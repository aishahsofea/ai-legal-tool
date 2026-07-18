"""Developer-only eval dashboard API and isolated runner orchestration."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from threading import Lock
from typing import Any

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from evals.coverage import (
    aggregate_scenarios,
    coverage_summary,
    missing_section_pairs,
    required_section_pairs,
    select_cases,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "evals" / "dataset.json"
RESULTS_PATH = ROOT / "evals" / "results.json"

router = APIRouter(prefix="/evals", tags=["evals"])

_active_lock = Lock()
_active_process: asyncio.subprocess.Process | None = None
_run_reserved = False


class EvalRunRequest(BaseModel):
    subset: str | dict[str, str] = "smoke"


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _load_cases() -> list[dict[str, Any]]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]


def present_section_pairs(database_url: str) -> set[tuple[str, str]]:
    """Read the Act/section keys currently present in the dedicated eval corpus."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT act_number, section_number FROM chunks")
            return {(str(act), str(section).upper()) for act, section in cursor.fetchall()}


def _staleness(cases: list[dict[str, Any]], database_url: str) -> list[dict[str, str]]:
    return missing_section_pairs(
        required_section_pairs(cases),
        present_section_pairs(database_url),
    )


def runner_command(subset: str | dict[str, str]) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "evals.run_evals",
        "--jsonl",
        "--dataset",
        str(DATASET_PATH),
        "--output",
        str(RESULTS_PATH),
    ]
    if subset == "smoke":
        command.append("--smoke")
    elif isinstance(subset, dict):
        key, value = next(iter(subset.items()))
        flag = {"category": "--category", "scenario": "--scenario", "case_id": "--case-id"}[key]
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


@router.get("/coverage")
async def get_coverage():
    cases = _load_cases()
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
    return {
        "type": "run_summary",
        "l1": {
            "passed": l1_passed,
            "total": len(results),
            "rate": 0.0 if not results else l1_passed / len(results),
        },
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
    _reserve_run()
    process: asyncio.subprocess.Process | None = None
    try:
        database_url = os.getenv("EVALS_DATABASE_URL")
        if not database_url:
            raise HTTPException(status_code=503, detail="Eval DB not configured")

        cases = _load_cases()
        try:
            selected = select_cases(cases, req.subset)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            missing = await asyncio.to_thread(_staleness, cases, database_url)
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
        child_env["DATABASE_URL"] = database_url
        child_env["CHECKPOINTER"] = "memory"
        process = await asyncio.create_subprocess_exec(
            *runner_command(req.subset),
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
                yield _sse(_run_summary(results))
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
def get_results():
    if not RESULTS_PATH.exists():
        return JSONResponse(status_code=404, content={"available": False})
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
