"""Score three sources of `response_language` against the labels in routing_dataset.json.

Sources: the LLM router, Jev (asked `query_type` and language in one request), and the fastText
classifier from evals/language_id.py. Live API for `llm` and `jev`; fastText needs a cached model.
Issue #212 Phase 3 reads this to pick the language source for the Jev router.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from agent import jev_client
from agent.nodes.router_jev import QUESTIONS
from agent.query_policy import trim_history
from evals import language_id
from evals.run_evals import _initial_state
from evals.run_routing import DEFAULT_DATASET_PATH, select_routing_cases

DEFAULT_RESULTS_PATH = Path(__file__).resolve().parent / "results" / "routing_language.json"
SOURCES = ("llm", "jev", "fasttext")

# fastText reads short queries unreliably (see language_id.py), so the cut-offs are a first guess,
# not a calibration. Scored as-is: the point is to see how far it gets.
FASTTEXT_BM_AT = 0.75
FASTTEXT_EN_AT = 0.25

def _jev_state(case: dict[str, Any]) -> str:
    # Same layout as the LLM router's user message, so both see the same context.
    history = trim_history(case.get("history") or [])
    history_text = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)
    return f"Conversation history:\n{history_text or '(none)'}\n\nCurrent query:\n{case['query']}"


def _llm(case: dict[str, Any]) -> dict[str, Any]:
    from agent.nodes.router import router_node

    out = router_node(_initial_state(case["query"], case.get("history")))
    return {"language": out["response_language"], "query_type": out["query_type"]}


def _jev(case: dict[str, Any]) -> dict[str, Any]:
    tokens: list[tuple[int, int]] = []
    token = jev_client.usage_observer.set(lambda _model, i, o: tokens.append((i, o)))
    try:
        answers = jev_client.classify(_jev_state(case), QUESTIONS, timeout=15.0)
    finally:
        jev_client.usage_observer.reset(token)
    try:
        language, query_type = answers["response_language"]["choice"], answers["query_type"]["choice"]
    except (KeyError, TypeError) as exc:
        raise jev_client.JevError(f"Jev answers missing a choice: {exc!r}") from exc
    return {
        "language": language,
        "query_type": query_type,
        "input_tokens": sum(i for i, _ in tokens),
        "output_tokens": sum(o for _, o in tokens),
    }


def _fasttext(case: dict[str, Any]) -> dict[str, Any]:
    share = language_id.bm_share(case["query"])
    if share is None:
        # Too short for fastText to score; counted as a miss, not guessed.
        return {"language": None, "bm_share": None}
    language = "bm" if share >= FASTTEXT_BM_AT else "en" if share <= FASTTEXT_EN_AT else "mixed"
    return {"language": language, "bm_share": round(share, 3)}


_RUNNERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {"llm": _llm, "jev": _jev, "fasttext": _fasttext}


def score(case: dict[str, Any], source: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": case["id"], "source": source, "label": case["language"], "label_type": case["query_type"]}
    started = time.perf_counter()
    try:
        entry.update(_RUNNERS[source](case))
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
    entry["latency_s"] = round(time.perf_counter() - started, 3)
    entry["match"] = "error" not in entry and entry.get("language") == case["language"]
    return entry


def summarise(entries: list[dict[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for source in SOURCES:
        rows = [e for e in entries if e["source"] == source]
        if not rows:
            continue
        ok = [e for e in rows if "error" not in e]
        by_label: dict[str, dict[str, Any]] = {}
        for label in sorted({e["label"] for e in rows}):
            group = [e for e in rows if e["label"] == label]
            by_label[label] = {"n": len(group), "accuracy": sum(e["match"] for e in group) / len(group)}
        item: dict[str, Any] = {
            "n": len(rows),
            "errors": len(rows) - len(ok),
            "language_accuracy": sum(e["match"] for e in rows) / len(rows),
            "by_label": by_label,
            "median_latency_s": statistics.median(e["latency_s"] for e in ok) if ok else None,
        }
        if source == "jev":
            item["input_tokens"] = sum(e.get("input_tokens", 0) for e in ok)
            item["output_tokens"] = sum(e.get("output_tokens", 0) for e in ok)
        if source in ("llm", "jev"):
            # Comes free with the same call; Phase 7 compares it properly.
            item["query_type_accuracy"] = (
                sum(e["query_type"] == e["label_type"] for e in ok) / len(ok) if ok else 0.0
            )
        report[source] = item
    return report


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Score response_language sources on the routing dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--sources", default=",".join(SOURCES), help="Comma-separated: llm,jev,fasttext.")
    parser.add_argument("--case-ids")
    parser.add_argument("--language")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if unknown := sorted(set(sources) - set(SOURCES)):
        parser.error(f"Unknown sources: {', '.join(unknown)}")
    cases = json.loads(args.dataset.read_text(encoding="utf-8"))["cases"]
    try:
        selected = select_routing_cases(cases, case_ids=args.case_ids, language=args.language, limit=args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    if "fasttext" in sources:
        language_id.ensure_available()

    entries = []
    for case in selected:
        for source in sources:
            entry = score(case, source)
            entries.append(entry)
            got = entry.get("language") or entry.get("error", "none")
            print(f"{case['id']} {source:<8} label {case['language']:<5} got {got}", flush=True)

    report = summarise(entries)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"summary": report, "results": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    for source, item in report.items():
        extra = f"  type {item['query_type_accuracy']:.1%}" if "query_type_accuracy" in item else ""
        tokens = f"  tokens in/out {item['input_tokens']}/{item['output_tokens']}" if source == "jev" else ""
        print(f"{source:<9} lang {item['language_accuracy']:.1%}{extra}  median {item['median_latency_s']}s"
              f"  errors {item['errors']}{tokens}")
    print(f"Results written to: {args.output}")
    return 1 if any(item["errors"] for item in report.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
