"""Developer-only eval dashboard API and isolated runner orchestration."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from evals.coverage import (
    aggregate_scenarios,
    coverage_summary,
    missing_section_pairs,
    present_section_pairs,
    required_section_pairs,
    select_cases,
)
from evals.grounding_summary import summarise as summarise_grounding

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "evals" / "dataset.json"
RESULTS_PATH = ROOT / "evals" / "results.json"
GROUNDING_DATASET_PATH = ROOT / "evals" / "grounding_dataset.json"
GROUNDING_RESULTS_PATH = ROOT / "evals" / "results" / "grounding.json"

router = APIRouter(prefix="/evals", tags=["evals"])

DEFAULT_SET = "end_to_end"


@dataclass(frozen=True)
class EvalSet:
    name: str
    # Callables, not Paths: tests monkeypatch DATASET_PATH / RESULTS_PATH on this module.
    dataset_path: Callable[[], Path]
    results_path: Callable[[], Path]
    runner_module: str
    case_passed: Callable[[dict[str, Any]], bool]
    run_summary: Callable[[list[dict[str, Any]]], dict[str, Any]]
    # False for sets that judge text directly: no corpus, so no DB check or staleness.
    needs_corpus: bool = True


EVAL_SETS: dict[str, EvalSet] = {
    DEFAULT_SET: EvalSet(
        name=DEFAULT_SET,
        dataset_path=lambda: DATASET_PATH,
        results_path=lambda: RESULTS_PATH,
        runner_module="evals.run_evals",
        case_passed=lambda result: not result.get("l1_failures")
        and isinstance(result.get("judge"), dict)
        and result["judge"].get("passed") is True,
        run_summary=lambda results: _run_summary(results),
    ),
    "grounding": EvalSet(
        name="grounding",
        dataset_path=lambda: GROUNDING_DATASET_PATH,
        results_path=lambda: GROUNDING_RESULTS_PATH,
        runner_module="evals.run_grounding",
        case_passed=lambda result: result.get("match") is True,
        run_summary=lambda results: {"type": "run_summary", **summarise_grounding(results)},
        needs_corpus=False,
    ),
}


def _get_set(name: str) -> EvalSet:
    try:
        return EVAL_SETS[name]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown eval set: {name}") from None

_active_lock = Lock()
_active_process: asyncio.subprocess.Process | None = None
_run_reserved = False


class EvalRunRequest(BaseModel):
    subset: str | dict[str, str] = "smoke"
    set: str = DEFAULT_SET


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _load_cases(eval_set: EvalSet | None = None) -> list[dict[str, Any]]:
    path = (eval_set or EVAL_SETS[DEFAULT_SET]).dataset_path()
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _staleness(cases: list[dict[str, Any]], database_url: str) -> list[dict[str, str]]:
    return missing_section_pairs(
        required_section_pairs(cases),
        present_section_pairs(database_url),
    )


def runner_command(subset: str | dict[str, str], eval_set: EvalSet | None = None) -> list[str]:
    eval_set = eval_set or EVAL_SETS[DEFAULT_SET]
    command = [
        sys.executable,
        "-m",
        eval_set.runner_module,
        "--jsonl",
        "--dataset",
        str(eval_set.dataset_path()),
        "--output",
        str(eval_set.results_path()),
    ]
    if subset == "smoke":
        command.append("--smoke")
    elif isinstance(subset, dict):
        key, value = next(iter(subset.items()))
        flag = {
            "category": "--category",
            "scenario": "--scenario",
            "case_id": "--case-id",
            "case_ids": "--case-ids",
            "language": "--language",
        }[key]
        command.extend([flag, value])
    return command


def _reserve_run() -> None:
    global _run_reserved
    with _active_lock:
        if _run_reserved or (_active_process and _active_process.returncode is None):
            raise HTTPException(status_code=409, detail="An eval run is already active")
        _run_reserved = True


def _release_reservation() -> None:
    global _run_reserved
    with _active_lock:
        _run_reserved = False


def _set_active(process: asyncio.subprocess.Process | None) -> None:
    global _active_process, _run_reserved
    with _active_lock:
        _active_process = process
        _run_reserved = False


def reset_active_run_for_tests() -> None:
    """Reset completed module state between isolated API app tests."""
    global _active_process, _run_reserved
    with _active_lock:
        if _active_process is not None and _active_process.returncode is None:
            raise RuntimeError("Cannot reset while an eval run is active")
        _active_process = None
        _run_reserved = False


@router.get("/sets")
def list_sets():
    return {"default": DEFAULT_SET, "sets": [{"name": name} for name in EVAL_SETS]}


@router.get("/coverage")
async def get_coverage(set: str = DEFAULT_SET):
    eval_set = _get_set(set)
    cases = _load_cases(eval_set)
    if not eval_set.needs_corpus:
        return {
            "total_cases": len(cases),
            "by_verdict": dict(Counter(case["verdict"] for case in cases)),
            "by_language": dict(Counter(case["language"] for case in cases)),
            "judgement_calls": sum(bool(case.get("judgement_call")) for case in cases),
            "corpus_staleness": {"checked": False, "reason": "This set needs no corpus"},
        }
    payload = coverage_summary(cases)
    database_url = os.getenv("EVALS_DATABASE_URL")
    if not database_url:
        payload["corpus_staleness"] = {
            "checked": False,
            "reason": "Eval DB not configured",
        }
        return payload

    try:
        missing = await asyncio.to_thread(_staleness, cases, database_url)
        payload["corpus_staleness"] = {"checked": True, "missing_sections": missing}
    except Exception as exc:
        payload["corpus_staleness"] = {
            "checked": False,
            "reason": f"Eval DB unreachable: {exc}",
        }
    return payload


def _run_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    l1_passed = sum(not result.get("l1_failures") for result in results)
    judged = [result["judge"] for result in results if isinstance(result.get("judge"), dict)]
    recalls = [
        result["section_recall"]["recall"]
        for result in results
        if isinstance(result.get("section_recall"), dict)
    ]
    return {
        "type": "run_summary",
        "l1": {
            "passed": l1_passed,
            "total": len(results),
            "rate": 0.0 if not results else l1_passed / len(results),
        },
        "section_recall_mean": sum(recalls) / len(recalls) if recalls else None,
        "section_recall_cases": len(recalls),
        "judge_passed": sum(verdict.get("passed") is True for verdict in judged),
        "judge_total": len(judged),
        "by_scenario": aggregate_scenarios(results),
    }


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def _readline_or_disconnect(
    process: asyncio.subprocess.Process,
    request: Request,
) -> bytes | None:
    assert process.stdout is not None
    read_task = asyncio.create_task(process.stdout.readline())
    try:
        while not read_task.done():
            if await request.is_disconnected():
                await _terminate(process)
                read_task.cancel()
                return None
            await asyncio.sleep(0.1)
        return await read_task
    finally:
        if not read_task.done():
            read_task.cancel()


@router.post("/run")
async def run_evals(req: EvalRunRequest, request: Request):
    eval_set = _get_set(req.set)
    _reserve_run()
    process: asyncio.subprocess.Process | None = None
    try:
        database_url = os.getenv("EVALS_DATABASE_URL")
        if eval_set.needs_corpus and not database_url:
            raise HTTPException(status_code=503, detail="Eval DB not configured")

        cases = _load_cases(eval_set)
        try:
            selected = select_cases(cases, req.subset)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        missing: list[dict[str, str]] = []
        if eval_set.needs_corpus:
            try:
                missing = await asyncio.to_thread(_staleness, selected, database_url)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"Eval DB unreachable: {exc}") from exc
        if missing:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Eval corpus is stale",
                    "missing_sections": missing,
                },
            )

        child_env = os.environ.copy()
        if database_url:
            child_env["DATABASE_URL"] = database_url
        child_env["CHECKPOINTER"] = "memory"
        process = await asyncio.create_subprocess_exec(
            *(
                runner_command(req.subset)
                if eval_set.name == DEFAULT_SET
                else runner_command(req.subset, eval_set)
            ),
            cwd=ROOT,
            env=child_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _set_active(process)
    except Exception:
        if process is not None:
            await _terminate(process)
        _release_reservation()
        raise

    async def stream():
        results: list[dict[str, Any]] = []
        try:
            yield _sse({"type": "run_start", "subset": req.subset, "case_count": len(selected)})
            for index, case in enumerate(selected, 1):
                yield _sse({
                    "type": "case_start",
                    "id": case["id"],
                    "index": index,
                    "total": len(selected),
                })
                line = await _readline_or_disconnect(process, request)
                if line is None:
                    return
                if not line:
                    break
                try:
                    result = json.loads(line)
                except json.JSONDecodeError as exc:
                    yield _sse({"type": "error", "message": f"Invalid eval runner output: {exc}"})
                    return
                results.append(result)
                yield _sse({"type": "case_result", **result})

            return_code = await process.wait()
            if return_code != 0:
                assert process.stderr is not None
                stderr = (await process.stderr.read()).decode("utf-8", errors="replace").strip()
                yield _sse({
                    "type": "error",
                    "message": stderr or f"Eval runner exited with status {return_code}",
                })
            elif len(results) != len(selected):
                yield _sse({"type": "error", "message": "Eval runner stopped before all cases completed"})
            else:
                yield _sse(eval_set.run_summary(results))
            yield _sse({"type": "done"})
        finally:
            if process.returncode is None:
                await _terminate(process)
            _set_active(None)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.post("/cancel")
async def cancel_evals():
    with _active_lock:
        process = _active_process
    if process is None or process.returncode is not None:
        return {"status": "no_active_run"}
    # The stream's owning event loop performs the wait/kill fallback and clears
    # module state. Sending SIGTERM here keeps cancellation server-authoritative
    # without coupling this request to the stream task's loop.
    process.terminate()
    return {"status": "cancelled"}


@router.get("/results")
def get_results(set: str = DEFAULT_SET):
    path = _get_set(set).results_path()
    if not path.exists():
        return JSONResponse(status_code=404, content={"available": False})
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/cases")
def list_cases(set: str = DEFAULT_SET):
    eval_set = _get_set(set)
    cases = _load_cases(eval_set)
    path = eval_set.results_path()
    saved: dict[str, dict[str, Any]] = {}
    if path.exists():
        for result in json.loads(path.read_text(encoding="utf-8")).get("results", []):
            case_id = (result.get("case") or {}).get("id")
            if case_id is not None:
                saved[case_id] = result

    rows = []
    for case in cases:
        result = saved.get(case["id"])
        status = "not run" if result is None else (
            "passed" if eval_set.case_passed(result) else "failed"
        )
        rows.append({**case, "status": status, "result": result})
    return {"set": eval_set.name, "cases": rows}
