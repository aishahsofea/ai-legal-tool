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


def test_run_rejects_unknown_case_ids_with_422(tmp_path, monkeypatch):
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")
    monkeypatch.setenv("EVALS_DATABASE_URL", "postgresql://evals")

    response = client.post("/evals/run", json={"subset": {"case_ids": "case-1,nope"}})

    assert response.status_code == 422
    assert "nope" in response.json()["detail"]


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


def test_run_gates_staleness_on_the_selected_subset_not_the_whole_dataset(tmp_path, monkeypatch):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps({
        "cases": [
            {
                "id": "smoke-case",
                "category": "citation",
                "scenario": "exact_match",
                "query": "What does section 90A provide?",
                "expected_act_number": "56",
                "expected_section": "90A",
                "citation_applicable": True,
                "expected_policy": "allow",
                "smoke": True,
            },
            {
                "id": "non-smoke-case",
                "category": "citation",
                "scenario": "exact_match",
                "query": "What does section 19 provide?",
                "expected_act_number": "265",
                "expected_section": "19",
                "citation_applicable": True,
                "expected_policy": "allow",
                "smoke": False,
            },
        ]
    }))
    script = tmp_path / "fake_runner.py"
    script.write_text(
        "import json\n"
        "print(json.dumps({"
        "'id':'smoke-case','category':'citation','scenario':'exact_match',"
        "'expected_policy':'allow','expected_act_number':'56','expected_section':'90A',"
        "'l1_failures':[],'l1_failure_details':{},'judge':{'passed':True,'reasoning':'Grounded'},"
        "'query':'What does section 90A provide?','response':'Answer','citations':[],"
        "'elapsed_seconds':0.01}), flush=True)\n"
    )
    client = _client(monkeypatch, dataset_path, tmp_path / "results.json")
    monkeypatch.setenv("EVALS_DATABASE_URL", "postgresql://evals")
    # Only the smoke case's section is seeded; the non-smoke case's section is
    # absent. A smoke-only run must not be blocked by a section no case in the
    # selected subset needs.
    monkeypatch.setattr(evals_api, "present_section_pairs", lambda _url: {("56", "90A")})
    monkeypatch.setattr(evals_api, "runner_command", lambda _subset: [sys.executable, str(script)])

    response = client.post("/evals/run", json={"subset": "smoke"})

    assert response.status_code == 200
    # CORS headers come from the app middleware (FRONTEND_ORIGIN), never from the route.
    assert "access-control-allow-origin" not in response.headers


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


def test_runner_command_passes_each_dashboard_subset_through_as_its_cli_flag():
    assert evals_api.runner_command("smoke")[-1] == "--smoke"
    assert "--smoke" not in evals_api.runner_command("all")

    for subset, flag, value in (
        ({"category": "citation"}, "--category", "citation"),
        ({"scenario": "mixed_language"}, "--scenario", "mixed_language"),
        ({"case_id": "evidence-90a-1"}, "--case-id", "evidence-90a-1"),
        ({"language": "bm,mixed"}, "--language", "bm,mixed"),
        ({"case_ids": "a,b,c"}, "--case-ids", "a,b,c"),
    ):
        assert evals_api.runner_command(subset)[-2:] == [flag, value]


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


def test_sets_lists_the_registry_with_end_to_end_as_default(tmp_path, monkeypatch):
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")

    response = client.get("/evals/sets")

    assert response.status_code == 200
    assert response.json() == {"default": "end_to_end", "sets": [{"name": "end_to_end"}, {"name": "grounding"}]}


def test_unknown_set_returns_404_on_every_endpoint(tmp_path, monkeypatch):
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")

    assert client.get("/evals/coverage?set=nope").status_code == 404
    assert client.get("/evals/results?set=nope").status_code == 404
    assert client.post("/evals/run", json={"subset": "smoke", "set": "nope"}).status_code == 404


def test_explicit_end_to_end_set_matches_the_default(tmp_path, monkeypatch):
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps({"results": []}))
    client = _client(monkeypatch, _dataset(tmp_path), results_path)

    assert client.get("/evals/coverage?set=end_to_end").json()["total_cases"] == 1
    assert client.get("/evals/results?set=end_to_end").json() == client.get("/evals/results").json()


def test_runner_command_uses_the_set_runner_and_paths(tmp_path, monkeypatch):
    _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")

    command = evals_api.runner_command("smoke", evals_api.EVAL_SETS["end_to_end"])

    assert command[2] == "evals.run_evals"
    assert str(tmp_path / "dataset.json") in command
    assert str(tmp_path / "results.json") in command


def test_cases_without_results_are_all_not_run(tmp_path, monkeypatch):
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")

    body = client.get("/evals/cases").json()

    assert body["set"] == "end_to_end"
    assert [(c["id"], c["status"], c["result"]) for c in body["cases"]] == [("case-1", "not run", None)]
    assert body["cases"][0]["query"] == "What does section 90A provide?"


