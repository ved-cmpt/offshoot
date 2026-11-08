#!/usr/bin/env python3
"""Measure rule extraction against the answer key. Run this on the host, never in a container.

    python scripts/evaluate_rules.py --api http://localhost:8100

It reads docs/BILLRITE_RULES.md, which is not mounted into the orchestrator, and it reads
the stored rules through the public API as the demo viewer. Nothing flows back: the product
never receives the answer key or this script's results. Reports hold rule IDs, not rule text.

Standard library only, so that it needs no project environment. docs/EVALUATION.md explains
the method.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_KEY = Path(__file__).resolve().parent.parent / "docs" / "BILLRITE_RULES.md"
DEFAULT_ENV = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_SOURCES = Path(__file__).resolve().parent.parent / "legacy" / "billrite"
VIEWER_EMAIL = "viewer@demo.parityforge.dev"
DEFAULT_THRESHOLD = 0.3
SENSITIVITY = (0.2, 0.3, 0.4, 0.5)
SHINGLE_WORDS = 8
PROGRAM_BY_PREFIX = {"MV": "MTRVAL", "RC": "RATECALC", "LF": "LATEFEE", "SG": "STMTGEN", "BR": "BILLRUN"}
HARD_FLAGS = {"SPAN_INVALID", "NAMES_NOT_FOUND"}

_ROW = re.compile(r"^\|\s*([A-Z]{2}-\d{2})\s*\|(.+)\|(.+)\|\s*$")
_SOURCE = re.compile(r"`([A-Za-z0-9_]+\.(?:cbl|cpy)):([0-9,\- ]+)`")
_TOKEN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*|\d+(?:\.\d+)?")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    """
    the and for with that this are was were from into than then them they its not but any all only each
    when one two per has have had been will would can may must also both same other more most such
    otherwise out over under above below between still there here which what who how does did
    """.split()
)


@dataclass(frozen=True)
class KeyRule:
    id: str
    program: str
    text: str
    spans: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class Extracted:
    id: str
    program: str
    title: str
    text: str
    spans: tuple[tuple[str, int, int], ...]
    flags: tuple[str, ...]
    state: str
    spans_cited: int = 0


@dataclass
class Evaluation:
    threshold: float
    rules_total: int = 0
    key_total: int = 0
    matched_rules: int = 0
    matched_keys: int = 0
    one_to_one: int = 0
    span_valid_rules: int = 0
    spans_total: int = 0
    spans_valid: int = 0
    flagged: int = 0
    hard_flagged: int = 0
    hard_flagged_unmatched: int = 0
    unflagged_unmatched: list[str] = field(default_factory=list)
    flagged_but_matched: list[str] = field(default_factory=list)
    missed_keys: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)
    hallucinated_titles: list[str] = field(default_factory=list)
    by_program: dict[str, dict[str, int]] = field(default_factory=dict)
    precision_after_flags: float = 0.0

    @staticmethod
    def _ratio(part: int, whole: int) -> float:
        return round(part / whole, 4) if whole else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "rules_total": self.rules_total,
            "key_total": self.key_total,
            "precision": self._ratio(self.matched_rules, self.rules_total),
            "recall": self._ratio(self.matched_keys, self.key_total),
            "precision_one_to_one": self._ratio(self.one_to_one, self.rules_total),
            "recall_one_to_one": self._ratio(self.one_to_one, self.key_total),
            "precision_after_flags": self.precision_after_flags,
            "span_validity_rules": self._ratio(self.span_valid_rules, self.rules_total),
            "span_validity_spans": self._ratio(self.spans_valid, self.spans_total),
            "flagged": self.flagged,
            "hard_flagged": self.hard_flagged,
            "hallucinated_caught": self.hard_flagged_unmatched,
            "hallucinated_titles": self.hallucinated_titles,
            "unflagged_unmatched": self.unflagged_unmatched,
            "flagged_but_matched": self.flagged_but_matched,
            "missed_keys": self.missed_keys,
            "one_to_one_pairs": [{"key": key, "rule": rule} for key, rule in self.pairs],
            "by_program": self.by_program,
        }


def _parse_refs(refs: str) -> list[tuple[int, int]]:
    spans = []
    for part in refs.split(","):
        part = part.strip()
        if not part:
            continue
        start, _, end = part.partition("-")
        spans.append((int(start), int(end or start)))
    return spans


def parse_key(text: str) -> list[KeyRule]:
    rules = []
    for line in text.splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        rule_id, statement, source = match.groups()
        spans = tuple(
            (file, start, end) for file, refs in _SOURCE.findall(source) for start, end in _parse_refs(refs)
        )
        rules.append(KeyRule(rule_id, PROGRAM_BY_PREFIX[rule_id[:2]], statement.strip(), spans))
    return rules


def signature(text: str) -> set[str]:
    tokens = set()
    for token in _TOKEN.findall(text.lower().replace("`", " ")):
        if token in _STOP or (len(token) < 3 and not token[0].isdigit()):
            continue
        tokens.add(token[:-1] if token.endswith("s") and len(token) > 3 else token)
    return tokens


def overlap(first: set[str], second: set[str]) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / min(len(first), len(second))


def spans_overlap(first: tuple[tuple[str, int, int], ...], second: tuple[tuple[str, int, int], ...]) -> bool:
    return any(
        a_file == b_file and a_start <= b_end and b_start <= a_end
        for a_file, a_start, a_end in first
        for b_file, b_start, b_end in second
    )


def is_match(rule: Extracted, key: KeyRule, threshold: float) -> bool:
    return (
        rule.program == key.program
        and spans_overlap(rule.spans, key.spans)
        and overlap(signature(rule.text), signature(key.text)) >= threshold
    )


def maximum_matching(edges: dict[str, list[str]]) -> dict[str, str]:
    """Kuhn's algorithm: the largest set of pairs using each rule and key row at most once.

    Returns key row -> rule.
    """
    owner: dict[str, str] = {}

    def assign(rule: str, seen: set[str]) -> bool:
        for key in edges[rule]:
            if key in seen:
                continue
            seen.add(key)
            if key not in owner or assign(owner[key], seen):
                owner[key] = rule
                return True
        return False

    for rule in edges:
        assign(rule, set())
    return owner


def evaluate(rules: list[Extracted], key: list[KeyRule], threshold: float = DEFAULT_THRESHOLD) -> Evaluation:
    result = Evaluation(threshold=threshold, rules_total=len(rules), key_total=len(key))
    edges = {rule.id: [row.id for row in key if is_match(rule, row, threshold)] for rule in rules}
    matched_keys = {row for targets in edges.values() for row in targets}
    result.matched_rules = sum(1 for targets in edges.values() if targets)
    result.matched_keys = len(matched_keys)
    pairs = maximum_matching(edges)
    titles = {rule.id: rule.title for rule in rules}
    result.one_to_one = len(pairs)
    result.pairs = sorted((row, titles[rule]) for row, rule in pairs.items())
    result.missed_keys = sorted(row.id for row in key if row.id not in matched_keys)
    survivors = 0
    survivors_matched = 0
    for rule in rules:
        hard = bool(set(rule.flags) & HARD_FLAGS)
        matched = bool(edges[rule.id])
        result.flagged += bool(rule.flags)
        result.hard_flagged += hard
        result.span_valid_rules += "SPAN_INVALID" not in rule.flags
        result.spans_total += rule.spans_cited
        result.spans_valid += len(rule.spans)
        if hard and not matched:
            result.hard_flagged_unmatched += 1
            result.hallucinated_titles.append(rule.title)
        if not rule.flags and not matched:
            result.unflagged_unmatched.append(rule.title)
        if rule.flags and matched:
            result.flagged_but_matched.append(rule.title)
        if not hard:
            survivors += 1
            survivors_matched += matched
    result.precision_after_flags = Evaluation._ratio(survivors_matched, survivors)
    for program in sorted({row.program for row in key}):
        program_rules = [rule for rule in rules if rule.program == program]
        program_keys = [row for row in key if row.program == program]
        result.by_program[program] = {
            "rules": len(program_rules),
            "rules_matched": sum(1 for rule in program_rules if edges[rule.id]),
            "key_rows": len(program_keys),
            "key_rows_matched": sum(1 for row in program_keys if row.id in matched_keys),
        }
    return result


def shingles(text: str, size: int = SHINGLE_WORDS) -> set[str]:
    """Hashes of every run of `size` words. Used to prove key text is absent, without holding it."""
    words = _WORD.findall(text.lower())
    return {
        hashlib.sha256(" ".join(words[index : index + size]).encode()).hexdigest()[:24]
        for index in range(len(words) - size + 1)
    }


def key_fingerprints(key_text: str, source_texts: tuple[str, ...] = ()) -> list[str]:
    """Every run of words in the key, without line references or anything quoted from the COBOL.

    The key quotes a few source comments, such as ticket 96-233. Those runs are legitimately in
    every prompt for that program, so they say nothing about a leak and are left out.
    """
    prose = shingles(re.sub(r"`[^`]*`", " ", key_text))
    for text in source_texts:
        prose -= shingles(text)
    return sorted(prose)


def read_source_texts(root: Path) -> tuple[str, ...]:
    paths = sorted((*root.glob("src/*.cbl"), *root.glob("copy/*.cpy")))
    return tuple(path.read_text(encoding="ascii") for path in paths)


def load_env_value(name: str, env_path: Path = DEFAULT_ENV) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return None


def _request(url: str, data: dict[str, Any] | None = None, token: str | None = None) -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers=headers)  # noqa: S310 - a local URL given by the operator.
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.load(response)


def fetch_rules(api: str, password: str) -> list[dict[str, Any]]:
    session = _request(f"{api}/api/v1/auth/login", {"email": VIEWER_EMAIL, "password": password})
    token = session["access_token"]
    projects = _request(f"{api}/api/v1/projects", token=token)["items"]
    project = next(item for item in projects if item["name"] == "BillRite")
    rules: list[dict[str, Any]] = []
    while True:
        page = _request(f"{api}/api/v1/projects/{project['id']}/rules?limit=50&offset={len(rules)}", token=token)
        rules.extend(page["items"])
        if len(rules) >= page["total"] or not page["items"]:
            return rules


def to_extracted(raw: dict[str, Any]) -> Extracted:
    # Rejected rules still count: precision measures what the agent proposed, not what survived.
    return Extracted(
        id=raw["id"],
        program=raw["program"],
        title=raw["title"],
        text=f"{raw['title']}. {raw['statement']}",
        spans=tuple((span["file"], span["start_line"], span["end_line"]) for span in raw["spans"] if span["valid"]),
        flags=tuple(raw["flags"]),
        state=raw["state"],
        spans_cited=len(raw["spans"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8100")
    parser.add_argument("--rules-json", type=Path, help="Read rules from this file instead of the API.")
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--write-fingerprints", type=Path, help="Write hashed key fingerprints and stop.")
    parser.add_argument("--check-fingerprints", type=Path, help="Fail if the stored fingerprints are out of date.")
    args = parser.parse_args()

    if not args.key.exists():
        print(f"The answer key is not reachable from here: {args.key}", file=sys.stderr)
        return 2
    key_text = args.key.read_text(encoding="utf-8")

    if args.write_fingerprints:
        current = key_fingerprints(key_text, read_source_texts(DEFAULT_SOURCES))
        args.write_fingerprints.write_text(json.dumps(current, indent=0) + "\n", newline="\n")
        print(f"Wrote {len(current)} fingerprints")
        return 0
    if args.check_fingerprints:
        current = key_fingerprints(key_text, read_source_texts(DEFAULT_SOURCES))
        if json.loads(args.check_fingerprints.read_text()) != current:
            print("The stored fingerprints do not match the answer key. Rewrite them.", file=sys.stderr)
            return 1
        print(f"Fingerprints current: {len(current)}")
        return 0

    if args.rules_json:
        raw_rules = json.loads(args.rules_json.read_text())
    else:
        password = load_env_value("DEMO_PASSWORD_VIEWER")
        if not password:
            print("DEMO_PASSWORD_VIEWER is not set", file=sys.stderr)
            return 2
        raw_rules = fetch_rules(args.api, password)
    rules = [to_extracted(raw) for raw in raw_rules]
    key = parse_key(key_text)
    report = evaluate(rules, key, args.threshold).as_dict()
    report["sensitivity"] = {
        str(threshold): {
            "precision": evaluate(rules, key, threshold).as_dict()["precision"],
            "recall": evaluate(rules, key, threshold).as_dict()["recall"],
        }
        for threshold in SENSITIVITY
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
