"""BM/English language identification for the `language_register` L1 assertion.

Scores what share of a response is Bahasa Malaysia. The assertion needs a
*ratio* rather than a keyword hit: a mostly-English answer with one stray
"seksyen" in it is the exact failure the old wordlist could not see.

Scoring is segment-level, not whole-text. A correct answer to a mixed-language
query is deliberately bilingual (BM framing, English statute quotes, BM
disclaimer — see ADR 0004 and the 2026-05-16 build-log entry), and fastText
scores such a document as whichever language has more words. Splitting on
sentence boundaries and weighting each segment by its word count gives the
composition of the answer instead.

Only responses are scored. Which cases the assertion applies to comes from the
`language` a case declares, because scoring short queries is not reliable in
either direction: the classifier reads "Am I liable if I posted the comment
online?" as 48% BM, and reads two of the code-switched cases as almost entirely
English. A declared label also keeps an English-only run model-free.

The classifier is mesolitica/fasttext-language-detection-bahasa-en, downloaded
from the Hugging Face Hub on first use and cached under ~/.cache/huggingface.
A cached copy is loaded straight from disk, so a second run needs no network at
all. It is only loaded when a BM or mixed case is actually scored, so an
English-only run (the CI smoke gate) never touches it.
"""
from __future__ import annotations

import os
import re
from typing import Any

# Share of a response that must be BM, by the language the case declares.
# Calibrated in issue #38 against the synthesiser's answers to all 40 BM/mixed
# cases: every `bm` answer scored 1.00, and `mixed` answers ran 0.42 to 1.00
# (the spread is how much English statute text each one quotes). Both thresholds
# sit below the observed floor, and far above the 0.00-0.05 an English answer
# with a stray BM word scores — which is the failure this replaced.
BM_SHARE_THRESHOLDS: dict[str, float] = {"bm": 0.60, "mixed": 0.25}

DEFAULT_MODEL_REPO = "mesolitica/fasttext-language-detection-bahasa-en"
DEFAULT_MODEL_FILE = "fasttext.ftz"

# Sentence enders plus line breaks. Statute quotes are usually their own
# sentence or their own line, which is what makes segment scoring work.
_SEGMENT_RE = re.compile(r"(?<=[.!?;:])\s+|\n+")

# Below this, fastText is scoring noise ("Ya.", a bare section number), and the
# label it returns is usually "other".
_MIN_SEGMENT_WORDS = 3


class LanguageModelUnavailable(RuntimeError):
    """The fastText classifier could not be loaded (missing package, or no
    cached copy and no network). Raised rather than returning a neutral score:
    a language assertion that silently stops scoring is worse than a failed run.
    """


# Two sentences whose language is not in doubt. Predicting both at load time is
# how a wrong `BM_LANGID_MODEL_REPO` is caught: a classifier with different label
# names would otherwise score every segment 0/0, and each case would fail as
# "no scoreable text" — which reads like an agent regression, not a config error.
_LABEL_PROBES = (
    "Seseorang pekerja tidak boleh dikehendaki bekerja lebih daripada lapan jam sehari.",
    "An employee shall not be required to work more than eight hours in one day.",
)

_model_cache: Any = None
_load_error: LanguageModelUnavailable | None = None


def _download_path(repo: str, filename: str) -> str:
    try:
        from huggingface_hub import hf_hub_download, try_to_load_from_cache
    except ImportError as exc:
        raise LanguageModelUnavailable(
            "language_register scoring needs `fasttext-predict` and `huggingface-hub` "
            "(both in requirements.txt)."
        ) from exc

    # hf_hub_download revalidates the etag over HTTP even on a cache hit, so a
    # cached copy is resolved from disk first: an eval run with no network still
    # scores, and a run with network makes no request at all.
    cached = try_to_load_from_cache(repo, filename)
    if isinstance(cached, str):
        return cached
    return hf_hub_download(repo_id=repo, filename=filename)


def _check_labels(model, repo: str, filename: str) -> None:
    seen: set[str] = set()
    for probe in _LABEL_PROBES:
        labels, _ = model.predict(probe, k=3)
        seen.update(label.removeprefix("__label__") for label in labels)
    missing = {"bahasa", "english"} - seen
    if missing:
        raise LanguageModelUnavailable(
            f"The classifier {repo}/{filename} never predicts {sorted(missing)}; "
            f"it labels text {sorted(seen)}. `language_register` scores the "
            "`bahasa` and `english` labels, so this model cannot back it."
        )


def _load_model():
    repo = os.getenv("BM_LANGID_MODEL_REPO", DEFAULT_MODEL_REPO)
    filename = os.getenv("BM_LANGID_MODEL_FILE", DEFAULT_MODEL_FILE)
    try:
        import fasttext
    except ImportError as exc:
        raise LanguageModelUnavailable(
            "language_register scoring needs `fasttext-predict` and `huggingface-hub` "
            "(both in requirements.txt)."
        ) from exc
    try:
        model = fasttext.load_model(_download_path(repo, filename))
    except LanguageModelUnavailable:
        raise
    except Exception as exc:
        raise LanguageModelUnavailable(
            f"Could not load the language classifier {repo}/{filename}: {exc}"
        ) from exc
    _check_labels(model, repo, filename)
    return model


def _model():
    global _model_cache, _load_error
    if _model_cache is not None:
        return _model_cache
    # A failure is remembered, so a missing model is not retried once per segment
    # of every case. `ensure_available()` is where a run is meant to hit it.
    if _load_error is not None:
        raise _load_error
    try:
        _model_cache = _load_model()
    except LanguageModelUnavailable as exc:
        _load_error = exc
        raise
    return _model_cache


def ensure_available() -> None:
    """Load the classifier now, so a run that needs it fails before the first
    LLM call rather than part-way through a paid eval.

    Raises LanguageModelUnavailable.
    """
    _model()


def _segments(text: str) -> list[str]:
    return [
        segment
        for segment in (" ".join(part.split()) for part in _SEGMENT_RE.split(text or ""))
        if len(segment.split()) >= _MIN_SEGMENT_WORDS
    ]


def _bm_en_probabilities(text: str) -> tuple[float, float]:
    """(bahasa, english) probabilities for one line of text.

    The model's third label is "other"; it is dropped here so the pair
    renormalizes to the BM-vs-EN question the assertion actually asks.
    """
    labels, values = _model().predict(text, k=3)
    scores = {label.removeprefix("__label__"): float(value) for label, value in zip(labels, values)}
    return scores.get("bahasa", 0.0), scores.get("english", 0.0)


def bm_share(text: str) -> float | None:
    """Word-weighted share of `text` that is Bahasa Malaysia, 0.0 to 1.0.

    None when nothing in the text is long enough to score — an empty response,
    or one that is only a section number. Callers decide what that means;
    `check_language_register` treats it as unscoreable rather than as a pass.

    Raises LanguageModelUnavailable if the classifier cannot be loaded.
    """
    bm_weight = 0.0
    en_weight = 0.0
    for segment in _segments(text):
        bahasa, english = _bm_en_probabilities(segment)
        total = bahasa + english
        if total <= 0:
            continue
        words = len(segment.split())
        bm_weight += words * bahasa / total
        en_weight += words * english / total
    scored = bm_weight + en_weight
    if scored == 0:
        return None
    return bm_weight / scored
