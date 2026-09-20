import json
from unittest.mock import MagicMock, patch

import pytest

from evals import seed_test_corpus


def _dataset(tmp_path, cases):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({"cases": cases}))
    return path


def _case(case_id, act, section):
    return {
        "id": case_id,
        "citation_applicable": True,
        "expected_act_number": act,
        "expected_section": section,
    }


def _write_chunk(chunks_dir, act_number, rows):
    chunks_dir.mkdir(exist_ok=True)
    (chunks_dir / f"{act_number}.json").write_text(json.dumps(rows))


def _mock_conn():
    cursor = MagicMock()
    cursor.__enter__ = lambda self: self
    cursor.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.__enter__ = lambda self: self
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn, cursor


def _run(monkeypatch, tmp_path, *, cases, chunks, present, argv):
    dataset_path = _dataset(tmp_path, cases)
    chunks_dir = tmp_path / "chunks"
    for act_number, rows in chunks.items():
        _write_chunk(chunks_dir, act_number, rows)

    conn, cursor = _mock_conn()
    embedding_client_mock = MagicMock(return_value=MagicMock())

    monkeypatch.setattr(seed_test_corpus, "DATASET_PATH", dataset_path)
    monkeypatch.setattr(seed_test_corpus, "CHUNKS_DIR", chunks_dir)
    monkeypatch.setattr(seed_test_corpus, "present_section_pairs", lambda _url: present)
    monkeypatch.setattr(seed_test_corpus, "_connect", lambda: conn)
    monkeypatch.setattr(seed_test_corpus, "embedding_client", embedding_client_mock)
    monkeypatch.setattr(seed_test_corpus, "_embed_batch", lambda client, texts: [[0.0]] * len(texts))
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setattr("sys.argv", argv)

    with patch.object(seed_test_corpus.psycopg2.extras, "execute_values") as execute_values:
        exit_code = seed_test_corpus.main()
    return exit_code, cursor, execute_values, embedding_client_mock


def test_missing_only_seeds_only_the_gap_and_never_truncates(tmp_path, monkeypatch):
    exit_code, cursor, execute_values, _embedding_client_mock = _run(
        monkeypatch, tmp_path,
        cases=[_case("has-it", "56", "90A"), _case("needs-it", "265", "19")],
        chunks={
            "56": [{"act_number": "56", "section_number": "90A", "content": "Section 90A text"}],
            "265": [{"act_number": "265", "section_number": "19", "content": "Section 19 text"}],
        },
        present={("56", "90A")},
        argv=["seed_test_corpus", "--missing-only"],
    )

    assert exit_code == 0
    executed_sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert not any("TRUNCATE" in sql for sql in executed_sql)
    execute_values.assert_called_once()
    _cur, _sql, records = execute_values.call_args.args
    assert [(row[0], row[2]) for row in records] == [("265", "19")]


def test_missing_only_no_op_when_nothing_missing_skips_embedding_entirely(tmp_path, monkeypatch, capsys):
    exit_code, cursor, execute_values, embedding_client_mock = _run(
        monkeypatch, tmp_path,
        cases=[_case("has-it", "56", "90A")],
        chunks={"56": [{"act_number": "56", "section_number": "90A", "content": "Section 90A text"}]},
        present={("56", "90A")},
        argv=["seed_test_corpus", "--missing-only"],
    )

    assert exit_code == 0
    embedding_client_mock.assert_not_called()
    execute_values.assert_not_called()
    assert cursor.execute.call_count == 0
    assert "already has every required section" in capsys.readouterr().out


def test_clear_and_missing_only_are_mutually_exclusive(tmp_path, monkeypatch):
    dataset_path = _dataset(tmp_path, [_case("x", "56", "90A")])
    monkeypatch.setattr(seed_test_corpus, "DATASET_PATH", dataset_path)
    monkeypatch.setattr("sys.argv", ["seed_test_corpus", "--clear", "--missing-only"])

    with pytest.raises(SystemExit):
        seed_test_corpus.main()
