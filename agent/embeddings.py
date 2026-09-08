"""
Provider-agnostic embedding factory, mirroring agent/llm_factory.py's role for
chat models but for embeddings.

Corpus-side (ingestion) and query-side (statute search) embeddings must come
from the same model or retrieval degrades silently — no error, just worse
hits. Both call sites go through make_corpus_embedder() so CORPUS_EMBEDDING_MODEL
is resolved once, here, instead of duplicated per call site.

The Semantic Memory store (agent/graph.py) is a separate collection with no
reason to move when the corpus model changes, so it resolves through its own
make_memory_embedder() and MEMORY_EMBEDDING_MODEL.
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def _client() -> OpenAI:
    base_url = os.getenv("EMBEDDING_BASE_URL") or None
    return OpenAI(base_url=base_url)


def make_corpus_embedder() -> tuple[OpenAI, str]:
    """Client + model for the statute corpus — shared by ingestion and query-side search."""
    model = os.getenv("CORPUS_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    return _client(), model


def make_memory_embedder() -> tuple[OpenAI, str]:
    """Client + model for the Semantic Memory store, independent of the corpus model."""
    model = os.getenv("MEMORY_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    return _client(), model
