import importlib
import os
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.nodes import synthesiser


class SynthesiserModelEnvTests(unittest.TestCase):
    def test_synthesiser_model_defaults_to_sonnet(self):
        env = {k: v for k, v in os.environ.items() if k != "SYNTHESISER_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            with patch("langchain_anthropic.ChatAnthropic") as mock_cls:
                mock_cls.return_value.with_structured_output.return_value = MagicMock()
                importlib.reload(synthesiser)
                mock_cls.assert_called_once_with(model="claude-sonnet-4-6", temperature=0)

    def test_synthesiser_model_reads_env_var(self):
        with patch.dict(os.environ, {"SYNTHESISER_MODEL": "claude-haiku-4-5-20251001"}):
            with patch("langchain_anthropic.ChatAnthropic") as mock_cls:
                mock_cls.return_value.with_structured_output.return_value = MagicMock()
                importlib.reload(synthesiser)
                mock_cls.assert_called_once_with(model="claude-haiku-4-5-20251001", temperature=0)

    @classmethod
    def tearDownClass(cls):
        importlib.reload(synthesiser)


if __name__ == "__main__":
    unittest.main()
