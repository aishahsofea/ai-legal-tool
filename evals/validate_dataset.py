"""Human review helper for eval dataset."""
from __future__ import annotations

import argparse
import json
from functools import lru_cache
from pathlib import Path

from evals.coverage import case_section_pairs

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "dataset.json"
CHUNKS_DIR = Path("data/chunks/en")


def _load_dataset(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


@lru_cache(maxsize=None)
def _act_rows(act_number: str) -> tuple[dict, ...]:
    path = CHUNKS_DIR / f"{act_number}.json"
    if not path.exists():
        return ()
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def _load_section(act_number: str, section_number: str) -> dict | None:
    for row in _act_rows(act_number):
        if row["section_number"] == section_number:
            return row
    return None


def _expected_label(case: dict) -> str:
    if case.get("expected_policy") == "block":
        return "block"
    pairs = case_section_pairs(case)
    if not pairs:
        return "no citation expected"
    return ", ".join(f"Act {act} / s.{section}" for act, section in pairs)


def _section_notes(case: dict, n: int = 260) -> str:
    """One snippet per expected section, so a multi-part case shows every
    provision a reviewer has to check rather than only the first."""
    pairs = case_section_pairs(case)
    if not pairs:
        return "MISSING SECTION"
    parts = []
    for act, section_number in pairs:
        section = _load_section(act, section_number)
        if section is None:
            parts.append(f"s.{section_number}: MISSING SECTION")
        else:
            parts.append(f"s.{section_number}: {_snippet(section.get('content', ''), n)}")
    return " || ".join(parts)


def _snippet(text: str, n: int = 260) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _markdown_row(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the eval dataset for human review.")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--act", type=str, default=None, help="Filter to one Act number.")
    parser.add_argument("--category", choices=("citation", "policy"), default=None)
    parser.add_argument("--format", choices=("plain", "markdown"), default="plain")
    parser.add_argument("--output", type=Path, default=None, help="Optional file to write the checklist to.")
    args = parser.parse_args()

    cases = _load_dataset(args.dataset)
    if args.act:
        cases = [c for c in cases if any(act == args.act for act, _ in case_section_pairs(c))]
    if args.category:
        cases = [c for c in cases if c.get("category") == args.category]

    lines: list[str] = []
    if args.format == "markdown":
        lines.append(f"# Eval review checklist")
        lines.append(f"Dataset: `{args.dataset}`")
        lines.append(f"Cases: {len(cases)}")
        lines.append("")
        lines.append("| Status | ID | Type | Query | Expected | Notes |")
        lines.append("|---|---|---|---|---|---|")
        for case in cases:
            expected = _expected_label(case)
            if case.get("citation_applicable"):
                notes = _section_notes(case)
            else:
                notes = "Escalation / no citation expected"
            lines.append(
                f"| ☐ | {case['id']} | {case['category']} | {_markdown_row(case['query'])} | {_markdown_row(expected)} | {_markdown_row(notes)} |"
            )
    else:
        lines.append(f"Dataset: {args.dataset}")
        lines.append(f"Cases: {len(cases)}")
        lines.append("")
        for case in cases:
            lines.append(f"[{case['id']}] {case['category']} | expected={_expected_label(case)} | policy={case['expected_policy']}")
            if case.get("min_sections_found") is not None:
                lines.append(f"   min sections to find: {case['min_sections_found']}")
            lines.append(f"Q: {case['query']}")
            if case.get("citation_applicable"):
                pairs = case_section_pairs(case)
                if not pairs:
                    lines.append("A: MISSING SECTION")
                for act, section_number in pairs:
                    section = _load_section(act, section_number)
                    if section:
                        lines.append(f"A: {section.get('act_title', '')} / Section {section['section_number']}")
                        lines.append(f"   {_snippet(section.get('content', ''))}")
                    else:
                        lines.append(f"A: Act {act} Section {section_number} — MISSING SECTION")
            else:
                lines.append("A: escalation / no citation expected")
            lines.append("-" * 80)

    output = "\n".join(lines)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
