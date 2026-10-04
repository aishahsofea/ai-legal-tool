"""Check evals/routing_dataset.json and print it for human review."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROUTING_PATH = ROOT / "routing_dataset.json"
DATASET_PATH = ROOT / "dataset.json"

# "escalate" is absent on purpose: router.py decides it by regex before any model call.
QUERY_TYPES = ("statute_lookup", "topical", "provision_extraction", "conversational", "clarify")
LANGUAGES = ("en", "bm", "mixed")
SOURCES = ("eval_dataset", "hand")
TAGS = ("tie_break", "clarify_boundary", "history")
REVIEW_STATUSES = ("proposed", "reviewed")

MIN_CASES = 60
# Each class needs enough cases for an accuracy figure to mean something.
MIN_PER_QUERY_TYPE = 10
MIN_PER_LANGUAGE = 10


def validate(data: dict, dataset_ids: set[str], *, require_reviewed: bool = False) -> list[str]:
    errors: list[str] = []
    cases = data.get("cases")
    if not isinstance(cases, list):
        return ["`cases` must be a list"]

    seen_ids: set[str] = set()
    seen_queries: set[tuple[str, str]] = set()
    for idx, case in enumerate(cases):
        cid = case.get("id", f"#{idx}")

        def bad(msg: str) -> None:
            errors.append(f"{cid}: {msg}")

        if not case.get("id"):
            bad("missing id")
        elif cid in seen_ids:
            bad("duplicate id")
        seen_ids.add(cid)

        query = case.get("query")
        if not isinstance(query, str) or not query.strip():
            bad("query must be a non-empty string")
        else:
            history_key = json.dumps(case.get("history", []), sort_keys=True)
            # Same text with different history is a legitimate pair (history flips the label).
            if (query, history_key) in seen_queries:
                bad("duplicate query with the same history")
            seen_queries.add((query, history_key))

        if case.get("query_type") not in QUERY_TYPES:
            bad(f"query_type must be one of {QUERY_TYPES}")
        if case.get("language") not in LANGUAGES:
            bad(f"language must be one of {LANGUAGES}")
        if case.get("review_status") not in REVIEW_STATUSES:
            bad(f"review_status must be one of {REVIEW_STATUSES}")
        elif require_reviewed and case["review_status"] != "reviewed":
            bad("not reviewed")

        source = case.get("source")
        if source not in SOURCES:
            bad(f"source must be one of {SOURCES}")
        elif source == "eval_dataset" and case.get("source_id") not in dataset_ids:
            bad(f"source_id {case.get('source_id')!r} not in dataset.json")

        for tag in case.get("tags", []):
            if tag not in TAGS:
                bad(f"unknown tag {tag!r}")
        if "history" in case.get("tags", []) and not case.get("history"):
            bad("tagged `history` but has no history")

        for turn in case.get("history", []):
            if turn.get("role") not in ("user", "assistant") or not str(turn.get("content", "")).strip():
                bad("history turns need role user|assistant and non-empty content")

    if len(cases) < MIN_CASES:
        errors.append(f"need at least {MIN_CASES} cases, found {len(cases)}")
    by_type = Counter(c.get("query_type") for c in cases)
    for qt in QUERY_TYPES:
        if by_type[qt] < MIN_PER_QUERY_TYPE:
            errors.append(f"query_type {qt}: need at least {MIN_PER_QUERY_TYPE}, found {by_type[qt]}")
    by_lang = Counter(c.get("language") for c in cases)
    for lang in LANGUAGES:
        if by_lang[lang] < MIN_PER_LANGUAGE:
            errors.append(f"language {lang}: need at least {MIN_PER_LANGUAGE}, found {by_lang[lang]}")
    return errors


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def review_table(cases: list[dict]) -> str:
    lines = [
        "| Status | ID | Lang | Label | Query | History / note |",
        "|---|---|---|---|---|---|",
    ]
    for c in cases:
        extra = []
        if c.get("history"):
            extra.append("history: " + " / ".join(f"{t['role']}: {t['content']}" for t in c["history"]))
        if c.get("note"):
            extra.append(c["note"])
        mark = "☑" if c["review_status"] == "reviewed" else "☐"
        lines.append(
            f"| {mark} | {c['id']} | {c['language']} | {c['query_type']} | {_md(c['query'])} | {_md(' — '.join(extra))} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the routing label set.")
    parser.add_argument("--path", type=Path, default=ROUTING_PATH)
    parser.add_argument("--require-reviewed", action="store_true", help="Fail on any case not yet human-reviewed.")
    parser.add_argument("--review", action="store_true", help="Print a markdown checklist for human review.")
    args = parser.parse_args()

    data = json.loads(args.path.read_text(encoding="utf-8"))
    dataset_ids = {c["id"] for c in json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]}
    if args.review:
        print(review_table(data["cases"]))
        return 0

    errors = validate(data, dataset_ids, require_reviewed=args.require_reviewed)
    cases = data["cases"]
    print(f"{len(cases)} cases | types {dict(Counter(c['query_type'] for c in cases))} "
          f"| languages {dict(Counter(c['language'] for c in cases))} "
          f"| reviewed {sum(c['review_status'] == 'reviewed' for c in cases)}")
    for err in errors:
        print(f"ERROR {err}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
