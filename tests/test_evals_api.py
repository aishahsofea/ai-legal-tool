import asyncio
import json
import sys
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.evals as evals_api


def _dataset(tmp_path, *, smoke: bool = True):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({
        "cases": [{
            "id": "case-1",
            "category": "citation",
            "scenario": "exact_match",
            "query": "What does section 90A provide?",
            "expected_act_number": "56",
            "expected_section": "90A",
            "citation_applicable": True,
            "expected_policy": "allow",
            "smoke": smoke,
        }]
    }))
    return path


def _client(monkeypatch, dataset_path, results_path):
    monkeypatch.setattr(evals_api, "DATASET_PATH", dataset_path)
    monkeypatch.setattr(evals_api, "RESULTS_PATH", results_path)
    evals_api.reset_active_run_for_tests()
    app = FastAPI()
    app.include_router(evals_api.router)
    return TestClient(app)


def _events(response):
    return [
        json.loads(block.removeprefix("data: "))
        for block in response.text.strip().split("\n\n")
    ]


def test_coverage_counts_render_when_eval_database_is_not_configured(tmp_path, monkeypatch):
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")
    monkeypatch.delenv("EVALS_DATABASE_URL", raising=False)

    response = client.get("/evals/coverage")

    assert response.status_code == 200
    assert response.json()["total_cases"] == 1
    assert response.json()["by_scenario"] == {"exact_match": 1}
    assert response.json()["corpus_staleness"] == {
        "checked": False,
        "reason": "Eval DB not configured",
    }


def test_run_requires_a_configured_and_fresh_eval_corpus(tmp_path, monkeypatch):
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")
    monkeypatch.delenv("EVALS_DATABASE_URL", raising=False)
    assert client.post("/evals/run", json={"subset": "smoke"}).status_code == 503

    monkeypatch.setenv("EVALS_DATABASE_URL", "postgresql://evals")
    monkeypatch.setattr(evals_api, "present_section_pairs", lambda _url: set())
    stale = client.post("/evals/run", json={"subset": "smoke"})

    assert stale.status_code == 422
    assert stale.json()["detail"]["missing_sections"] == [
        {"act_number": "56", "section_number": "90A"}
    ]


def test_run_streams_fake_jsonl_and_aggregates_a_summary(tmp_path, monkeypatch):
    dataset_path = _dataset(tmp_path)
    results_path = tmp_path / "results.json"
    script = tmp_path / "fake_runner.py"
    script.write_text(
        "import json\n"
        "print(json.dumps({"
        "'id':'case-1','category':'citation','scenario':'exact_match',"
        "'expected_policy':'allow','expected_act_number':'56','expected_section':'90A',"
        "'l1_failures':[],'l1_failure_details':{},'judge':{'passed':True,'reasoning':'Grounded'},"
        "'query':'What does section 90A provide?','response':'Answer','citations':[],"
        "'elapsed_seconds':0.01}), flush=True)\n"
    )
    client = _client(monkeypatch, dataset_path, results_path)
    monkeypatch.setenv("EVALS_DATABASE_URL", "postgresql://evals")
    monkeypatch.setattr(evals_api, "present_section_pairs", lambda _url: {("56", "90A")})
    monkeypatch.setattr(
        evals_api,
        "runner_command",
        lambda _subset: [sys.executable, str(script)],
    )

    response = client.post("/evals/run", json={"subset": "smoke"})
    events = _events(response)

    assert response.status_code == 200
    assert [event["type"] for event in events] == [
        "run_start", "case_start", "case_result", "run_summary", "done"
    ]
    assert events[0]["case_count"] == 1
    assert events[2]["id"] == "case-1"
    assert events[3]["judge_passed"] == 1
    assert events[3]["judge_total"] == 1
    assert events[3]["by_scenario"] == {
        "exact_match": {"passed": 1, "total": 1, "rate": 1.0}
    }


def test_results_returns_unavailable_then_the_last_report_verbatim(tmp_path, monkeypatch):
    results_path = tmp_path / "results.json"
    client = _client(monkeypatch, _dataset(tmp_path), results_path)

    missing = client.get("/evals/results")
    assert missing.status_code == 404
    assert missing.json() == {"available": False}

    report = {"generated_at": "now", "summary": {"total_cases": 1}, "results": []}
    results_path.write_text(json.dumps(report))
    available = client.get("/evals/results")
    assert available.status_code == 200
    assert available.json() == report


def test_concurrent_run_is_rejected_and_cancel_is_idempotent(tmp_path, monkeypatch):
    dataset_path = _dataset(tmp_path)
    script = tmp_path / "slow_runner.py"
    script.write_text("import time\ntime.sleep(30)\n")
    client = _client(monkeypatch, dataset_path, tmp_path / "results.json")
    monkeypatch.setenv("EVALS_DATABASE_URL", "postgresql://evals")
    monkeypatch.setattr(evals_api, "present_section_pairs", lambda _url: {("56", "90A")})
    command_built = threading.Event()

    def command(_subset):
        command_built.set()
        return [sys.executable, str(script)]

    monkeypatch.setattr(evals_api, "runner_command", command)
    responses = []
    worker = threading.Thread(
        target=lambda: responses.append(client.post("/evals/run", json={"subset": "smoke"})),
        daemon=True,
    )
    worker.start()
    assert command_built.wait(timeout=2)
    time.sleep(0.1)

    conflict = client.post("/evals/run", json={"subset": "smoke"})
    cancelled = client.post("/evals/cancel")
    worker.join(timeout=3)

    assert conflict.status_code == 409
    assert cancelled.json() == {"status": "cancelled"}
    assert not worker.is_alive()
    assert client.post("/evals/cancel").json() == {"status": "no_active_run"}


def test_disconnected_stream_terminates_the_runner(tmp_path):
    script = tmp_path / "headless_runner.py"
    script.write_text("import time\ntime.sleep(30)\n")

    class DisconnectedRequest:
        async def is_disconnected(self):
            return True

    async def scenario():
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            stdout=asyncio.subprocess.PIPE,
        )
        line = await evals_api._readline_or_disconnect(process, DisconnectedRequest())
        await process.wait()
        return line, process.returncode

    line, return_code = asyncio.run(scenario())
    assert line is None
    assert return_code is not None
