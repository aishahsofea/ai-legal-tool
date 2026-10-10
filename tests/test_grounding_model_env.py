import importlib
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import agent.llm_factory as llm_factory
from agent.nodes import grounding_check


class GroundingMaxTokensEnvTests(unittest.TestCase):
    def _reload_with(self, **overrides):
        # "" for unset: reloading re-runs load_dotenv(), which would restore a real .env value.
        env = {"GROUNDING_MODEL": "nvidia/Nemotron-3_5-Lightning", "GROUNDING_BASE_URL": "",
               "GROUNDING_API_KEY": "", "CHAT_BASE_URL": "", "CHAT_API_KEY": "",
               "GROUNDING_MAX_TOKENS": "", **overrides}
        with patch.dict(os.environ, env):
            with patch.object(llm_factory, "ChatOpenAI") as mock_openai:
                mock_openai.return_value.with_structured_output.return_value = MagicMock()
                importlib.reload(grounding_check)
                return mock_openai

    def test_max_tokens_read_from_env(self):
        mock_openai = self._reload_with(GROUNDING_MAX_TOKENS="24576")
        self.assertEqual(mock_openai.call_args.kwargs["max_tokens"], 24576)

    def test_max_tokens_unset_sends_nothing(self):
        mock_openai = self._reload_with()
        self.assertNotIn("max_tokens", mock_openai.call_args.kwargs)

    def test_json_mode_retry_uses_the_same_client(self):
        mock_openai = self._reload_with(GROUNDING_MAX_TOKENS="24576")
        mock_openai.assert_called_once()
        structured = mock_openai.return_value.with_structured_output
        self.assertIn("json_mode", [c.kwargs.get("method") for c in structured.call_args_list])

    @classmethod
    def tearDownClass(cls):
        importlib.reload(grounding_check)


if __name__ == "__main__":
    unittest.main()
