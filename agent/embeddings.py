"""
Provider-agnostic embedding factory, mirroring agent/llm_factory.py's role for
chat models but for embeddings.

Corpus-side (ingestion) and query-side (statute search) embeddings must come
from the same model or retrieval degrades silently — no error, just worse
hits. Every writer into the `chunks` table and the query path resolve
CORPUS_EMBEDDING_MODEL here, so the two can no longer drift apart.

The Semantic Memory store (agent/graph.py) is a separate collection with no
reason to move when the corpus model changes, so it resolves through its own
make_memory_embedder() and MEMORY_EMBEDDING_MODEL.
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def embedding_client(**client_kwargs) -> OpenAI:
    """EMBEDDING_BASE_URL points both embedders at an OpenAI-compatible provider.

    client_kwargs pass through to OpenAI() for callers with their own client
    policy — corpus/rollout.py needs max_retries=0 to keep its dollar cap exact.
    """
    return OpenAI(base_url=os.getenv("EMBEDDING_BASE_URL") or None, **client_kwargs)


def corpus_embedding_model() -> str:
    """Model name without a client, so argparse defaults and `--help` need no API key."""
    return os.getenv("CORPUS_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def memory_embedding_model() -> str:
    return os.getenv("MEMORY_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def make_corpus_embedder() -> tuple[OpenAI, str]:
    """Client + model for the statute corpus — every ingest path and query-side search."""
    return embedding_client(), corpus_embedding_model()


def make_memory_embedder() -> tuple[OpenAI, str]:
    """Client + model for the Semantic Memory store, independent of the corpus model."""
    return embedding_client(), memory_embedding_model()
