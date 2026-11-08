"""Section 14 attacks against the generated-code sandbox, through the real dotnet-builder.

Each attack is a recorded "model answer" built in a temporary fixture folder: the repaired
RATECALC files plus one hostile file. The deny policy must fail the build, the time and
memory limits must end runaway code, and nothing may reach VERIFIED.
"""

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import CodeArtifact, VerificationRun
from app.services.agent.mock import FIXTURES, MockAgent
from app.services.jobs import module_handlers
from app.services.sandbox.client import DotnetBuilder, SandboxError
from tests.conftest import UserFactory
from tests.modules.helpers import Actors, detail, module_of, ready_project, start

REPAIRED = FIXTURES / "repair_v1" / "RATECALC"
SOCKET = "/run/builder/builder.sock"


def hostile_body(body: str) -> str:
    return f"""namespace Offshoot.Generated;

public static class Hostile
{{
    public static void Run()
    {{
        {body}
    }}
}}
"""


ATTACKS: dict[str, str] = {
    "process": hostile_body('System.Diagnostics.Process.Start("sh", "-c id");'),
    "http_client": hostile_body(
        'using var client = new System.Net.Http.HttpClient(); _ = client.GetStringAsync("http://1.1.1.1/").Result;'
    ),
    "socket": hostile_body(
        "using var socket = new System.Net.Sockets.Socket(System.Net.Sockets.AddressFamily.InterNetwork, "
        "System.Net.Sockets.SocketType.Stream, System.Net.Sockets.ProtocolType.Tcp);"
    ),
    "file_system": hostile_body('_ = System.IO.File.ReadAllText("/etc/passwd");'),
    "environment": hostile_body('_ = System.Environment.GetEnvironmentVariable("RUNNER_SHARED_SECRET");'),
    "reflection_emit": hostile_body(
        '_ = System.Reflection.Emit.AssemblyBuilder.DefineDynamicAssembly(new System.Reflection.AssemblyName("x"), '
        "System.Reflection.Emit.AssemblyBuilderAccess.Run);"
    ),
    "type_by_name": hostile_body('_ = System.Type.GetType("System.IO.File");'),
    "unsafe": hostile_body("unsafe { var value = 1; var pointer = &value; _ = *pointer; }"),
    "native": """namespace Offshoot.Generated;

public static class Hostile
{
    [System.Runtime.InteropServices.DllImport("libc")]
    private static extern int getpid();

    public static int Run() => getpid();
}
""",
}

RUNAWAY = """namespace Offshoot.Generated;

public static class Spin
{
    public static int Forever(int seed)
    {
        var value = seed;
        while (value >= 0)
        {
            value = (value + 1) % 1000;
        }
        return value;
    }
}
"""

RUNAWAY_TEST = """using Offshoot.Generated;
using Xunit;

namespace Offshoot.Generated.Tests;

public sealed class SpinTests
{
    [Fact]
    public void Spins() => Assert.Equal(0, Spin.Forever(1));
}
"""

MEMORY_TEST = """using Xunit;

namespace Offshoot.Generated.Tests;

public sealed class MemoryTests
{
    [Fact]
    public void Allocates_four_gigabytes()
    {
        var blocks = new List<byte[]>();
        for (var i = 0; i < 4096; i++)
        {
            var block = new byte[1024 * 1024];
            Array.Fill(block, (byte)1);
            blocks.Add(block);
        }
        Assert.NotEmpty(blocks);
    }
}
"""


