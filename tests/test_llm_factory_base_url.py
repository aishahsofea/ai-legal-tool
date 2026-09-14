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

    def test_api_key_omitted_when_unset(self):
        """Omitted, not None — ChatOpenAI must resolve OPENAI_API_KEY itself."""
        with patch.dict(os.environ, {}, clear=False), patch.object(llm_factory, "ChatOpenAI") as mock:
            os.environ.pop("CHAT_API_KEY", None)
            llm_factory.make_llm("gpt-4.1")
            self.assertNotIn("api_key", mock.call_args.kwargs)

    def test_empty_api_key_omitted(self):
        with patch.dict(os.environ, {"CHAT_API_KEY": ""}), patch.object(llm_factory, "ChatOpenAI") as mock:
            llm_factory.make_llm("gpt-4.1")
            self.assertNotIn("api_key", mock.call_args.kwargs)

    def test_api_key_forwarded(self):
        with patch.dict(os.environ, {"CHAT_API_KEY": "nebius-key"}), \
             patch.object(llm_factory, "ChatOpenAI") as mock:
            llm_factory.make_llm("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
            self.assertEqual(mock.call_args.kwargs["api_key"], "nebius-key")

    def test_api_key_ignored_by_anthropic(self):
        with patch.dict(os.environ, {"CHAT_API_KEY": "nebius-key"}), \
             patch.object(llm_factory, "ChatAnthropic") as mock:
            llm_factory.make_llm("claude-sonnet-4-6")
            self.assertNotIn("api_key", mock.call_args.kwargs)

    def test_embedding_client_unaffected_by_chat_key(self):
        """The whole point of a separate var: embeddings keep OPENAI_API_KEY."""
        from agent import embeddings
        with patch.dict(os.environ, {"CHAT_API_KEY": "nebius-key", "CHAT_BASE_URL": "https://example.invalid/v1/"}), \
             patch.object(embeddings, "OpenAI") as mock:
            embeddings.embedding_client()
            self.assertNotIn("api_key", mock.call_args.kwargs)
            self.assertIsNone(mock.call_args.kwargs["base_url"])

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

    def test_length_limit_is_wrapped(self):
        """openai raises this from its own parser with no status code. A reasoning
        model handed a json_schema can generate to the token ceiling without the
        request ever failing, which is a schema failure however it is spelled."""
        class LengthFinishReasonError(Exception):
            pass

        wrapped = self._wrapped(LengthFinishReasonError("length limit reached"))
        with self.assertRaises(llm_factory.StructuredOutputError) as ctx:
            wrapped.invoke("x")
        self.assertIn("synthesiser", str(ctx.exception))

    def test_content_filter_finish_is_wrapped(self):
        class ContentFilterFinishReasonError(Exception):
            pass

        wrapped = self._wrapped(ContentFilterFinishReasonError("filtered"))
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


class LengthFinishReasonError(Exception):
    """Matched by name in the factory. openai raises it from its own parser, so it
    carries no status code — a reasoning model handed a json_schema generated to
    the token ceiling and never produced the object."""


class JsonModeFallbackTests(unittest.TestCase):
    """The json_schema request is what provokes the runaway, so the retry drops it."""

    MESSAGES = [{"role": "system", "content": "judge"}, {"role": "user", "content": "{}"}]

    def _llm(self, primary_error, *, result=None, fallback_error=None):
        primary, fallback = Mock(), Mock()
        primary.invoke.side_effect = primary_error
        primary.ainvoke = AsyncMock(side_effect=primary_error)
        if fallback_error is not None:
            fallback.invoke.side_effect = fallback_error
            fallback.ainvoke = AsyncMock(side_effect=fallback_error)
        else:
            fallback.invoke.return_value = result
            fallback.ainvoke = AsyncMock(return_value=result)
        llm = Mock()
        llm.with_structured_output.side_effect = (
            lambda schema, **kwargs: fallback if kwargs.get("method") == "json_mode" else primary
        )
        return llm, primary, fallback

    def _wrapped(self, llm, model_name="nemotron-lightning"):
        return llm_factory.structured_llm(
            llm, _Schema, node="grounding_check", model_name=model_name
        )

    def test_length_failure_retries_in_json_mode(self):
        llm, _, fallback = self._llm(
            LengthFinishReasonError("8192"), result=_Schema(answer="ok")
        )
        self.assertEqual(self._wrapped(llm).invoke(self.MESSAGES).answer, "ok")

        retried = fallback.invoke.call_args.args[0]
        self.assertEqual(retried[:2], self.MESSAGES)
        self.assertIn("JSON Schema", retried[-1]["content"])
        self.assertIn("answer", retried[-1]["content"])

    def test_async_path_retries_too(self):
        import asyncio
        llm, _, fallback = self._llm(
            LengthFinishReasonError("8192"), result=_Schema(answer="ok")
        )
        result = asyncio.run(self._wrapped(llm).ainvoke(self.MESSAGES))
        self.assertEqual(result.answer, "ok")
        fallback.ainvoke.assert_awaited_once()

    def test_retry_failure_still_names_node_and_model(self):
        llm, _, _ = self._llm(
            LengthFinishReasonError("8192"),
            fallback_error=OutputParserException("still not json"),
        )
        with self.assertRaises(llm_factory.StructuredOutputError) as ctx:
            self._wrapped(llm).invoke(self.MESSAGES)
        self.assertIn("grounding_check", str(ctx.exception))
        self.assertIn("nemotron-lightning", str(ctx.exception))

    def test_transient_failure_does_not_retry(self):
        llm, _, fallback = self._llm(_Boom(429))
        with self.assertRaises(_Boom):
            self._wrapped(llm).invoke(self.MESSAGES)
        fallback.invoke.assert_not_called()

    def test_anthropic_builds_no_fallback(self):
        """Anthropic has no json_object response format, and its structured-output
        path does not trip the failure this retry exists for."""
        llm, _, fallback = self._llm(LengthFinishReasonError("8192"))
        with self.assertRaises(llm_factory.StructuredOutputError):
            self._wrapped(llm, model_name="claude-sonnet-4-6").invoke(self.MESSAGES)
        fallback.invoke.assert_not_called()
        self.assertEqual(llm.with_structured_output.call_count, 1)

    def test_non_message_input_is_not_rewritten(self):
        """The schema has to travel in the prompt, so a call this wrapper cannot
        rewrite falls back to the original error rather than retrying blind."""
        llm, _, fallback = self._llm(LengthFinishReasonError("8192"))
        with self.assertRaises(llm_factory.StructuredOutputError):
            self._wrapped(llm).invoke("a bare string")
        fallback.invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
