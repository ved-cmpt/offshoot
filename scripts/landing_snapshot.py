"""The landing page's data: a static snapshot of stored runs, with provenance (ADR-054).

    python scripts/landing_snapshot.py --api https://offshoot-go2y.onrender.com
    python scripts/landing_snapshot.py --check

The landing page is public and never signs in, so it reads this file instead of the API. The
script signs in as the published demo viewer, reads the bundled BillRite project's modules,
verification runs, artifacts and rules, and writes them to
frontend/public/data/landing-snapshot.json together with:

- verbatim excerpts of the COBOL sources (legacy/billrite), each checked against the SHA-256
  the verification run recorded for that file;
- the repaired RATECALC translation, from the recorded repair fixture, with its measured
  numbers from docs/EVALUATION.md (the public demo shows the blocked run; the repair runs
  only where code can execute, ADR-047);
- the evaluation headline from docs/EVALUATION.md.

`--check` needs no network: it rebuilds the repository parts and requires them to equal the
committed file, and checks that the numbers agree with each other (CI runs it). The test
`tests/test_seed.py::test_the_landing_snapshot_matches_the_seed` rebuilds the API part from a
fresh seed and requires it to equal the committed one, ids and times aside.

Standard library only, like evaluate_rules.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "frontend" / "public" / "data" / "landing-snapshot.json"
LEGACY = REPO / "legacy" / "billrite"
EVALUATION = REPO / "docs" / "EVALUATION.md"
REPAIR_FIXTURE = REPO / "orchestrator" / "app" / "services" / "agent" / "fixtures" / "repair_v1" / "RATECALC"
VIEWER = "viewer"
PASSWORD = "demo1234"  # noqa: S105 - published on purpose (ADR-050); not a secret.
SCHEMA = 1
# The stored case the landing page explains: residential, 610 kWh, a non-summer month.
FOCUS_INPUT = "R1200610"

Get = Callable[[str], Any]

# Fields that differ between databases or over time, and so are left out of comparisons.
DRAW = re.compile(r"seeded draw \d+")
VOLATILE = {"id", "module_id", "run_id", "artifact_id", "created_at", "project_id", "state", "facade_mode"}


# --- The API part --------------------------------------------------------------------------


def _demo_project(projects: list[dict[str, Any]]) -> dict[str, Any]:
    bundled = [item for item in projects if item["source_kind"] == "BUNDLED"]
    for item in bundled:
        if item["name"] == "BillRite":
            return item
    raise SystemExit("The bundled BillRite project is missing.")


def _full_runs(get: Get, module_id: str) -> list[dict[str, Any]]:
    runs = [run for run in get(f"/api/v1/modules/{module_id}/runs") if run["kind"] == "FULL"]
    return sorted(runs, key=lambda run: run["created_at"])


def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "status", "seed", "cases", "passed", "failed", "coverage_pct", "mutation_score", "created_at")
    return {key: run.get(key) for key in keys}


def _lines(content: str, first: str, last: str) -> dict[str, Any]:
    """The lines from the first containing `first` to the next containing `last`, numbered."""
    lines = content.split("\n")
    start = next(index for index, line in enumerate(lines) if first in line)
    end = next(index for index in range(start, len(lines)) if last in lines[index])
    return {"start": start + 1, "lines": lines[start : end + 1]}


def _artifact_excerpt(artifact: dict[str, Any], path: str, first: str, last: str) -> dict[str, Any]:
    content = next(item["content"] for item in artifact["file_contents"] if item["path"] == path)
    tests = (artifact.get("build_report") or {}).get("tests") or {}
    return {
        "file": path,
        "artifact_version": artifact["version"],
        "artifact_kind": artifact["kind"],
        "sha256": artifact["sha256"],
        "unit_tests": {"passed": tests.get("passed"), "total": tests.get("total")},
        **_lines(content, first, last),
    }


def _rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rule["id"],
        "program": rule["program"],
        "title": rule["title"],
        "statement": rule["statement"],
        "state": rule["state"],
        "flags": rule["flags"],
        "flag_details": rule["flag_details"],
        "spans": [
            {
                "file": span["file"],
                "start_line": span["start_line"],
                "end_line": span["end_line"],
                "valid": span["valid"],
            }
            for span in rule["spans"]
        ],
        "examples": rule["examples"],
    }


def build_api_part(get: Get) -> dict[str, Any]:
    project = _demo_project(get("/api/v1/projects")["items"])
    pid = project["id"]
    modules = sorted(get(f"/api/v1/projects/{pid}/modules"), key=lambda item: item["order_index"])
    by_program = {module["program"]: module for module in modules}
    rules: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = get(f"/api/v1/projects/{pid}/rules?offset={offset}")
        rules.extend(page["items"])
        offset += len(page["items"])
        if not page["items"] or offset >= page["total"]:
            break

    summaries = []
    for module in modules:
        runs = _full_runs(get, module["id"])
        latest = runs[-1] if runs else None
        summaries.append(
            {
                "program": module["program"],
                "id": module["id"],
                "service": module["target_service"],
                "order": module["order_index"],
                "state": module["state"],
                "facade_mode": module["facade_mode"],
                "run": _run_summary(latest) if latest else None,
            }
        )

    # The rounding defect: RATECALC's first full verification, on the first translation.
    ratecalc = by_program["RATECALC"]
    first_run = _full_runs(get, ratecalc["id"])[0]
    detail = get(f"/api/v1/modules/{ratecalc['id']}/runs/{first_run['id']}")
    report = detail["report"]
    artifact = get(f"/api/v1/modules/{ratecalc['id']}/artifacts/{report['artifact']['version']}")
    mismatches = [
        {
            "case": item["case"],
            "input": item["input"],
            "input_fields": item["input_fields"],
            "label": item["label"],
            "source": item["source"],
            "diffs": [{"field": d["field"], "legacy": d["legacy"], "modern": d["modern"]} for d in item["diffs"]],
        }
        for item in report["mismatches"]
    ]
    rounding = {
        "module_id": ratecalc["id"],
        "run_id": first_run["id"],
        "created_at": first_run["created_at"],
        "seed": report["seed"],
        "cases": report["cases"],
        "passed": report["passed"],
        "failed": report["failed"],
        "by_source": report["by_source"],
        "failed_by_source": report["failed_by_source"],
        "mismatched_fields": report["mismatched_fields"],
        "mismatches": mismatches,
        "coverage": {"pct": report["coverage"]["pct"], "missed": report["coverage"]["missed"]},
        "gates": [
            {key: gate.get(key) for key in ("gate", "label", "passed", "value", "threshold", "unit")}
            for gate in detail["gates"]
        ],
        "versions": {
            "compiler": report["versions"]["legacy"]["compiler"],
            "harness": report["versions"]["harness"],
            "generator": report["versions"]["generator"],
            "hypothesis": report["versions"]["hypothesis"],
            "dotnet_sdk": report["versions"]["modern"]["sdk"],
        },
        "legacy_sha256": report["versions"]["legacy"]["sources"],
        "csharp_first": _artifact_excerpt(
            artifact, "src/RateCalculator.cs", "var energy = RoundToCent", "public static decimal RoundToCent"
        ),
        "artifact_notes": artifact["notes"],
    }

    def latest_detail(program: str) -> dict[str, Any]:
        module = by_program[program]
        run = _full_runs(get, module["id"])[-1]
        run_detail = get(f"/api/v1/modules/{module['id']}/runs/{run['id']}")
        current = module["current_artifact"]["version"]
        return {
            "module_id": module["id"],
            "run_id": run["id"],
            "created_at": run["created_at"],
            "run": run_detail,
            "artifact": get(f"/api/v1/modules/{module['id']}/artifacts/{current}"),
        }

    def rule_titled(program: str, title: str) -> dict[str, Any]:
        return _rule(next(rule for rule in rules if rule["program"] == program and rule["title"] == title))

    latefee = latest_detail("LATEFEE")
    year_window = {
        "module_id": latefee["module_id"],
        "run_id": latefee["run_id"],
        "created_at": latefee["created_at"],
        "seed": latefee["run"]["seed"],
        "cases": latefee["run"]["cases"],
        "passed": latefee["run"]["passed"],
        "by_source": latefee["run"]["report"]["by_source"],
        "coverage_pct": latefee["run"]["coverage_pct"],
        "mutation_score": latefee["run"]["mutation_score"],
        "rule": rule_titled("LATEFEE", "Century window for two-digit years"),
        "csharp": _artifact_excerpt(
            latefee["artifact"], "src/LateFeeCalculator.cs", "public const int CenturyPivot", "1900 : 2000"
        ),
        "legacy_sha256": latefee["run"]["report"]["versions"]["legacy"]["sources"],
    }

    mtrval = latest_detail("MTRVAL")
    rollover = {
        "module_id": mtrval["module_id"],
        "run_id": mtrval["run_id"],
        "created_at": mtrval["created_at"],
        "seed": mtrval["run"]["seed"],
        "cases": mtrval["run"]["cases"],
        "passed": mtrval["run"]["passed"],
        "by_source": mtrval["run"]["report"]["by_source"],
        "coverage_pct": mtrval["run"]["coverage_pct"],
        "mutation_score": mtrval["run"]["mutation_score"],
        "rule": rule_titled("MTRVAL", "Rollover usage calculation"),
        "csharp": _artifact_excerpt(
            mtrval["artifact"], "src/MeterReadValidator.cs", "The dials count up to 99999", "return new MeterReadResult"
        ),
        "legacy_sha256": mtrval["run"]["report"]["versions"]["legacy"]["sources"],
    }

    flagged = [_rule(rule) for rule in rules if rule["program"] == "RATECALC" and rule["flags"]]
    injection = {
        "rules_proposed": sum(1 for rule in rules if rule["program"] == "RATECALC"),
        "flagged": sorted(flagged, key=lambda rule: rule["spans"][0]["start_line"] if rule["spans"] else 0),
    }

    counts: dict[str, int] = {}
    for rule in rules:
        counts[rule["state"]] = counts.get(rule["state"], 0) + 1
    inventory = get(f"/api/v1/projects/{pid}/inventory")
    return {
        "project": {
            "id": pid,
            "name": project["name"],
            "files": project["source_file_count"],
            "lines": project["source_line_count"],
        },
        "inventory": {
            "summary": inventory["summary"],
            "dead_paragraphs": [item["name"] for item in inventory["dead_code"]["paragraphs"]],
        },
        "modules": summaries,
        "rules": {"total": len(rules), "by_state": dict(sorted(counts.items()))},
        "rounding": rounding,
        "year_window": year_window,
        "rollover": rollover,
        "injection": injection,
    }


# --- The repository part -------------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cobol_excerpt(legacy: Path, relative: str, first: str, last: str, recorded: dict[str, str]) -> dict[str, Any]:
    path = legacy / relative
    sha = _sha(path)
    return {
        "file": relative,
        "sha256": sha,
        "matches_run": recorded.get(relative) == sha,
        **_lines(path.read_text(encoding="utf-8"), first, last),
    }


def _rates(legacy: Path) -> dict[str, dict[str, Any]]:
    found = {}
    for number, line in enumerate((legacy / "copy" / "RATES.cpy").read_text(encoding="utf-8").split("\n"), 1):
        match = re.search(r"05\s+(RT-[A-Z0-9-]+)\s+PIC\s+\S+\s+VALUE\s+([0-9.]+)\.", line)
        if match:
            found[match.group(1)] = {"value": match.group(2), "line": number}
    return found


def _evaluation_rows(text: str, heading: str) -> list[list[str]]:
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.split("\n"):
        if line.startswith("|") and not line.startswith("|---"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _plain(cell: str) -> str:
    return cell.replace("**", "").replace("`", "")


def build_repo_part(api: dict[str, Any], legacy: Path = LEGACY, evaluation: Path = EVALUATION) -> dict[str, Any]:
    rounding = api["rounding"]
    recorded = rounding["legacy_sha256"]
    rates = _rates(legacy)

    # The focus case's arithmetic, from the copybook's own constants.
    focus = next(item for item in rounding["mismatches"] if item["input"] == FOCUS_INPUT)
    kwh = int(focus["input_fields"]["RC-IN-KWH"])
    month = int(focus["input_fields"]["RC-IN-MONTH"])
    summer = int(rates["RT-SUMMER-FIRST-MM"]["value"]) <= month <= int(rates["RT-SUMMER-LAST-MM"]["value"])
    limit = int(rates["RT-RES-SUMMER-LIMIT" if summer else "RT-RES-TIER-LIMIT"]["value"])
    rate1, rate2 = Decimal(rates["RT-RES-TIER1-RATE"]["value"]), Decimal(rates["RT-RES-TIER2-RATE"]["value"])
    tier1_kwh, tier2_kwh = min(kwh, limit), max(0, kwh - limit)
    tier1, tier2 = tier1_kwh * rate1, tier2_kwh * rate2
    exact = tier1 + tier2
    half_up = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    half_even = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    energy = next(diff for diff in focus["diffs"] if diff["field"] == "RC-OUT-ENERGY")

    text = evaluation.read_text(encoding="utf-8")
    migration = _evaluation_rows(text, "## Migration and verification in mock mode (Run 03)")
    repaired = next(row for row in migration if row[0] == "RATECALC after one repair")
    headline = _evaluation_rows(text, "## Headline (Run 05)")

    repair_source = REPAIR_FIXTURE / "src" / "RateCalculator.cs"
    repair_excerpt = _lines(
        repair_source.read_text(encoding="utf-8"), "/// COMPUTE ... ROUNDED", "MidpointRounding.AwayFromZero"
    )

    return {
        "rounding_cobol": [
            cobol_excerpt(legacy, "src/RATECALC.cbl", "ROUNDED MEANS HALF-UP", "5000-EXIT", recorded),
            cobol_excerpt(legacy, "src/RATECALC.cbl", "7000-ADD-LEVY.", "7000-EXIT", recorded),
        ],
        "rounding_math": {
            "case": focus["case"],
            "input": focus["input"],
            "label": focus["label"],
            "kwh": kwh,
            "month": month,
            "season": "summer" if summer else "standard",
            "tier_limit": limit,
            "tier1": {"kwh": tier1_kwh, "rate": str(rate1), "amount": str(tier1)},
            "tier2": {"kwh": tier2_kwh, "rate": str(rate2), "amount": str(tier2)},
            "exact": str(exact),
            "half_up": str(half_up),
            "half_even": str(half_even),
            "legacy": energy["legacy"],
            "modern": energy["modern"],
            "consistent": str(half_up) == energy["legacy"] and str(half_even) == energy["modern"],
            "constants": {
                name: {"value": rates[name]["value"], "line": rates[name]["line"]}
                for name in ("RT-RES-TIER1-RATE", "RT-RES-TIER2-RATE", "RT-RES-TIER-LIMIT", "RT-LEVY-RATE")
            },
        },
        "repair": {
            "source": "orchestrator/app/services/agent/fixtures/repair_v1/RATECALC/src/RateCalculator.cs",
            "measured_in": "docs/EVALUATION.md, Migration and verification in mock mode (Run 03)",
            "unit_tests": _plain(repaired[2]),
            "identical": _plain(repaired[3]),
            "coverage": _plain(repaired[4]),
            "mutation": _plain(repaired[5]),
            "state": _plain(repaired[6]),
            "csharp": {"file": "src/RateCalculator.cs", **repair_excerpt},
        },
        "year_window_cobol": [
            cobol_excerpt(legacy, "src/LATEFEE.cbl", "Y2K WINDOW", "3000-EXIT", api["year_window"]["legacy_sha256"]),
            cobol_excerpt(
                legacy, "copy/RATES.cpy", "RT-CENTURY-PIVOT", "RT-CENTURY-PIVOT", api["year_window"]["legacy_sha256"]
            ),
        ],
        "rollover_cobol": [
            cobol_excerpt(
                legacy, "src/MTRVAL.cbl", "THE METER COUNTS UP TO 99999", "3100-EXIT", api["rollover"]["legacy_sha256"]
            ),
        ],
        "injection_cobol": [
            cobol_excerpt(
                legacy, "src/RATECALC.cbl", "COUNCIL ORDER 96-7: JUNE", "RC-IN-MONTH >= RT-SUMMER-FIRST-MM", recorded
            ),
        ],
        "evaluation": {
            "source": "docs/EVALUATION.md, Headline (Run 05)",
            "columns": headline[0],
            "rows": [[_plain(cell) for cell in row] for row in headline[1:]],
        },
    }


# --- Checks --------------------------------------------------------------------------------


def deterministic(value: Any) -> Any:
    """The snapshot without ids, times and visitor-changeable states, for comparison.

    A random case's label also loses its draw number: two seeds produced the same inputs, case
    numbers and results, but numbered one draw differently ("seeded draw 296" and "297"), because
    Hypothesis can discard a repeated draw in one run and not the other (ADR-054).
    """
    if isinstance(value, dict):
        return {
            key: (DRAW.sub("seeded draw", item) if key == "label" and isinstance(item, str) else deterministic(item))
            for key, item in value.items()
            if key not in VOLATILE
        }
    if isinstance(value, list):
        return [deterministic(item) for item in value]
    return value


def differences(left: Any, right: Any, path: str = "") -> list[str]:
    """The paths at which two JSON-like values differ, for a readable test failure."""
    if isinstance(left, dict) and isinstance(right, dict):
        found: list[str] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                found.append(f"{path}.{key} (only on one side)")
            else:
                found.extend(differences(left[key], right[key], f"{path}.{key}"))
        return found
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [f"{path} (lengths {len(left)} and {len(right)})"]
        return [
            item
            for index, pair in enumerate(zip(left, right, strict=True))
            for item in differences(*pair, f"{path}[{index}]")
        ]
    return [] if left == right else [f"{path}: {left!r} != {right!r}"]


def problems(snapshot: dict[str, Any]) -> list[str]:
    found = []
    api, repo = snapshot["api"], snapshot["repo"]
    rounding = api["rounding"]
    if rounding["passed"] + rounding["failed"] != rounding["cases"]:
        found.append("rounding: passed + failed is not the number of cases")
    if len(rounding["mismatches"]) != rounding["failed"]:
        found.append("rounding: not every mismatch is in the snapshot")
    if not repo["rounding_math"]["consistent"]:
        found.append("rounding: the copybook arithmetic does not give the stored legacy and modern values")
    for group in ("rounding_cobol", "year_window_cobol", "rollover_cobol", "injection_cobol"):
        for excerpt in repo[group]:
            if not excerpt["matches_run"]:
                found.append(f"{excerpt['file']}: differs from the source the run recorded")
    if not any(rule["spans"] and rule["spans"][0]["start_line"] == 135 for rule in api["injection"]["flagged"]):
        found.append("injection: no flagged rule cites the planted comment")
    return found


# --- Command line --------------------------------------------------------------------------


def _http_get(api: str, token: str) -> Get:
    def get(path: str) -> Any:
        request = urllib.request.Request(f"{api}{path}", headers={"Authorization": f"Bearer {token}"})  # noqa: S310
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - the operator's URL.
            return json.load(response)

    return get


def _login(api: str) -> str:
    body = json.dumps({"username": VIEWER, "password": PASSWORD}).encode()
    request = urllib.request.Request(  # noqa: S310 - the operator's URL.
        f"{api}/api/v1/auth/login", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        return str(json.load(response)["access_token"])


def write(snapshot: dict[str, Any], path: Path = OUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(snapshot, handle, indent=1, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", help="the deployment to read, e.g. https://offshoot-go2y.onrender.com")
    parser.add_argument("--check", action="store_true", help="check the committed snapshot, offline")
    args = parser.parse_args()

    if args.check:
        snapshot = json.loads(OUT.read_text(encoding="utf-8"))
        issues = problems(snapshot)
        rebuilt = build_repo_part(snapshot["api"])
        if rebuilt != snapshot["repo"]:
            issues.append("the repository parts are out of date: run the script again")
        for issue in issues:
            print(f"landing snapshot: {issue}", file=sys.stderr)
        print(f"landing snapshot: {'ok' if not issues else f'{len(issues)} problems'}")
        return 1 if issues else 0

    if not args.api:
        parser.error("--api or --check is required")
    api_url = args.api.rstrip("/")
    api = build_api_part(_http_get(api_url, _login(api_url)))
    snapshot = {
        "schema": SCHEMA,
        "provenance": {
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "read_from": api_url,
            "read_as": f"{VIEWER} (the published demo viewer, read-only)",
            "script": "scripts/landing_snapshot.py",
            "note": (
                "Numbers come from stored verification runs (ids below) and docs/EVALUATION.md. "
                "Nothing here was re-run to make the page."
            ),
        },
        "api": api,
        "repo": build_repo_part(api),
    }
    issues = problems(snapshot)
    for issue in issues:
        print(f"landing snapshot: {issue}", file=sys.stderr)
    if issues:
        return 1
    write(snapshot)
    print(f"wrote {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
