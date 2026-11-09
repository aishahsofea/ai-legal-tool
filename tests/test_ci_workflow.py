from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "tests.yml"


@pytest.fixture(scope="module")
def raw() -> str:
    return WORKFLOW.read_text()


@pytest.fixture(scope="module")
def wf(raw: str) -> dict:
    return yaml.safe_load(raw)


@pytest.fixture(scope="module")
def steps(wf: dict) -> list[dict]:
    return wf["jobs"]["pytest"]["steps"]


def _index(steps: list[dict], needle: str) -> int:
    return next(i for i, s in enumerate(steps) if needle in s.get("run", ""))


def test_triggers_on_pull_request_only(wf):
    # PyYAML parses the bare key `on` as True
    assert wf.get("on", wf.get(True)) == "pull_request" or list(wf.get("on", wf.get(True))) == ["pull_request"]


def test_python_311(steps):
    setup = next(s for s in steps if s.get("uses", "").startswith("actions/setup-python"))
    assert setup["with"]["python-version"] == "3.11"


def test_installs_english_tessdata(steps):
    assert any("tesseract-ocr-eng" in s.get("run", "") for s in steps)


def test_tessdata_guard_runs_before_pytest(steps):
    assert _index(steps, "test -f") < _index(steps, "python3 -m pytest")


def test_pytest_runs_with_tracing_off(wf, steps):
    job = wf["jobs"]["pytest"]
    step = steps[_index(steps, "python3 -m pytest")]
    env = {**job.get("env", {}), **step.get("env", {})}
    assert env.get("LANGSMITH_TRACING") == "false"


def test_pytest_exit_code_is_not_hidden(steps, raw):
    assert not any("continue-on-error" in s for s in steps)
    assert "|| true" not in raw


@pytest.mark.parametrize("forbidden", ["secrets.", "DATABASE_URL", "CORPUS_SIDECAR_ROOT"])
def test_no_secrets_db_or_sidecar_override(raw, forbidden):
    assert forbidden not in raw