def test_cases_merge_saved_results_and_ignore_unknown_ids(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"cases": [{"id": i, "query": i} for i in ("a", "b", "c")]}))
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"results": [
        {"case": {"id": "a"}, "l1_failures": [], "judge": {"passed": True}},
        {"case": {"id": "b"}, "l1_failures": ["x"], "judge": {"passed": True}},
        {"case": {"id": "gone"}, "l1_failures": [], "judge": {"passed": True}},
    ]}))
    client = _client(monkeypatch, dataset, results)

    body = client.get("/evals/cases").json()

    assert [(c["id"], c["status"]) for c in body["cases"]] == [
        ("a", "passed"), ("b", "failed"), ("c", "not run"),
    ]


def test_cases_unknown_set_returns_404(tmp_path, monkeypatch):
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")

    assert client.get("/evals/cases?set=nope").status_code == 404


def test_cases_smoke_against_real_dataset(monkeypatch, tmp_path):
    client = _client(monkeypatch, evals_api.ROOT / "evals" / "dataset.json", tmp_path / "none.json")

    assert len(client.get("/evals/cases").json()["cases"]) == 80


def test_grounding_cases_against_real_dataset(monkeypatch, tmp_path):
    monkeypatch.setattr(evals_api, "GROUNDING_RESULTS_PATH", tmp_path / "none.json")
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")

    cases = client.get("/evals/cases?set=grounding").json()["cases"]

    assert len(cases) == 134
    assert {v: sum(c["verdict"] == v for c in cases) for v in ("supported", "partial", "unsupported")} == {
        "supported": 56, "partial": 24, "unsupported": 54,
    }
    assert {c["status"] for c in cases} == {"not run"}


def test_grounding_status_is_match_or_mismatch(tmp_path, monkeypatch):
    results_path = tmp_path / "grounding.json"
    results_path.write_text(json.dumps({"results": [
        {"id": "g001", "case": {"id": "g001"}, "match": True},
        {"id": "g002", "case": {"id": "g002"}, "match": False, "error_kind": "too_lenient"},
    ]}))
    monkeypatch.setattr(evals_api, "GROUNDING_RESULTS_PATH", results_path)
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")

    status = {c["id"]: c["status"] for c in client.get("/evals/cases?set=grounding").json()["cases"]}

    assert status["g001"] == "passed"
    assert status["g002"] == "failed"
    assert status["g003"] == "not run"


def test_grounding_coverage_needs_no_corpus(tmp_path, monkeypatch):
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")

    body = client.get("/evals/coverage?set=grounding").json()

    assert body["total_cases"] == 134
    assert body["by_verdict"] == {"supported": 56, "partial": 24, "unsupported": 54}
    assert sum(body["by_language"].values()) == 134
    assert body["judgement_calls"] == 13
    assert body["corpus_staleness"]["checked"] is False


def test_grounding_run_skips_the_db_and_staleness_checks(tmp_path, monkeypatch):
    script = tmp_path / "fake_runner.py"
    script.write_text(
        "import json\n"
        "for cid, match, kind in (('g001', True, None), ('g002', False, 'too_lenient')):\n"
        "    print(json.dumps({'id': cid, 'match': match, 'error_kind': kind,"
        " 'jev_cleared': False, 'jev_error': False}), flush=True)\n"
    )
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "results.json")
    monkeypatch.delenv("EVALS_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        evals_api, "runner_command", lambda _subset, _set=None: [sys.executable, str(script)]
    )

    response = client.post(
        "/evals/run", json={"set": "grounding", "subset": {"case_ids": "g001,g002"}}
    )
    events = _events(response)

    assert response.status_code == 200
    assert [e["type"] for e in events] == [
        "run_start", "case_start", "case_result", "case_start", "case_result", "run_summary", "done"
    ]
    assert events[-2]["matched"] == 1
    assert events[-2]["by_error_kind"] == {"too_lenient": 1}


def test_grounding_runner_command_uses_the_grounding_runner(tmp_path, monkeypatch):
    command = evals_api.runner_command({"case_ids": "g001"}, evals_api.EVAL_SETS["grounding"])

    assert command[2] == "evals.run_grounding"
    assert command[-2:] == ["--case-ids", "g001"]


def test_each_set_reads_only_its_own_results_file(tmp_path, monkeypatch):
    grounding_path = tmp_path / "grounding.json"
    grounding_path.write_text(json.dumps({"results": [{"id": "g001", "case": {"id": "g001"}, "match": True}]}))
    monkeypatch.setattr(evals_api, "GROUNDING_RESULTS_PATH", grounding_path)
    client = _client(monkeypatch, _dataset(tmp_path), tmp_path / "end_to_end.json")

    assert client.get("/evals/results?set=end_to_end").status_code == 404
    assert client.get("/evals/results?set=grounding").status_code == 200
    assert evals_api.runner_command("all", evals_api.EVAL_SETS["grounding"]).count(str(grounding_path)) == 1
    assert str(tmp_path / "end_to_end.json") in evals_api.runner_command("all")
