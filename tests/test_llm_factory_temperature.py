import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from agent import llm_factory


class LlmFactoryTemperatureTests(unittest.TestCase):
    def test_defaults_to_zero_for_openai(self):
        with patch.object(llm_factory, "ChatOpenAI") as mock:
            llm_factory.make_llm("gpt-4.1")
            self.assertEqual(mock.call_args.kwargs["temperature"], 0)

    def test_forwards_temperature_for_openai(self):
        with patch.object(llm_factory, "ChatOpenAI") as mock:
            llm_factory.make_llm("gpt-4.1-mini", temperature=0.7)
            self.assertEqual(mock.call_args.kwargs["temperature"], 0.7)

    def test_forwards_temperature_for_anthropic(self):
        with patch.object(llm_factory, "ChatAnthropic") as mock:
            llm_factory.make_llm("claude-haiku-4-5-20251001", temperature=0.7)
            self.assertEqual(mock.call_args.kwargs["temperature"], 0.7)

    def test_forwards_temperature_for_gemini(self):
        with patch.object(llm_factory, "ChatGoogleGenerativeAI") as mock:
            llm_factory.make_llm("gemini-1.5-pro", temperature=0.7)
            self.assertEqual(mock.call_args.kwargs["temperature"], 0.7)


if __name__ == "__main__":
    unittest.main()
