"""Check evals/grounding_dataset.json and print it for human review."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROUNDING_PATH = ROOT / "grounding_dataset.json"

# Same three labels as `_GroundingClaim.support` in agent/nodes/grounding_check.py.
VERDICTS = ("supported", "partial", "unsupported")
LANGUAGES = ("en", "bm", "mixed")
SOURCE_LANGUAGES = ("en", "bm")
REVIEW_STATUSES = ("proposed", "reviewed")
# "drafted" is the only method for a supported claim. Every other method is a way of
# breaking a supported claim, so the label says what the judge should have caught.
POSITIVE_METHOD = "drafted"
NEGATIVE_METHODS = (
    "changed_number",
    "changed_period",
    "changed_actor",
    "changed_scope",
    "overstated",
    "added_detail",
    "reversal",
    "wrong_section",
)
HARD_NEGATIVE_METHODS = ("wrong_section", "overstated", "changed_number", "changed_period")

MIN_CASES = 100
# A rate such as "unsupported called supported" needs enough cases in each class.
MIN_PER_VERDICT = 20
MIN_PER_LANGUAGE = 20
MIN_PER_HARD_NEGATIVE = 5


def validate(data: dict, *, require_reviewed: bool = False) -> list[str]:
    errors: list[str] = []
    cases = data.get("cases")
    if not isinstance(cases, list):
        return ["`cases` must be a list"]

    seen_ids: set[str] = set()
    seen_claims: set[tuple[str, str, str]] = set()
    for idx, case in enumerate(cases):
        cid = case.get("id", f"#{idx}")

        def bad(msg: str) -> None:
            errors.append(f"{cid}: {msg}")

        if not case.get("id"):
            bad("missing id")
        elif cid in seen_ids:
            bad("duplicate id")
        seen_ids.add(cid)

        claim = case.get("claim")
        act, section = case.get("act_number"), case.get("section_number")
        if not isinstance(claim, str) or not claim.strip():
            bad("claim must be a non-empty string")
        else:
            key = (claim, str(act), str(section))
            if key in seen_claims:
                bad("duplicate claim for the same Act and section")
            seen_claims.add(key)
        for field in ("act_number", "act_title", "section_number"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                bad(f"{field} must be a non-empty string")

        source = case.get("source_text")
        if not isinstance(source, str) or not source.strip():
            bad("source_text must be a non-empty string")
        elif isinstance(section, str) and not re.search(rf"(?m)^\s*{re.escape(section)}\.", source):
            # A chunk carries its own section number at the start of a line. Without it
            # the cited source is not the section the case says it is.
            bad(f"source_text does not contain section {section!r}")

        if case.get("language") not in LANGUAGES:
            bad(f"language must be one of {LANGUAGES}")
        if case.get("source_language") not in SOURCE_LANGUAGES:
            bad(f"source_language must be one of {SOURCE_LANGUAGES}")
        if case.get("verdict") not in VERDICTS:
            bad(f"verdict must be one of {VERDICTS}")
        if case.get("review_status") not in REVIEW_STATUSES:
            bad(f"review_status must be one of {REVIEW_STATUSES}")
        elif require_reviewed and case["review_status"] != "reviewed":
            bad("not reviewed")

        origin = case.get("origin") or {}
        method = origin.get("method")
        if not str(origin.get("detail", "")).strip():
            bad("origin.detail must say how the claim was made")
        if case.get("verdict") == "supported":
            if method != POSITIVE_METHOD:
                bad(f"a supported claim must have origin.method {POSITIVE_METHOD!r}")
        elif method not in NEGATIVE_METHODS:
            bad(f"a {case.get('verdict')} claim needs origin.method in {NEGATIVE_METHODS}")

        if case.get("judgement_call") and not str(case.get("note", "")).strip():
            bad("judgement_call needs a note")

    if len(cases) < MIN_CASES:
        errors.append(f"need at least {MIN_CASES} cases, found {len(cases)}")
    by_verdict = Counter(c.get("verdict") for c in cases)
    for verdict in VERDICTS:
        if by_verdict[verdict] < MIN_PER_VERDICT:
            errors.append(f"verdict {verdict}: need at least {MIN_PER_VERDICT}, found {by_verdict[verdict]}")
    by_lang = Counter(c.get("language") for c in cases)
    for lang in LANGUAGES:
        if by_lang[lang] < MIN_PER_LANGUAGE:
            errors.append(f"language {lang}: need at least {MIN_PER_LANGUAGE}, found {by_lang[lang]}")
    by_method = Counter((c.get("origin") or {}).get("method") for c in cases)
    for method in HARD_NEGATIVE_METHODS:
        if by_method[method] < MIN_PER_HARD_NEGATIVE:
            errors.append(f"method {method}: need at least {MIN_PER_HARD_NEGATIVE}, found {by_method[method]}")
    return errors


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def review_table(cases: list[dict]) -> str:
    """One block per cited source, so the reviewer reads each statute text once."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for c in cases:
        groups.setdefault((c["act_number"], c["section_number"], c["source_language"]), []).append(c)

    blocks = []
    for (act, section, source_language), group in groups.items():
        first = group[0]
        lines = [
            f"### {first['act_title']}, section {section} (Act {act}, source {source_language})",
            "",
            *(f"> {line}" for line in first["source_text"].splitlines()),
            "",
            "| Status | ID | Lang | Verdict | How made | Claim | Note |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in group:
            mark = "☑" if c["review_status"] == "reviewed" else "☐"
            how = f"{c['origin']['method']}: {c['origin']['detail']}"
            note = ("JUDGEMENT CALL: " + c["note"]) if c.get("judgement_call") else ""
            lines.append(
                f"| {mark} | {c['id']} | {c['language']} | {c['verdict']} | {_md(how)} | {_md(c['claim'])} | {_md(note)} |"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the grounding label set.")
    parser.add_argument("--path", type=Path, default=GROUNDING_PATH)
    parser.add_argument("--require-reviewed", action="store_true", help="Fail on any case not yet human-reviewed.")
    parser.add_argument("--review", action="store_true", help="Print a markdown checklist for human review.")
    args = parser.parse_args()

    data = json.loads(args.path.read_text(encoding="utf-8"))
    if args.review:
        print(review_table(data["cases"]))
        return 0

    errors = validate(data, require_reviewed=args.require_reviewed)
    cases = data["cases"]
    print(f"{len(cases)} cases | verdicts {dict(Counter(c['verdict'] for c in cases))} "
          f"| languages {dict(Counter(c['language'] for c in cases))} "
          f"| reviewed {sum(c['review_status'] == 'reviewed' for c in cases)}")
    for err in errors:
        print(f"ERROR {err}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
