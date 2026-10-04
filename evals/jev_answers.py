"""Jev first pass measured on real answers instead of labelled claims (#201 Phase 3).

Two steps, so the paid agent run and the judge runs can be repeated apart:

    python3 -m evals.jev_answers collect --limit 8 --out answers.json
    JEV_MODEL=jev-1.13.0 python3 -m evals.jev_answers analyse answers.json [--locate] --out rows.json

`collect` runs router, retriever and synthesiser (the state grounding_check sees)
and keeps the draft, citations and retrieved chunks. `analyse` runs Ultra on each
answer as the reference, then replays the first pass: split, pair each claim to
its source, score with Jev. A claim that cannot be paired, or a Jev error, sends
the whole answer to Ultra, as the node would.
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

THRESHOLDS = (0.5, 0.7, 0.9, 0.95, 0.99)
DATASET_PATH = Path(__file__).resolve().parent / "dataset.json"


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
        # Per answer, because each one is a paid agent run that a late crash must not lose.
        out.write_text(json.dumps(answers, ensure_ascii=False, indent=1, default=float))
    print(f"{len(answers)} answers -> {out}")


def _source_text(source: dict) -> str:
    return (
        f"({source['act_title']}, Act {source['act_number']}, Section {source['section_number']}):\n"
        f"{source['content']}"
    )


def _covered(ultra_claim: str, sentences: list[str]) -> bool:
    from citation_receipts.locator import contains_normalized_sequence

    return any(
        contains_normalized_sequence(ultra_claim, s) or contains_normalized_sequence(s, ultra_claim)
        for s in sentences
    )


def _locate_first_quote(client: Any, citations: list[dict]) -> str | None:
    """matched / not_found / ... for the first evidence quote on the first receipt that has one."""
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


def analyse_answer(answer: dict, *, locate_client: Any = None) -> dict:
    from agent.jev_client import JevError, supported_probability
    from agent.nodes import grounding_check as gc
    from agent.nodes.claim_splitter import pair_source, split_claims
    from evals.usage import eval_usage

    state = {k: answer[k] for k in ("citations", "retrieved_chunks")} | {
        "draft_response": answer["draft_response"], "evidence_violations": [],
    }
    sources = gc._collect_cited_sources(state)
    row: dict[str, Any] = {"id": answer["id"], "language": answer["language"], "sources": len(sources)}
    if not sources:
        return row | {"error": "no cited sources"}

    with eval_usage() as ultra_usage:
        started = time.perf_counter()
        try:
            result = gc._grounding_llm.invoke(gc._messages(answer["draft_response"], sources))
        except Exception as exc:  # the node fails open on this, so the reference is just missing
            return row | {"error": f"ultra failed: {exc!r}"[:300]}
        row["ultra_seconds"] = time.perf_counter() - started
    row["ultra_usage"] = ultra_usage.summarize()["total"]["usd"]
    row["ultra_claims"] = [
        {"claim": c.claim, "support": c.support, "act": c.cited_act_number, "section": c.cited_section_number}
        for c in result.claims
    ]

    finalised = gc._finalise(result, state, [])
    row["evidence_quotes"] = sum(len(c["receipt"]["evidence"]) for c in finalised["citations"] if c.get("receipt"))
    if locate_client is not None:
        row["first_quote_locate"] = _locate_first_quote(locate_client, finalised["citations"])

    sentences = split_claims(answer["draft_response"])
    row["splitter_claims"] = len(sentences)
    row["splitter_recall"] = [_covered(c.claim, sentences) for c in result.claims]
    pairs = [pair_source(s, sources) for s in sentences]
    row["unpaired"] = sum(p is None for p in pairs)

    with eval_usage() as jev_usage:
        scores: list[float | None] = []
        started = time.perf_counter()
        for sentence, source in zip(sentences, pairs):
            if source is None:
                scores.append(None)
                continue
            try:
                scores.append(supported_probability(sentence, _source_text(source)))
            except JevError as exc:
                row["jev_error"] = str(exc)[:200]
                scores.append(None)
        row["jev_seconds"] = time.perf_counter() - started
    row["jev_usd"] = jev_usage.summarize()["total"]["usd"]
    row["jev_scores"] = scores
    return row


def _skips(row: dict, threshold: float) -> bool:
    scores = row.get("jev_scores")
    # No sentence to check means the splitter found nothing, which must not clear an
    # answer Ultra found claims in.
    return bool(scores) and all(s is not None and s >= threshold for s in scores)


def report(rows: list[dict]) -> str:
    ok = [r for r in rows if "ultra_claims" in r]
    flagged = [r for r in ok if any(c["support"] != "supported" for c in r["ultra_claims"])]
    unsupported = [r for r in ok if any(c["support"] == "unsupported" for c in r["ultra_claims"])]
    recall_flags = [f for r in ok for f in r["splitter_recall"]]
    total_claims = sum(r["splitter_claims"] for r in ok)
    unpaired = sum(r["unpaired"] for r in ok)
    lines = [
        f"answers: {len(rows)}  with Ultra reference: {len(ok)}  Ultra flagged partial/unsupported: {len(flagged)}"
        f" (unsupported: {len(unsupported)})",
        f"Ultra claims: {len(recall_flags)}  splitter recall: {sum(recall_flags)}/{len(recall_flags)}",
        f"splitter sentences: {total_claims}  unpaired to a source: {unpaired}"
        f" ({unpaired / max(total_claims, 1):.0%})  answers with a Jev error: {sum('jev_error' in r for r in ok)}",
        f"Ultra median seconds per answer: {statistics.median(r['ultra_seconds'] for r in ok):.1f}  "
        f"mean USD: {sum(float(r['ultra_usage']) for r in ok) / len(ok):.5f}" if ok else "",
        f"Jev mean seconds per answer: {statistics.mean(r['jev_seconds'] for r in ok):.1f}  "
        f"mean USD: {sum(float(r['jev_usd']) for r in ok) / len(ok):.6f}" if ok else "",
        "",
        "| threshold | skip Ultra | skipped but Ultra flagged any | skipped but Ultra flagged unsupported | mean USD/answer | mean s/answer (skipped=Jev only) |",
        "|---|---|---|---|---|---|",
    ]
    for t in THRESHOLDS:
        skipped = [r for r in ok if _skips(r, t)]
        usd = sum(float(r["jev_usd"]) + (0 if _skips(r, t) else float(r["ultra_usage"])) for r in ok) / max(len(ok), 1)
        sec = sum(r["jev_seconds"] + (0 if _skips(r, t) else r["ultra_seconds"]) for r in ok) / max(len(ok), 1)
        lines.append(
            f"| {t} | {len(skipped)}/{len(ok)} ({len(skipped) / max(len(ok), 1):.0%}) "
            f"| {sum(r in flagged for r in skipped)} | {sum(r in unsupported for r in skipped)} "
            f"| {usd:.5f} | {sec:.1f} |"
        )
    if any("first_quote_locate" in r for r in ok):
        with_evidence = [r for r in ok if r["first_quote_locate"] is not None]
        matched = [r for r in with_evidence if r["first_quote_locate"] == "matched"]
        lines += ["", f"/locate, Ultra alone: first quote matched on {len(matched)}/{len(ok)} answers "
                      f"({len(with_evidence)} had any evidence)",
                  "| threshold | matched, answers sent to Ultra | matched, answers skipped (no evidence) | overall matched |",
                  "|---|---|---|---|"]
        for t in THRESHOLDS:
            sent = [r for r in ok if not _skips(r, t)]
            lines.append(
                f"| {t} | {sum(r['first_quote_locate'] == 'matched' for r in sent)}/{len(sent)} "
                f"| 0/{len(ok) - len(sent)} "
                f"| {sum(r['first_quote_locate'] == 'matched' for r in sent)}/{len(ok)} |"
            )
    return "\n".join(line for line in lines if line is not None)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--limit", type=int)
    c.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("analyse")
    a.add_argument("answers", type=Path)
    a.add_argument("--locate", action="store_true", help="replay evidence through POST /receipts/{id}/locate")
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

    print(f"Ultra reference model: {_MODEL}  Jev model: {os.getenv('JEV_MODEL')}")
    rows = [analyse_answer(a, locate_client=client) for a in json.loads(args.answers.read_text())]
    if args.out:
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
    print(report(rows))


if __name__ == "__main__":
    main()
