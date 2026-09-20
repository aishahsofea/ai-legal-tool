from unittest.mock import MagicMock, patch

import pytest

from evals import setup_eval_db


def _mock_maintenance_conn():
    cursor = MagicMock()
    cursor.__enter__ = lambda self: self
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = (1,)  # database already exists, skip CREATE DATABASE
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _run(monkeypatch, argv):
    conn, cursor = _mock_maintenance_conn()
    monkeypatch.setenv("EVALS_DATABASE_URL", "postgresql://example/ai_legal_tool_evals")
    monkeypatch.setattr(setup_eval_db.psycopg2, "connect", lambda _url: conn)
    monkeypatch.setattr("sys.argv", argv)

    with patch.object(setup_eval_db.subprocess, "run") as run:
        run.return_value = MagicMock(returncode=0)
        exit_code = setup_eval_db.main()
    return exit_code, run, cursor


def test_default_run_passes_clear_to_the_seed_subprocess(monkeypatch):
    exit_code, run, _cursor = _run(monkeypatch, ["setup_eval_db"])

    assert exit_code == 0
    assert run.call_args.args[0][-1] == "--clear"


def test_missing_only_passes_missing_only_to_the_seed_subprocess(monkeypatch):
    exit_code, run, _cursor = _run(monkeypatch, ["setup_eval_db", "--missing-only"])

    assert exit_code == 0
    assert run.call_args.args[0][-1] == "--missing-only"


def test_seed_subprocess_inherits_the_eval_database_url(monkeypatch):
    _exit_code, run, _cursor = _run(monkeypatch, ["setup_eval_db"])

    child_env = run.call_args.kwargs["env"]
    assert child_env["DATABASE_URL"] == "postgresql://example/ai_legal_tool_evals"


def test_missing_eval_database_url_exits_before_touching_the_database(monkeypatch):
    monkeypatch.delenv("EVALS_DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["setup_eval_db"])

    with pytest.raises(SystemExit, match="EVALS_DATABASE_URL"):
        setup_eval_db.main()
