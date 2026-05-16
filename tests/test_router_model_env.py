import importlib
import os
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from agent.nodes import router


class RouterModelEnvTests(unittest.TestCase):
    def test_router_model_defaults_to_sonnet(self):
        env = {k: v for k, v in os.environ.items() if k != "ROUTER_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            with patch("langchain_anthropic.ChatAnthropic") as mock_cls:
                mock_cls.return_value.with_structured_output.return_value = MagicMock()
                importlib.reload(router)
                mock_cls.assert_called_once_with(model="claude-sonnet-4-6", temperature=0)

    def test_router_model_reads_env_var(self):
        with patch.dict(os.environ, {"ROUTER_MODEL": "claude-haiku-4-5-20251001"}):
            with patch("langchain_anthropic.ChatAnthropic") as mock_cls:
                mock_cls.return_value.with_structured_output.return_value = MagicMock()
                importlib.reload(router)
                mock_cls.assert_called_once_with(model="claude-haiku-4-5-20251001", temperature=0)

    @classmethod
    def tearDownClass(cls):
        importlib.reload(router)


if __name__ == "__main__":
    unittest.main()
