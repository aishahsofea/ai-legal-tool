import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent

# agent/retrieval/search.py builds its client at import, so reloading it needs a key.
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
    """Every writer into the `chunks` table must move with query-side search."""

    def test_ingest_and_search_resolve_same_corpus_model(self):
        from ingestion import step5_ingest
        from agent.retrieval import search

        with patch.dict(os.environ, {"CORPUS_EMBEDDING_MODEL": "text-embedding-3-large"}):
            importlib.reload(step5_ingest)
            importlib.reload(search)
            self.assertEqual(step5_ingest.EMBED_MODEL, "text-embedding-3-large")
            self.assertEqual(search._EMBED_MODEL, "text-embedding-3-large")

    def test_eval_seeder_resolves_same_corpus_model(self):
        # The eval corpus is queried through search.py, so a seeder that drifts
        # makes every eval score a retrieval it never actually configured.
        from evals import seed_test_corpus

        with patch.dict(os.environ, {"CORPUS_EMBEDDING_MODEL": "text-embedding-3-large"}):
            importlib.reload(seed_test_corpus)
            self.assertEqual(seed_test_corpus.EMBED_MODEL, "text-embedding-3-large")

    def test_operator_cli_defaults_follow_corpus_model(self):
        from corpus import cli

        with patch.dict(os.environ, {"CORPUS_EMBEDDING_MODEL": "text-embedding-3-large"}):
            parser = cli.build_parser()
        ingest = parser.parse_args(["ingest", "--bundle", "b.json", "--extraction-id", "e1"])
        rollout = parser.parse_args(["rollout"])
        self.assertEqual(ingest.embedding_model, "text-embedding-3-large")
        self.assertEqual(rollout.embedding_model, "text-embedding-3-large")

    def test_rollout_default_tracks_factory_default(self):
        import inspect

        from agent.embeddings import DEFAULT_EMBEDDING_MODEL
        from corpus.rollout import rollout_corpus

        default = inspect.signature(rollout_corpus).parameters["embedding_model"].default
        self.assertEqual(default, DEFAULT_EMBEDDING_MODEL)

    @classmethod
    def tearDownClass(cls):
        from ingestion import step5_ingest
        from agent.retrieval import search
        from evals import seed_test_corpus
        importlib.reload(step5_ingest)
        importlib.reload(search)
        importlib.reload(seed_test_corpus)


class LazyClientTests(unittest.TestCase):
    def test_ingest_module_imports_without_an_api_key(self):
        # run.py imports step5_ingest lazily, but a module that builds an OpenAI
        # client at import time makes the module unimportable without a key.
        script = (
            "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
            "import ingestion.step5_ingest as m; print(m.EMBED_MODEL)"
        )
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr[-600:])
        self.assertEqual(result.stdout.strip(), "text-embedding-3-small")

    def test_client_kwargs_reach_the_openai_client(self):
        # corpus/rollout.py depends on max_retries=0 for an exact dollar cap.
        client = embeddings.embedding_client(max_retries=0)
        self.assertEqual(client.max_retries, 0)


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
