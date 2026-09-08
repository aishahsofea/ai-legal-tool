import importlib
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import agent.embeddings as embeddings


class EmbeddingFactoryTests(unittest.TestCase):
    def test_corpus_defaults_to_text_embedding_3_small(self):
        env = {k: v for k, v in os.environ.items() if k != "CORPUS_EMBEDDING_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            _, model = embeddings.make_corpus_embedder()
        self.assertEqual(model, "text-embedding-3-small")

    def test_memory_defaults_to_text_embedding_3_small(self):
        env = {k: v for k, v in os.environ.items() if k != "MEMORY_EMBEDDING_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            _, model = embeddings.make_memory_embedder()
        self.assertEqual(model, "text-embedding-3-small")

    def test_corpus_model_is_configurable(self):
        with patch.dict(os.environ, {"CORPUS_EMBEDDING_MODEL": "text-embedding-3-large"}):
            _, model = embeddings.make_corpus_embedder()
        self.assertEqual(model, "text-embedding-3-large")

    def test_memory_model_independent_of_corpus(self):
        # Setting the corpus var must not move the memory store's model.
        with patch.dict(os.environ, {"CORPUS_EMBEDDING_MODEL": "text-embedding-3-large"}):
            _, memory_model = embeddings.make_memory_embedder()
        self.assertEqual(memory_model, "text-embedding-3-small")

    def test_corpus_model_independent_of_memory(self):
        # Setting the memory var must not move the corpus model, and vice versa.
        with patch.dict(os.environ, {"MEMORY_EMBEDDING_MODEL": "text-embedding-3-large"}):
            _, corpus_model = embeddings.make_corpus_embedder()
        self.assertEqual(corpus_model, "text-embedding-3-small")

    def test_base_url_passes_through_to_client(self):
        with patch.dict(os.environ, {"EMBEDDING_BASE_URL": "https://compat.example.com/v1"}):
            client, _ = embeddings.make_corpus_embedder()
        self.assertIn("compat.example.com", str(client.base_url))

    def test_base_url_unset_uses_openai_default(self):
        env = {k: v for k, v in os.environ.items() if k != "EMBEDDING_BASE_URL"}
        with patch.dict(os.environ, env, clear=True):
            client, _ = embeddings.make_corpus_embedder()
        self.assertIn("api.openai.com", str(client.base_url))


class EmbeddingCallSiteWiringTests(unittest.TestCase):
    """The ingest and query-side search call sites must move together."""

    def test_ingest_and_search_resolve_same_corpus_model(self):
        from ingestion import step5_ingest
        from agent.retrieval import search

        with patch.dict(os.environ, {"CORPUS_EMBEDDING_MODEL": "text-embedding-3-large"}):
            importlib.reload(step5_ingest)
            importlib.reload(search)
            self.assertEqual(step5_ingest.EMBED_MODEL, "text-embedding-3-large")
            self.assertEqual(search._EMBED_MODEL, "text-embedding-3-large")

    @classmethod
    def tearDownClass(cls):
        from ingestion import step5_ingest
        from agent.retrieval import search
        importlib.reload(step5_ingest)
        importlib.reload(search)


class MemoryEmbedderWiringTests(unittest.TestCase):
    """agent/graph.py's Semantic Memory store resolves MEMORY_EMBEDDING_MODEL, lazily."""

    def test_memory_embedder_ignores_corpus_var(self):
        from agent import graph
        graph._memory_embedder.cache_clear()
        with patch.dict(os.environ, {
            "MEMORY_EMBEDDING_MODEL": "text-embedding-3-large",
            "CORPUS_EMBEDDING_MODEL": "text-embedding-ada-002",
        }):
            _, model = graph._memory_embedder()
        self.assertEqual(model, "text-embedding-3-large")

    @classmethod
    def tearDownClass(cls):
        from agent import graph
        graph._memory_embedder.cache_clear()


if __name__ == "__main__":
    unittest.main()
