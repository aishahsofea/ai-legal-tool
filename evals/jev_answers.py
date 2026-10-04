"""Jev first pass on real answers (#201); `collect` is the paid agent run, `analyse` replays judges.

    python3 -m evals.jev_answers collect --limit 8 --out answers.json
    JEV_MODEL=jev-1.13.0 python3 -m evals.jev_answers analyse answers.json [--locate] --out rows.json

`--ultra-rows rows.json` reuses the Ultra reference from an earlier `analyse`, so only Jev runs.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

THRESHOLDS = (0.9, 0.95, 0.97, 0.99)
DATASET_PATH = Path(__file__).resolve().parent / "dataset.json"
_ULTRA_FIELDS = ("ultra_seconds", "ultra_usage", "ultra_claims", "evidence_quotes", "first_quote_locate")


def collect(limit: int | None, out: Path) -> None:
    from evals.run_evals import _run_raw_agent

    cases = [
        c for c in json.loads(DATASET_PATH.read_text())["cases"]
        if c.get("citation_applicable") and c.get("expected_policy", "allow") == "allow"
    ][:limit]
    answers = []
    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case['id']}", flush=True)
        state = _run_raw_agent(case["query"])
        if not state.get("draft_response") or not state.get("citations"):
            print("    no cited draft, skipped", flush=True)
            continue
        answers.append({
            "id": case["id"], "language": case.get("language"), "query": case["query"],
            "draft_response": state["draft_response"], "citations": state["citations"],
            "retrieved_chunks": state["retrieved_chunks"], "violations": state.get("violations", []),
        })
        # Per answer: each is a paid run a late crash must not lose.
        out.write_text(json.dumps(answers, ensure_ascii=False, indent=1, default=float))
    print(f"{len(answers)} answers -> {out}")


def _locate_first_quote(client: Any, citations: list[dict]) -> str | None:
    """Match status of the first evidence quote on the first receipt that has one."""
    for citation in citations:
        receipt = citation.get("receipt")
        if not isinstance(receipt, dict) or not receipt.get("evidence"):
            continue
        response = client.post(
            f"/receipts/{receipt['document_id']}/locate",
            json={
                "evidence_quote": receipt["evidence"][0]["quote"],
                "start_page": citation.get("page_number") or 1,
                "extraction_id": receipt.get("extraction_id"),
            },
        )
        return response.json().get("status") if response.status_code == 200 else f"http_{response.status_code}"
    return None


def _ultra_reference(answer: dict, state: dict, sources: list[dict], locate_client: Any) -> dict:
    from agent.nodes import grounding_check as gc
    from evals.usage import eval_usage

    with eval_usage() as usage:
        started = time.perf_counter()
        try:
            result = gc._grounding_llm.invoke(gc._messages(answer["draft_response"], sources))
        except Exception as exc:  # the node fails open on this, so the reference is just missing
            return {"error": f"ultra failed: {exc!r}"[:300]}
        row: dict[str, Any] = {"ultra_seconds": time.perf_counter() - started}
    row["ultra_usage"] = usage.summarize()["total"]["usd"]
    row["ultra_claims"] = [
        {"claim": c.claim, "support": c.support, "act": c.cited_act_number, "section": c.cited_section_number}
        for c in result.claims
    ]
    finalised = gc._finalise(result, state, [])
    row["evidence_quotes"] = sum(len(c["receipt"]["evidence"]) for c in finalised["citations"] if c.get("receipt"))
    if locate_client is not None:
        row["first_quote_locate"] = _locate_first_quote(locate_client, finalised["citations"])
    return row


def analyse_answer(
    answer: dict, *, ultra_row: dict | None = None, locate_client: Any = None, jev_runs: int = 2
) -> dict:
    from agent.jev_client import JevError, supported_probability
    from agent.nodes import grounding_check as gc
    from evals.usage import eval_usage

    state = {k: answer[k] for k in ("citations", "retrieved_chunks")} | {
        "draft_response": answer["draft_response"], "evidence_violations": [],
    }
    sources = gc._collect_cited_sources(state)
    row: dict[str, Any] = {"id": answer["id"], "language": answer["language"], "sources": len(sources)}
    if not sources:
        return row | {"error": "no cited sources"}
    if ultra_row and "ultra_claims" in ultra_row:
        row |= {k: ultra_row[k] for k in _ULTRA_FIELDS if k in ultra_row}
    else:
        row |= _ultra_reference(answer, state, sources, locate_client)
        if "error" in row:
            return row

    # More than one run: Jev's score moves between identical calls, and one run hides that.
    scores, seconds, usd = [], [], []
    for _ in range(jev_runs):
        with eval_usage() as usage:
            started = time.perf_counter()
            try:
                scores.append(supported_probability(answer["draft_response"], sources))
            except JevError as exc:
                row["jev_error"] = str(exc)[:200]
                scores.append(None)
            seconds.append(time.perf_counter() - started)
        usd.append(float(usage.summarize()["total"]["usd"]))
    row |= {"jev_scores": scores, "jev_seconds": statistics.mean(seconds), "jev_usd": statistics.mean(usd)}
    return row


def _ultra_verdict(row: dict) -> str:
    supports = {c["support"] for c in row["ultra_claims"]}
    return "unsupported" if "unsupported" in supports else "partial" if "partial" in supports else "supported"


def _skips(score: float | None, threshold: float) -> bool:
    return score is not None and score >= threshold


def report(rows: list[dict]) -> str:
    ok = [r for r in rows if "ultra_claims" in r and "jev_scores" in r]
    if not ok:
        return f"answers: {len(rows)}  none with both an Ultra reference and Jev scores"
    verdicts = {r["id"]: _ultra_verdict(r) for r in ok}
    flagged = sum(v != "supported" for v in verdicts.values())
    runs = len(ok[0]["jev_scores"])
    spreads = [max(s) - min(s) for r in ok if None not in (s := r["jev_scores"])]
    lines = [
        f"answers: {len(rows)}  with Ultra reference: {len(ok)}  Ultra flagged partial/unsupported: {flagged}"
        f" (unsupported: {sum(v == 'unsupported' for v in verdicts.values())})",
        f"Ultra median seconds per answer: {statistics.median(r['ultra_seconds'] for r in ok):.1f}  "
        f"mean USD: {sum(float(r['ultra_usage']) for r in ok) / len(ok):.5f}",
        f"Jev runs per answer: {runs}  mean seconds: {statistics.mean(r['jev_seconds'] for r in ok):.1f}  "
        f"mean USD: {sum(r['jev_usd'] for r in ok) / len(ok):.6f}  "
        f"max spread between runs: {max(spreads, default=0):.2f}  "
        f"answers with a Jev error: {sum('jev_error' in r for r in ok)}",
        "",
        "Skip counts are per run. A flagged answer counts if any run skipped it.",
        "| threshold | skip Ultra (per run) | skipped but Ultra flagged any | skipped but Ultra flagged unsupported "
        "| mean USD/answer | mean s/answer (skipped=Jev only) |",
        "|---|---|---|---|---|---|",
    ]
    for t in THRESHOLDS:
        per_run = [sum(_skips(r["jev_scores"][i], t) for r in ok) for i in range(runs)]
        ever = [r for r in ok if any(_skips(s, t) for s in r["jev_scores"])]
        first = [_skips(r["jev_scores"][0], t) for r in ok]
        usd = sum(r["jev_usd"] + (0 if skip else float(r["ultra_usage"])) for r, skip in zip(ok, first)) / len(ok)
        sec = sum(r["jev_seconds"] + (0 if skip else r["ultra_seconds"]) for r, skip in zip(ok, first)) / len(ok)
        lines.append(
            f"| {t} | {' / '.join(f'{n}/{len(ok)}' for n in per_run)} "
            f"| {sum(verdicts[r['id']] != 'supported' for r in ever)} "
            f"| {sum(verdicts[r['id']] == 'unsupported' for r in ever)} | {usd:.5f} | {sec:.1f} |"
        )
    if any("first_quote_locate" in r for r in ok):
        matched = [r for r in ok if r.get("first_quote_locate") == "matched"]
        lines += ["", f"/locate, Ultra alone: first quote matched on {len(matched)}/{len(ok)} answers",
                  "| threshold | matched, answers sent to Ultra (run 1) | overall matched |", "|---|---|---|"]
        for t in THRESHOLDS:
            sent = [r for r in ok if not _skips(r["jev_scores"][0], t)]
            hits = sum(r.get("first_quote_locate") == "matched" for r in sent)
            lines.append(f"| {t} | {hits}/{len(sent)} | {hits}/{len(ok)} |")

    def fmt(score: float | None) -> str:
        return "error" if score is None else f"{score:.3f}"

    lines += ["", "| id | Ultra verdict | Ultra claims | Jev scores |", "|---|---|---|---|"]
    for r in sorted(ok, key=lambda r: -max((s for s in r["jev_scores"] if s is not None), default=0)):
        scores = " / ".join(fmt(s) for s in r["jev_scores"])
        lines.append(f"| {r['id']} | {verdicts[r['id']]} | {len(r['ultra_claims'])} | {scores} |")
    return "\n".join(lines)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--limit", type=int)
    c.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("analyse")
    a.add_argument("answers", type=Path)
    a.add_argument("--ultra-rows", type=Path, help="reuse the Ultra reference from an earlier `analyse` --out")
    a.add_argument("--locate", action="store_true", help="replay evidence through POST /receipts/{id}/locate")
    a.add_argument("--jev-runs", type=int, default=2)
    a.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.cmd == "collect":
        collect(args.limit, args.out)
        return
    client = None
    if args.locate:
        from fastapi.testclient import TestClient

        from api.main import app

        client = TestClient(app)
    from agent.nodes.grounding_check import _MODEL

    ultra_rows = {r["id"]: r for r in json.loads(args.ultra_rows.read_text())} if args.ultra_rows else {}
    print(f"Ultra reference model: {_MODEL if not ultra_rows else 'reused from ' + str(args.ultra_rows)}"
          f"  Jev model: {os.getenv('JEV_MODEL')}")
    rows = [
        analyse_answer(a, ultra_row=ultra_rows.get(a["id"]), locate_client=client, jev_runs=args.jev_runs)
        for a in json.loads(args.answers.read_text())
    ]
    if args.out:
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
    print(report(rows))


if __name__ == "__main__":
    main()
