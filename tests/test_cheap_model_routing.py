import os
import unittest
from unittest.mock import patch

from agent import llm_factory
from agent.nodes import synthesiser
from agent.retrieval import agent as retrieval_agent

_ON = {
    "CHEAP_MODEL_ROUTING": "on",
    "CHEAP_MODEL_THRESHOLD": "0.9",
    "SYNTHESISER_CHEAP_MODEL": "cheap-synth",
    "RETRIEVAL_AGENT_CHEAP_MODEL": "cheap-retr",
}
_SIMPLE = {"complexity": "simple", "complexity_probability": 0.95, "retry_count": 0}


def _env(**overrides):
    env = {**_ON, **overrides}
    return patch.dict(os.environ, {k: v for k, v in env.items() if v is not None}, clear=False)


class UseCheapModelTests(unittest.TestCase):
    def test_confident_simple_first_pass_is_cheap(self):
        with _env():
            self.assertTrue(llm_factory.use_cheap_model(_SIMPLE))

    def test_flag_off_is_strong(self):
        with _env(CHEAP_MODEL_ROUTING="off"):
            self.assertFalse(llm_factory.use_cheap_model(_SIMPLE))

    def test_flag_unset_is_strong(self):
        with _env(), patch.dict(os.environ):
            os.environ.pop("CHEAP_MODEL_ROUTING")
            self.assertFalse(llm_factory.use_cheap_model(_SIMPLE))

    def test_jev_error_or_llm_router_leaves_fields_unset_and_is_strong(self):
        with _env():
            self.assertFalse(llm_factory.use_cheap_model({"retry_count": 0}))

    def test_multi_provision_is_strong(self):
        with _env():
            self.assertFalse(llm_factory.use_cheap_model({**_SIMPLE, "complexity": "multi_provision"}))

    def test_low_probability_is_strong(self):
        with _env():
            self.assertFalse(llm_factory.use_cheap_model({**_SIMPLE, "complexity_probability": 0.89}))

    def test_probability_at_threshold_is_cheap(self):
        with _env():
            self.assertTrue(llm_factory.use_cheap_model({**_SIMPLE, "complexity_probability": 0.9}))

    def test_retry_is_strong(self):
        with _env():
            self.assertFalse(llm_factory.use_cheap_model({**_SIMPLE, "retry_count": 1}))

    def test_unset_threshold_takes_default(self):
        for raw in (None, "  "):
            with self.subTest(raw), _env(CHEAP_MODEL_THRESHOLD=raw):
                self.assertFalse(llm_factory.use_cheap_model({**_SIMPLE, "complexity_probability": 0.89}))
                self.assertTrue(llm_factory.use_cheap_model({**_SIMPLE, "complexity_probability": 0.9}))

    def test_invalid_threshold_takes_strictest(self):
        for bad in ("abc", "0", "-1", "1.5"):
            with self.subTest(bad), _env(CHEAP_MODEL_THRESHOLD=bad):
                self.assertFalse(llm_factory.use_cheap_model({**_SIMPLE, "complexity_probability": 0.99}))

    def test_cheap_name_needs_a_configured_model(self):
        with _env(SYNTHESISER_CHEAP_MODEL=""):
            self.assertIsNone(llm_factory.cheap_model_name(_SIMPLE, "SYNTHESISER_CHEAP_MODEL"))
        with _env():
            self.assertEqual(llm_factory.cheap_model_name(_SIMPLE, "SYNTHESISER_CHEAP_MODEL"), "cheap-synth")


class SynthesiserSelectionTests(unittest.TestCase):
    def test_cheap_turn_selects_cheap_model(self):
        with _env(), patch.object(synthesiser, "_make_synthesiser_llm"), \
             patch.object(synthesiser, "structured_llm", return_value="cheap-llm"):
            synthesiser._cheap_structured_llm.cache_clear()
            self.assertEqual(synthesiser._select_llm(_SIMPLE), ("cheap-llm", "cheap-synth"))

    def test_retry_keeps_strong_model(self):
        with _env():
            self.assertEqual(
                synthesiser._select_llm({**_SIMPLE, "retry_count": 1}),
                (synthesiser._structured_llm, synthesiser._MODEL),
            )

    def test_system_prompt_salt_follows_the_chosen_model(self):
        state = {"query": "q", "retrieved_chunks": [], "history": []}
        ultra = synthesiser._build_messages(state, "nemotron-3-ultra")[0]["content"]
        cheap = synthesiser._build_messages(state, "cheap-synth")[0]["content"]
        self.assertTrue(ultra.startswith("[request "))
        self.assertFalse(cheap.startswith("[request "))


class RetrievalSelectionTests(unittest.TestCase):
    def test_cheap_turn_selects_cheap_model(self):
        with _env():
            self.assertEqual(retrieval_agent._retrieval_model_name(_SIMPLE), "cheap-retr")

    def test_retry_and_missing_state_keep_strong_model(self):
        with _env(RETRIEVAL_AGENT_MODEL="strong"):
            self.assertEqual(retrieval_agent._retrieval_model_name({**_SIMPLE, "retry_count": 1}), "strong")
            self.assertEqual(retrieval_agent._retrieval_model_name(), "strong")

    def test_flag_off_keeps_strong_model(self):
        with _env(CHEAP_MODEL_ROUTING="off", RETRIEVAL_AGENT_MODEL="strong"):
            self.assertEqual(retrieval_agent._retrieval_model_name(_SIMPLE), "strong")


if __name__ == "__main__":
    unittest.main()
