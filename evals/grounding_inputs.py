"""Turn a grounding-dataset case into the judge's inputs. Shared by the Jev first pass and the grounding runner."""
from __future__ import annotations


def draft(case: dict) -> str:
    return f"Here is the position.\n\n{case['claim']}\n\nThis is not legal advice."


def source(case: dict) -> dict:
    return {
        "act_number": case["act_number"], "act_title": case["act_title"],
        "section_number": case["section_number"], "content": case["source_text"],
    }
