import importlib
import os
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import agent.llm_factory as llm_factory
from agent.nodes import synthesiser


class SynthesiserModelEnvTests(unittest.TestCase):
    def test_synthesiser_defaults_to_gpt_4_1(self):
        env = {k: v for k, v in os.environ.items() if k != "SYNTHESISER_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(llm_factory, "ChatOpenAI") as mock_openai:
                with patch.object(llm_factory, "ChatAnthropic") as mock_anthropic:
                    mock_openai.return_value.with_structured_output.return_value = MagicMock()
                    importlib.reload(synthesiser)
                    mock_openai.assert_called_once_with(model="gpt-4.1", temperature=0)
                    mock_anthropic.assert_not_called()

    def test_synthesiser_uses_anthropic_for_claude_model(self):
        with patch.dict(os.environ, {"SYNTHESISER_MODEL": "claude-haiku-4-5-20251001"}):
            with patch.object(llm_factory, "ChatAnthropic") as mock_anthropic:
                with patch.object(llm_factory, "ChatOpenAI") as mock_openai:
                    mock_anthropic.return_value.with_structured_output.return_value = MagicMock()
                    importlib.reload(synthesiser)
                    mock_anthropic.assert_called_once_with(model="claude-haiku-4-5-20251001", temperature=0)
                    mock_openai.assert_not_called()

    def test_synthesiser_uses_openai_for_gpt_model(self):
        with patch.dict(os.environ, {"SYNTHESISER_MODEL": "gpt-4o"}):
            with patch.object(llm_factory, "ChatOpenAI") as mock_openai:
                with patch.object(llm_factory, "ChatAnthropic") as mock_anthropic:
                    mock_openai.return_value.with_structured_output.return_value = MagicMock()
                    importlib.reload(synthesiser)
                    mock_openai.assert_called_once_with(model="gpt-4o", temperature=0)
                    mock_anthropic.assert_not_called()

    @classmethod
    def tearDownClass(cls):
        importlib.reload(synthesiser)


if __name__ == "__main__":
    unittest.main()
