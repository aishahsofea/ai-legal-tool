import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError

from agent import llm_factory


class _Schema(BaseModel):
    answer: str


class ChatBaseUrlTests(unittest.TestCase):
    def test_unset_base_url_is_none(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(llm_factory, "ChatOpenAI") as mock:
            os.environ.pop("CHAT_BASE_URL", None)
            llm_factory.make_llm("gpt-4.1")
            self.assertIsNone(mock.call_args.kwargs["base_url"])

    def test_empty_base_url_is_none(self):
        with patch.dict(os.environ, {"CHAT_BASE_URL": ""}), patch.object(llm_factory, "ChatOpenAI") as mock:
            llm_factory.make_llm("gpt-4.1")
            self.assertIsNone(mock.call_args.kwargs["base_url"])

    def test_base_url_forwarded(self):
        url = "https://api.studio.nebius.com/v1/"
        with patch.dict(os.environ, {"CHAT_BASE_URL": url}), patch.object(llm_factory, "ChatOpenAI") as mock:
            llm_factory.make_llm("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
            self.assertEqual(mock.call_args.kwargs["base_url"], url)
            self.assertEqual(mock.call_args.kwargs["model"], "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")

    def test_base_url_ignored_by_anthropic(self):
        with patch.dict(os.environ, {"CHAT_BASE_URL": "https://example.invalid/v1/"}), \
             patch.object(llm_factory, "ChatAnthropic") as mock:
            llm_factory.make_llm("claude-sonnet-4-6")
            self.assertNotIn("base_url", mock.call_args.kwargs)

    def test_base_url_ignored_by_gemini(self):
        with patch.dict(os.environ, {"CHAT_BASE_URL": "https://example.invalid/v1/"}), \
             patch.object(llm_factory, "ChatGoogleGenerativeAI") as mock:
            llm_factory.make_llm("gemini-1.5-pro")
            self.assertNotIn("base_url", mock.call_args.kwargs)

    def test_prompt_caching_stays_anthropic_only(self):
        nemotron = llm_factory.system_content("prompt", "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B")
        self.assertEqual(nemotron, "prompt")
        claude = llm_factory.system_content("prompt", "claude-sonnet-4-6")
        self.assertEqual(claude[0]["cache_control"], {"type": "ephemeral"})


class NodeModelRegistryTests(unittest.TestCase):
    def test_node_name_recorded(self):
        with patch.object(llm_factory, "ChatOpenAI"):
            llm_factory.make_llm("gpt-4.1", node="test_node")
        self.assertEqual(llm_factory.node_models()["test_node"], "gpt-4.1")

    def test_registry_copy_is_not_live(self):
        with patch.object(llm_factory, "ChatOpenAI"):
            llm_factory.make_llm("gpt-4.1", node="test_node_copy")
        snapshot = llm_factory.node_models()
        snapshot["test_node_copy"] = "mutated"
        self.assertEqual(llm_factory.node_models()["test_node_copy"], "gpt-4.1")

    def test_every_graph_node_registers_a_model(self):
        """The trace criterion in #59 is worthless if a node forgets its label."""
        import agent.graph  # noqa: F401  — imports every node module
        registered = llm_factory.node_models()
        for node in ("router", "contextualize", "synthesiser", "grounding_check", "conversational"):
            self.assertIn(node, registered)


class _Boom(Exception):
    def __init__(self, status_code):
        super().__init__("provider said no")
        self.status_code = status_code


class StructuredOutputErrorTests(unittest.TestCase):
    def _wrapped(self, error):
        llm = Mock()
        inner = Mock()
        inner.invoke.side_effect = error
        inner.ainvoke = AsyncMock(side_effect=error)
        llm.with_structured_output.return_value = inner
        return llm_factory.structured_llm(llm, _Schema, node="synthesiser", model_name="nemotron-super")

    def _schema_error(self):
        try:
            _Schema(answer=None)
        except ValidationError as exc:
            return exc

    def test_validation_error_names_node_and_model(self):
        wrapped = self._wrapped(self._schema_error())
        with self.assertRaises(llm_factory.StructuredOutputError) as ctx:
            wrapped.invoke("x")
        self.assertIn("synthesiser", str(ctx.exception))
        self.assertIn("nemotron-super", str(ctx.exception))

    def test_parser_error_is_wrapped(self):
        wrapped = self._wrapped(OutputParserException("not json"))
        with self.assertRaises(llm_factory.StructuredOutputError):
            wrapped.invoke("x")

    def test_json_decode_error_is_wrapped(self):
        wrapped = self._wrapped(json.JSONDecodeError("bad", "doc", 0))
        with self.assertRaises(llm_factory.StructuredOutputError):
            wrapped.invoke("x")

    def test_rejected_request_is_wrapped(self):
        wrapped = self._wrapped(_Boom(400))
        with self.assertRaises(llm_factory.StructuredOutputError):
            wrapped.invoke("x")

    def test_transient_error_passes_through(self):
        """A 429 is not a schema failure; upstream retry logic needs its own shape."""
        wrapped = self._wrapped(_Boom(429))
        with self.assertRaises(_Boom):
            wrapped.invoke("x")

    def test_async_path_wrapped(self):
        import asyncio
        wrapped = self._wrapped(self._schema_error())
        with self.assertRaises(llm_factory.StructuredOutputError) as ctx:
            asyncio.run(wrapped.ainvoke("x"))
        self.assertIn("synthesiser", str(ctx.exception))

    def test_success_passes_result_through(self):
        llm = Mock()
        inner = Mock()
        inner.invoke.return_value = _Schema(answer="ok")
        llm.with_structured_output.return_value = inner
        wrapped = llm_factory.structured_llm(llm, _Schema, node="router", model_name="gpt-4.1")
        self.assertEqual(wrapped.invoke("x").answer, "ok")

    def test_other_runnable_attributes_delegate(self):
        llm = Mock()
        inner = Mock()
        inner.some_runnable_method.return_value = "delegated"
        llm.with_structured_output.return_value = inner
        wrapped = llm_factory.structured_llm(llm, _Schema, node="router", model_name="gpt-4.1")
        self.assertEqual(wrapped.some_runnable_method(), "delegated")


if __name__ == "__main__":
    unittest.main()