def fixture_root(tmp_path: Path, extra: dict[str, str], replace: dict[str, str] | None = None) -> Path:
    """A workflow fixture root whose RATECALC migration is the repaired module plus `extra` files."""
    root = tmp_path / "workflow"
    target = root / "migrate_v1" / "RATECALC"
    shutil.copytree(REPAIRED, target)
    for name, content in {**extra, **(replace or {})}.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def use_fixtures(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(module_handlers, "get_agent_provider", lambda _settings: MockAgent(workflow_root=root))


@pytest.fixture
def actors(client: TestClient, make_user: UserFactory) -> Actors:
    return Actors(client, make_user)


@pytest.fixture
def ratecalc(client: TestClient, db: Session, actors: Actors) -> dict[str, Any]:
    project_id = ready_project(client, db, actors, ("RATECALC",))
    return module_of(client, actors, project_id, "RATECALC")


def _runs(db: Session, module_id: str) -> int:
    query = select(func.count()).select_from(VerificationRun).where(VerificationRun.module_id == uuid.UUID(module_id))
    return db.scalar(query) or 0


@pytest.mark.parametrize("attack", sorted(ATTACKS))
def test_a_policy_violation_fails_the_build_and_nothing_is_verified(
    client: TestClient,
    db: Session,
    actors: Actors,
    ratecalc: dict[str, Any],
    attack: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_fixtures(monkeypatch, fixture_root(tmp_path, {"src/Hostile.cs": ATTACKS[attack]}))
    monkeypatch.setattr(get_settings(), "repair_max_attempts", 0)
    job = start(client, actors, ratecalc["id"], "migrate")
    assert (job["status"], job["error_code"]) == ("FAILED", "POLICY_VIOLATION"), job
    found = detail(client, actors, ratecalc["id"])
    assert (found["state"], found["state_reason"]) == ("BUILD_FAILED", "POLICY_VIOLATION")
    artifact = client.get(f"/api/v1/modules/{ratecalc['id']}/artifacts/1", headers=actors.viewer).json()
    assert artifact["build_status"] == "POLICY_FAILED"
    violations = artifact["build_report"]["build"]["policy_violations"]
    assert violations
    assert all(item["file"] == "src/Hostile.cs" for item in violations)
    assert {item["id"] for item in violations} <= {"RS0030", "CS0227"}
    assert _runs(db, ratecalc["id"]) == 0


def test_an_infinite_loop_hits_the_test_time_limit_and_the_job_fails(
    client: TestClient,
    db: Session,
    actors: Actors,
    ratecalc: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_fixtures(monkeypatch, fixture_root(tmp_path, {"src/Spin.cs": RUNAWAY, "tests/SpinTests.cs": RUNAWAY_TEST}))
    monkeypatch.setattr(get_settings(), "sandbox_test_timeout_seconds", 5)
    job = start(client, actors, ratecalc["id"], "migrate")
    assert (job["status"], job["error_code"]) == ("FAILED", "SANDBOX_TIMEOUT"), job
    found = detail(client, actors, ratecalc["id"])
    assert (found["state"], found["state_reason"]) == ("BUILD_FAILED", "SANDBOX_TIMEOUT")
    artifact = client.get(f"/api/v1/modules/{ratecalc['id']}/artifacts/1", headers=actors.viewer).json()
    assert artifact["build_status"] == "TIMED_OUT"
    assert artifact["build_report"]["tests"]["timed_out"] is True
    # A sandbox limit is not repaired blindly: one artifact, no repair attempt, nothing verified.
    assert client.get(f"/api/v1/modules/{ratecalc['id']}/artifacts", headers=actors.viewer).json()[0]["version"] == 1
    assert _runs(db, ratecalc["id"]) == 0


def test_an_infinite_loop_during_verification_fails_the_job_and_blocks_the_module(
    client: TestClient,
    db: Session,
    actors: Actors,
    ratecalc: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit tests pass, but the module spins on one input the harness generates (kWh 99999)."""
    entry = (REPAIRED / "src" / "ModuleEntry.cs").read_text()
    spinning = entry.replace(
        "    public static string Process(string record)\n    {\n",
        "    public static string Process(string record)\n    {\n"
        '        if (FixedWidth.Field(record, 3, 5) == "99999")\n        {\n'
        "            _ = Spin.Forever(1);\n        }\n",
        1,
    )
    assert spinning != entry
    root = fixture_root(tmp_path, {"src/Spin.cs": RUNAWAY}, {"src/ModuleEntry.cs": spinning})
    use_fixtures(monkeypatch, root)
    monkeypatch.setattr(get_settings(), "sandbox_run_timeout_seconds", 5)
    job = start(client, actors, ratecalc["id"], "migrate")
    assert job["status"] == "SUCCEEDED", job
    verify_job = client.get(f"/api/v1/jobs/{job['metrics']['verify_job_id']}", headers=actors.viewer).json()
    assert (verify_job["status"], verify_job["error_code"]) == ("FAILED", "SANDBOX_TIMEOUT"), verify_job
    found = detail(client, actors, ratecalc["id"])
    assert (found["state"], found["state_reason"]) == ("BLOCKED", "SANDBOX_TIMEOUT")
    assert _runs(db, ratecalc["id"]) == 0


def test_the_memory_limit_ends_a_runaway_allocation_and_the_job_fails(
    client: TestClient,
    db: Session,
    actors: Actors,
    ratecalc: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_fixtures(monkeypatch, fixture_root(tmp_path, {"tests/MemoryTests.cs": MEMORY_TEST}))
    job = start(client, actors, ratecalc["id"], "migrate")
    assert (job["status"], job["error_code"]) == ("FAILED", "SANDBOX_MEMORY_LIMIT"), job
    found = detail(client, actors, ratecalc["id"])
    assert (found["state"], found["state_reason"]) == ("BUILD_FAILED", "SANDBOX_MEMORY_LIMIT")
    artifact = db.scalar(select(CodeArtifact).where(CodeArtifact.produced_by_job == uuid.UUID(job["id"])))
    assert artifact is not None
    assert artifact.build_status == "MEMORY_LIMIT"
    assert artifact.build_report["tests"]["out_of_memory"] is True
    assert _runs(db, ratecalc["id"]) == 0


# --- The builder container itself ---


@pytest.fixture(scope="module")
def builder() -> DotnetBuilder:
    return DotnetBuilder(SOCKET, os.environ["RUNNER_SHARED_SECRET"], 120)


def test_the_builder_has_no_network_interface_but_loopback(builder: DotnetBuilder) -> None:
    assert builder.isolation_probe()["interfaces"] == ["lo"]


def test_executed_code_cannot_open_sockets_or_reach_anything(builder: DotnetBuilder) -> None:
    probe = builder.isolation_probe()
    assert "'inet': 'blocked'" in probe["filtered"]
    assert "'inet6': 'blocked'" in probe["filtered"]
    # The mutation step runs without the seccomp filter, and still reaches nothing.
    assert "'internet': 'reachable'" not in probe["unfiltered"]
    assert "'orchestrator_dns': 'resolves'" not in probe["unfiltered"]
    assert probe["uid"] == 10001


def test_executed_code_does_not_see_the_runner_secret(builder: DotnetBuilder) -> None:
    probe = builder.isolation_probe()
    assert "RUNNER_SHARED_SECRET" not in probe["filtered"]
    assert "RUNNER_SHARED_SECRET" not in probe["unfiltered"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/info"),
        ("GET", "/v1/isolation-probe"),
        ("POST", "/v1/build"),
        ("POST", "/v1/run"),
        ("POST", "/v1/mutate"),
    ],
)
@pytest.mark.parametrize("token", [None, "", "wrong-token-of-enough-length"])
def test_the_builder_refuses_unauthenticated_calls(method: str, path: str, token: str | None) -> None:
    headers = {} if token is None else {"X-Runner-Token": token}
    with httpx.Client(transport=httpx.HTTPTransport(uds=SOCKET), base_url="http://builder") as raw:
        response = raw.request(method, path, json={"files": [], "records": []}, headers=headers, timeout=30)
    assert response.status_code == 401


def test_the_builder_health_check_needs_no_token() -> None:
    with httpx.Client(transport=httpx.HTTPTransport(uds=SOCKET), base_url="http://builder") as raw:
        assert raw.get("/healthz", timeout=30).status_code == 200


@pytest.mark.parametrize(
    "path",
    ["src/../Program.cs", "Generated/Offshoot.Generated.csproj", "src/Thing.csproj", "/etc/passwd", "tests/a/b.cs"],
)
def test_the_builder_refuses_files_outside_the_allowlist(builder: DotnetBuilder, path: str) -> None:
    with pytest.raises(SandboxError) as caught:
        builder.build([{"path": path, "content": "class X {}"}])
    assert caught.value.code == "SANDBOX_REJECTED"


def test_the_builder_reports_its_limits() -> None:
    with httpx.Client(transport=httpx.HTTPTransport(uds=SOCKET), base_url="http://builder") as raw:
        info = raw.get("/v1/info", headers={"X-Runner-Token": os.environ["RUNNER_SHARED_SECRET"]}, timeout=30).json()
    assert info["limits"]["test_timeout_seconds"] <= 60
    assert info["limits"]["run_timeout_seconds"] <= 60
    assert info["limits"]["run_memory_mb"] == 512
