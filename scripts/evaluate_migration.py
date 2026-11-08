"""Migration and verification measures from stored runs (Blueprint Section 6.5).

    python scripts/evaluate_migration.py --api http://localhost:8100 [--project NAME]

Reads modules, artifacts and verification runs through the public API as the demo viewer and
prints, per module and in total: whether the first artifact compiled, its unit tests, whether
its first full verification was 100% equivalent, whether the latest artifact is, and how many
repair attempts were used. Every number comes from stored rows; nothing is re-run.

Standard library only, like evaluate_rules.py, so it needs no project environment.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_rules import VIEWER_EMAIL, load_env_value  # noqa: E402

COMPILED = {"BUILT", "TESTS_FAILED"}


def _get(url: str, token: str | None = None, data: dict[str, Any] | None = None) -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers=headers)  # noqa: S310 - a local URL given by the operator.
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.load(response)


def _full_runs(runs: list[dict[str, Any]], artifact_id: str) -> list[dict[str, Any]]:
    chosen = [run for run in runs if run["artifact_id"] == artifact_id and run["kind"] == "FULL"]
    return sorted(chosen, key=lambda run: run["created_at"])


def measure_module(api: str, token: str, module: dict[str, Any]) -> dict[str, Any] | None:
    artifacts = _get(f"{api}/api/v1/modules/{module['id']}/artifacts", token)
    if not artifacts:
        return None
    artifacts = sorted(artifacts, key=lambda item: item["version"])
    first, last = artifacts[0], artifacts[-1]
    detail = _get(f"{api}/api/v1/modules/{module['id']}/artifacts/{first['version']}", token)
    tests = (detail.get("build_report") or {}).get("tests") or {}
    runs = _get(f"{api}/api/v1/modules/{module['id']}/runs", token)
    first_runs, last_runs = _full_runs(runs, first["id"]), _full_runs(runs, last["id"])
    first_run = first_runs[0] if first_runs else None
    last_run = last_runs[-1] if last_runs else None
    return {
        "program": module["program"],
        "state": module["state"],
        "artifacts": len(artifacts),
        "repairs_used": sum(1 for item in artifacts if item["kind"] == "REPAIR"),
        "model": detail.get("model_id"),
        "first_compiled": first["build_status"] in COMPILED,
        "first_build_status": first["build_status"],
        "first_unit_tests": f"{tests.get('passed', 0)} of {tests.get('total', 0)}" if tests else None,
        "first_unit_tests_pass": bool(tests) and tests.get("failed", 1) == 0 and tests.get("total", 0) > 0,
        "first_equivalence": f"{first_run['passed']} of {first_run['cases']}" if first_run else None,
        "first_equivalent": bool(first_run) and first_run["failed"] == 0,
        "latest_equivalence": f"{last_run['passed']} of {last_run['cases']}" if last_run else None,
        "latest_equivalent": bool(last_run) and last_run["failed"] == 0,
        "latest_coverage_pct": last_run["coverage_pct"] if last_run else None,
        "latest_mutation_score": last_run["mutation_score"] if last_run else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8100")
    parser.add_argument("--project", default="BillRite")
    args = parser.parse_args()
    password = load_env_value("DEMO_PASSWORD_VIEWER")
    if not password:
        print("DEMO_PASSWORD_VIEWER is not set", file=sys.stderr)
        return 2
    token = _get(f"{args.api}/api/v1/auth/login", data={"email": VIEWER_EMAIL, "password": password})["access_token"]
    project, offset = None, 0
    while project is None:
        page = _get(f"{args.api}/api/v1/projects?limit=50&offset={offset}", token)
        project = next((item for item in page["items"] if item["name"] == args.project), None)
        offset += len(page["items"])
        if not page["items"] or offset >= page["total"]:
            break
    if project is None:
        print(f"No project named {args.project}", file=sys.stderr)
        return 1
    modules = _get(f"{args.api}/api/v1/projects/{project['id']}/modules", token)
    rows = [row for module in modules if (row := measure_module(args.api, token, module)) is not None]
    count = len(rows)
    totals = {
        "modules_migrated": count,
        "compiled_first_attempt": sum(row["first_compiled"] for row in rows),
        "unit_tests_pass_first_attempt": sum(row["first_unit_tests_pass"] for row in rows),
        "equivalent_first_attempt": sum(row["first_equivalent"] for row in rows),
        "equivalent_latest": sum(row["latest_equivalent"] for row in rows),
        "repair_attempts_used": sum(row["repairs_used"] for row in rows),
    }
    print(json.dumps({"project": args.project, "totals": totals, "modules": rows}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
