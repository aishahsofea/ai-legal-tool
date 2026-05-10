"""Human review helper for eval dataset."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "dataset.json"
CHUNKS_DIR = Path("data/chunks/en")


def _load_dataset(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _load_section(act_number: str, section_number: str) -> dict | None:
    path = CHUNKS_DIR / f"{act_number}.json"
    if not path.exists():
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        if row["section_number"] == section_number:
            return row
    return None


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
        cases = [c for c in cases if c.get("expected_act_number") == args.act]
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
            expected = "block" if case.get("expected_policy") == "block" else f"Act {case.get('expected_act_number')} / s.{case.get('expected_section')}"
            notes = ""
            if case.get("citation_applicable"):
                section = _load_section(case["expected_act_number"], case["expected_section"])
                notes = _snippet(section.get("content", "")) if section else "MISSING SECTION"
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
            lines.append(f"[{case['id']}] {case['category']} | expected={case['expected_act_number']} s.{case['expected_section']} | policy={case['expected_policy']}")
            lines.append(f"Q: {case['query']}")
            if case.get("citation_applicable"):
                section = _load_section(case["expected_act_number"], case["expected_section"])
                if section:
                    lines.append(f"A: {section.get('act_title', '')} / Section {section['section_number']}")
                    lines.append(f"   {_snippet(section.get('content', ''))}")
                else:
                    lines.append("A: MISSING SECTION")
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
