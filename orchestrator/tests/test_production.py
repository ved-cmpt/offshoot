"""Production and public-demo behaviour (ADR-047, ADR-048): no code execution, the request
guards, the same-origin app with its CSP, the proxy-aware client address, and the demo snapshot
with its daily reset."""

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from app.core.client_ip import client_address
from app.core.config import Settings, get_settings
from app.core.rate_limit import write_limiter
from app.db.models import AuditLog, DemoSnapshot, Job, Project, Rule
from app.db.session import get_session_factory
from app.scripts import reset_demo
from app.services import demo_snapshot
from app.services.demo_reset import is_due, reset_if_due
from tests.agent.helpers import analyze, extract, make_project
from tests.conftest import CSRF, UserFactory, bearer, login_as


def engineer_headers(client: TestClient, make_user: UserFactory) -> dict[str, str]:
    return bearer(login_as(client, make_user("ENGINEER")))


@pytest.fixture
def fresh_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Build an app after changing settings that are read when the app is created."""

    def build(**changes: Any) -> TestClient:
        for name, value in changes.items():
            monkeypatch.setattr(get_settings(), name, value)
        from app.main import create_app

        write_limiter.reset()
        return TestClient(create_app(), base_url="http://localhost:8100")

    yield build
    write_limiter.reset()


# --- Client address ---


def connection(peer: str, forwarded: str | None = None) -> HTTPConnection:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return HTTPConnection({"type": "http", "client": (peer, 1234), "headers": headers})


@pytest.mark.parametrize(
    ("hops", "forwarded", "expected"),
    [
        (0, "1.1.1.1", "10.0.0.9"),  # No trusted proxy: the header is ignored.
        (1, "6.6.6.6, 2.2.2.2", "2.2.2.2"),  # The client forged the left entry.
        (2, "6.6.6.6, 2.2.2.2, 3.3.3.3", "2.2.2.2"),
        (1, None, "10.0.0.9"),
        (2, "2.2.2.2", "2.2.2.2"),
    ],
)
def test_the_client_address_trusts_only_the_configured_proxies(hops: int, forwarded: str | None, expected: str) -> None:
    assert client_address(connection("10.0.0.9", forwarded), hops) == expected


def test_a_header_the_edge_overwrites_wins_over_the_forwarded_chain() -> None:
    request = HTTPConnection(
        {
            "type": "http",
            "client": ("10.0.0.9", 1234),
            "headers": [(b"x-forwarded-for", b"6.6.6.6, 10.1.1.1"), (b"cf-connecting-ip", b"198.51.100.7")],
        }
    )
    assert client_address(request, 1, "cf-connecting-ip") == "198.51.100.7"
    assert client_address(request, 1, "true-client-ip") == "10.1.1.1"  # Absent: the chain decides.
    assert client_address(request, 0, "") == "10.0.0.9"


def test_an_admin_sees_how_their_own_address_is_resolved(client: TestClient, make_user: UserFactory) -> None:
    admin = bearer(login_as(client, make_user("ADMIN")))
    body = client.get("/api/v1/admin/users/me/address", headers={**admin, "X-Forwarded-For": "203.0.113.5"}).json()
    assert body["headers"] == {"x-forwarded-for": "203.0.113.5"}
    assert body["x_forwarded_for_entries"] == 1
    assert body["resolved"] == body["peer"]  # The test stack trusts no proxy.
    viewer = bearer(login_as(client, make_user("VIEWER")))
    assert client.get("/api/v1/admin/users/me/address", headers=viewer).status_code == 403


def test_the_app_page_declares_utf8(fresh_app: Any, static_dir: Path) -> None:
    page = fresh_app(static_dir=str(static_dir)).get("/")
    assert page.headers["Content-Type"] == "text/html; charset=utf-8"
    script = fresh_app(static_dir=str(static_dir)).get("/main-ABCDEFGH.js")
    assert "charset=utf-8" in script.headers["Content-Type"]


def test_a_plain_postgres_url_gets_the_psycopg_driver() -> None:
    settings = Settings(
        database_url="postgresql://user:pw@host.example/db?sslmode=require",  # type: ignore[arg-type]
        migration_database_url="postgres://owner:pw@host.example/db",  # type: ignore[arg-type]
        jwt_secret="x" * 40,  # type: ignore[arg-type]
    )
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://user:pw@host.example/db?")
    assert settings.migration_database_url is not None
    assert settings.migration_database_url.get_secret_value().startswith("postgresql+psycopg://owner")


def test_production_refuses_placeholder_secrets_and_insecure_cookies() -> None:
    base = {"database_url": "postgresql://u:p@h/d", "app_env": "production"}
    with pytest.raises(ValueError, match="placeholder"):
        Settings(**base, jwt_secret="local-dev-only-change-me-at-least-32-chars", cookie_secure=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(**base, jwt_secret="y" * 40, cookie_secure=False)  # type: ignore[arg-type]


# --- No code execution ---


def test_the_public_config_says_whether_code_runs(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/api/v1/config").json()["execution_enabled"] is True
    monkeypatch.setattr(get_settings(), "execution_enabled", False)
    monkeypatch.setattr(get_settings(), "demo_auto_reset_hours", 24.0)
    body = client.get("/api/v1/config").json()
    assert (body["execution_enabled"], body["demo_reset_hours"]) == (False, 24.0)


@pytest.mark.parametrize("action", ["migrate", "repair", "verify", "mutate", "shadow-replay"])
def test_every_code_running_endpoint_is_off_without_a_sandbox(
    client: TestClient, make_user: UserFactory, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    headers = engineer_headers(client, make_user)
    monkeypatch.setattr(get_settings(), "execution_enabled", False)
    response = client.post(f"/api/v1/modules/{uuid.uuid4()}/{action}", headers=headers, json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "EXECUTION_DISABLED"


# --- Volume caps ---


def test_the_demo_stops_new_jobs_at_the_daily_cap(
    client: TestClient, db: Session, make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = engineer_headers(client, make_user)
    project = make_project(db)
    db.commit()
    recent = db.scalar(
        select(func.count()).select_from(Job).where(Job.created_at > func.now() - text("interval '1 day'"))
    )
    monkeypatch.setattr(get_settings(), "demo_daily_job_cap", (recent or 0) + 1)
    assert client.post(f"/api/v1/projects/{project.id}/analyze", headers=headers).status_code == 202
    refused = client.post(f"/api/v1/projects/{project.id}/programs/MTRVAL/extract-rules", headers=headers)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "DEMO_CAP_REACHED"
    assert refused.headers["Retry-After"] == "3600"
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert client.post(f"/api/v1/projects/{project.id}/plan", headers=headers).status_code != 429


def test_mutating_requests_are_rate_limited_per_address(fresh_app: Any) -> None:
    app_client = fresh_app(write_rate_limit_per_minute=3)
    codes = [app_client.post("/api/v1/auth/logout").status_code for _ in range(4)]
    assert codes[:3] == [403, 403, 403]  # Counted even when refused for another reason.
    assert codes[3] == 429
    limited = app_client.post("/api/v1/auth/logout")
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.headers["X-Content-Type-Options"] == "nosniff"
    # Reads are never limited.
    assert app_client.get("/api/v1/healthz").status_code == 200


def test_bodies_over_the_cap_are_refused_before_the_app_reads_them(fresh_app: Any) -> None:
    app_client = fresh_app(max_request_bytes=2048)
    response = app_client.post(
        "/api/v1/auth/login", content=b"{" + b" " * 4096 + b"}", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_a_secure_deployment_accepts_its_own_https_origin_behind_a_tls_proxy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = {"Origin": "https://localhost:8100", **CSRF}
    assert client.post("/api/v1/auth/refresh", headers=origin).json()["error"]["code"] == "CSRF_ORIGIN"
    monkeypatch.setattr(get_settings(), "cookie_secure", True)
    response = client.post("/api/v1/auth/refresh", headers=origin)
    assert response.status_code == 401  # Past the origin check; there is simply no cookie.
    other = client.post("/api/v1/auth/refresh", headers={"Origin": "https://evil.example", **CSRF})
    assert other.json()["error"]["code"] == "CSRF_ORIGIN"


# --- The same-origin app ---


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><head><link rel="stylesheet" href="styles-ABCDEFGH.css"></head>'
        '<body><app-root></app-root><script src="main-ABCDEFGH.js" type="module"></script></body></html>'
    )
    (tmp_path / "main-ABCDEFGH.js").write_text("console.log(1)")
    (tmp_path / "favicon.ico").write_bytes(b"\x00")
    (tmp_path.parent / "secret.txt").write_text("outside")
    return tmp_path


def test_the_app_is_served_with_a_fresh_nonce_and_a_strict_policy(fresh_app: Any, static_dir: Path) -> None:
    app_client = fresh_app(static_dir=str(static_dir), cookie_secure=True)
    first, second = app_client.get("/"), app_client.get("/app/projects/123/modules")
    for page in (first, second):
        assert page.status_code == 200
        policy = page.headers["Content-Security-Policy"]
        nonce = re.search(r"'nonce-([^']+)'", policy)
        assert nonce is not None
        assert f'ngCspNonce="{nonce.group(1)}"' in page.text
        assert "unsafe-inline" not in policy
        assert "frame-ancestors 'none'" in policy
        assert "script-src 'self'" in policy
        assert "upgrade-insecure-requests" in policy
        assert page.headers["Cache-Control"] == "no-store"
        assert page.headers["Strict-Transport-Security"].startswith("max-age=")
    assert first.headers["Content-Security-Policy"] != second.headers["Content-Security-Policy"]


def test_hashed_files_are_immutable_and_api_paths_never_fall_through(fresh_app: Any, static_dir: Path) -> None:
    app_client = fresh_app(static_dir=str(static_dir))
    script = app_client.get("/main-ABCDEFGH.js")
    assert script.status_code == 200
    assert script.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert script.headers["Content-Type"].startswith("text/javascript")
    assert app_client.get("/favicon.ico").headers["Cache-Control"] == "public, max-age=3600"
    for path in ("/api/v1/nothing-here", "/api/v2/x", "/missing-ABCDEFGH.js"):
        response = app_client.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "NOT_FOUND"
    # The landing page's files: fonts, the manifest, the sitemap and its data, by type.
    (static_dir / "fonts").mkdir()
    (static_dir / "fonts" / "inter-var.woff2").write_bytes(b"wOF2")
    (static_dir / "manifest.webmanifest").write_text("{}")
    (static_dir / "data").mkdir()
    (static_dir / "data" / "landing-snapshot.json").write_text("{}")
    expected = {
        "/fonts/inter-var.woff2": "font/woff2",
        "/manifest.webmanifest": "application/manifest+json",
        "/data/landing-snapshot.json": "application/json",
    }
    for path, kind in expected.items():
        response = app_client.get(path)
        assert response.status_code == 200, path
        assert response.headers["Content-Type"].startswith(kind), path
    # Text files are gzipped for clients that accept it; small ones and images are not.
    (static_dir / "big-ABCDEFGH.js").write_text("console.log('offshoot');\n" * 200)
    zipped = app_client.get("/big-ABCDEFGH.js", headers={"Accept-Encoding": "gzip"})
    assert zipped.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in zipped.headers["Vary"]
    assert zipped.headers["Content-Type"] == "text/javascript; charset=utf-8"
    assert zipped.text.count("offshoot") == 200
    plain = app_client.get("/big-ABCDEFGH.js", headers={"Accept-Encoding": "identity"})
    assert "Content-Encoding" not in plain.headers
    assert "Content-Encoding" not in app_client.get("/favicon.ico", headers={"Accept-Encoding": "gzip"}).headers
    # The old app paths and the landing page are all the app's page.
    for path in ("/", "/login", "/projects/1/rules", "/app/login"):
        assert "<app-root" in app_client.get(path).text, path
    escaped = app_client.get("/..%2Fsecret.txt")
    assert "outside" not in escaped.text
    assert app_client.get("/api/v1/healthz").json() == {"status": "ok"}
    assert app_client.get("/healthz").json() == {"status": "ok"}


# --- The demo snapshot and its daily reset ---


def seeded_project(client: TestClient, db: Session, make_user: UserFactory) -> tuple[Project, dict[str, Any]]:
    engineer = make_user("ENGINEER")
    headers = bearer(login_as(client, engineer))
    project = make_project(db, "BUNDLED")
    db.commit()
    analyze(client, headers, project.id)
    assert extract(client, headers, project.id, "MTRVAL")["status"] == "SUCCEEDED"
    return project, engineer


def rule_states(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, tuple[str, int]]:
    db.expire_all()
    rows = db.execute(select(Rule.id, Rule.state, Rule.version).where(Rule.project_id == project_id)).all()
    return {rule_id: (state, version) for rule_id, state, version in rows}


def test_a_snapshot_restores_the_project_exactly_and_audits_the_reset(
    client: TestClient, db: Session, make_user: UserFactory
) -> None:
    project, _engineer = seeded_project(client, db, make_user)
    snapshot = demo_snapshot.capture(db, project)
    db.commit()
    before = rule_states(db, project.id)
    assert before and snapshot.row_counts["rules"] == len(before)
    assert snapshot.row_counts["inventory_items"] > 0

    # A visitor changes things: a rule is deleted, another is decided.
    victim, changed = list(before)[:2]
    db.execute(update(Rule).where(Rule.id == changed).values(state="REJECTED", version=Rule.version + 1))
    db.delete(db.get(Rule, victim))
    db.commit()
    assert rule_states(db, project.id) != before

    restored = demo_snapshot.restore(db, snapshot)
    db.commit()
    assert restored == snapshot.row_counts
    assert rule_states(db, project.id) == before
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "demo.reset").order_by(AuditLog.id.desc())).first()
    assert entry is not None
    assert entry.safe_metadata["mode"] == "snapshot"
    assert entry.safe_metadata["rules"] == len(before)


def test_a_snapshot_maps_users_by_email_into_another_database(
    client: TestClient, db: Session, make_user: UserFactory
) -> None:
    project, engineer = seeded_project(client, db, make_user)
    payload = demo_snapshot.build_payload(db, project)
    # Pretend the snapshot came from a database where this engineer had another id.
    elsewhere = str(uuid.uuid4())
    payload["users"] = {elsewhere: engineer["email"]}
    for job in payload["tables"]["jobs"]:
        job["requested_by"] = elsewhere
    db.execute(update(Project).where(Project.id == project.id).values(name=f"Moved {uuid.uuid4().hex}"))
    db.commit()
    snapshot = demo_snapshot.store(db, payload)
    demo_snapshot.restore(db, snapshot)
    db.commit()
    requested = set(db.scalars(select(Job.requested_by).where(Job.project_id == project.id)).all())
    assert requested == {engineer["id"]}


def test_a_snapshot_refuses_a_project_with_unfinished_jobs(db: Session) -> None:
    project = make_project(db, "BUNDLED")
    db.add(Job(project_id=project.id, kind="ANALYZE", status="QUEUED", input_hash=uuid.uuid4().hex, payload={}))
    db.commit()
    with pytest.raises(demo_snapshot.SnapshotError, match="queued or running"):
        demo_snapshot.build_payload(db, project)


def test_the_daily_reset_runs_once_when_due(client: TestClient, db: Session, make_user: UserFactory) -> None:
    assert is_due(datetime(2026, 1, 1, tzinfo=UTC), 24, datetime(2026, 1, 2, tzinfo=UTC))
    assert not is_due(datetime(2026, 1, 1, tzinfo=UTC), 24, datetime(2026, 1, 1, 23, tzinfo=UTC))
    project, _engineer = seeded_project(client, db, make_user)
    snapshot = demo_snapshot.capture(db, project)
    db.commit()
    settings = get_settings().model_copy(update={"demo_auto_reset_hours": 24.0})
    now = datetime.now(UTC)
    assert reset_if_due(get_session_factory(), settings, now=lambda: now) is None  # Captured just now.
    later = now + timedelta(hours=25)
    restored = reset_if_due(get_session_factory(), settings, now=lambda: later)
    assert restored == snapshot.row_counts
    assert reset_if_due(get_session_factory(), settings, now=lambda: later) is None  # Not due again yet.
    db.expire_all()
    stored = db.get(DemoSnapshot, snapshot.id)
    assert stored is not None and stored.last_restored_at is not None
    off = settings.model_copy(update={"demo_auto_reset_hours": 0.0})
    assert reset_if_due(get_session_factory(), off, now=lambda: later + timedelta(days=9)) is None


def test_the_guarded_reset_uses_the_snapshot_where_code_cannot_run(
    db: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demo_snapshot, "latest", lambda _db, _name=None: None)
    monkeypatch.setattr(get_settings(), "execution_enabled", False)
    assert reset_demo.main(["--confirm"]) == 2
    assert "No demo snapshot" in capsys.readouterr().err
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert reset_demo.main(["--confirm", "--snapshot"]) == 2
