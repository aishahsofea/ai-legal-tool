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
It is only loaded when a BM or mixed case is actually scored, so an
English-only run (the CI smoke gate) never touches it.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache

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


@lru_cache(maxsize=1)
def _model():
    repo = os.getenv("BM_LANGID_MODEL_REPO", DEFAULT_MODEL_REPO)
    filename = os.getenv("BM_LANGID_MODEL_FILE", DEFAULT_MODEL_FILE)
    try:
        import fasttext
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise LanguageModelUnavailable(
            "language_register scoring needs `fasttext-predict` and `huggingface-hub` "
            "(both in requirements.txt)."
        ) from exc
    try:
        path = hf_hub_download(repo_id=repo, filename=filename)
        return fasttext.load_model(path)
    except Exception as exc:
        raise LanguageModelUnavailable(
            f"Could not load the language classifier {repo}/{filename}: {exc}"
        ) from exc


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
