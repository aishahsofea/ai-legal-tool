"""
Provider-agnostic LLM factory.

Inspects the model name to select the correct LangChain provider:
  - claude-*  → ChatAnthropic (with prompt caching)
  - gemini-*  → ChatGoogleGenerativeAI
  - anything else → ChatOpenAI, aimed at CHAT_BASE_URL when one is set
"""
from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

load_dotenv()

logger = logging.getLogger(__name__)

# Filled in as each node builds its model. query_lifecycle stamps this onto the
# LangSmith run, because a mixed-provider turn is unreadable afterwards without it.
_NODE_MODELS: dict[str, str] = {}


def make_llm(model_name: str, temperature: float = 0, node: str | None = None):
    if node:
        _NODE_MODELS[node] = model_name
    if model_name.startswith("claude-"):
        return ChatAnthropic(model=model_name, temperature=temperature)
    if model_name.startswith("gemini-"):
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    # CHAT_BASE_URL aims the OpenAI-shaped client at any OpenAI-compatible
    # provider — the chat-side twin of EMBEDDING_BASE_URL. Unset keeps
    # api.openai.com, so an unconfigured deployment behaves exactly as before.
    kwargs = {}
    # CHAT_API_KEY has to be separate from OPENAI_API_KEY: agent/embeddings.py
    # authenticates with OPENAI_API_KEY too, and EMBEDDING_BASE_URL moves
    # independently. Overloading one key would send the chat provider's key to
    # api.openai.com on every embedding call. Omitted when unset so ChatOpenAI
    # resolves OPENAI_API_KEY itself, exactly as it did before.
    if chat_key := os.getenv("CHAT_API_KEY"):
        kwargs["api_key"] = chat_key
    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        base_url=os.getenv("CHAT_BASE_URL") or None,
        **kwargs,
    )


def node_models() -> dict[str, str]:
    """Model each node bound at import, keyed by node name."""
    return dict(_NODE_MODELS)


class StructuredOutputError(RuntimeError):
    """A provider could not honour a node's output schema."""


# json.JSONDecodeError covers a provider that returns prose where JSON was asked for.
_SCHEMA_ERRORS = (ValidationError, OutputParserException, json.JSONDecodeError)


# openai raises these from its own schema parser, not the transport, so they carry
# no status code. Matched by name to keep the openai import out of this file.
# LengthFinishReasonError is the one a served open-weights model hits in practice:
# handed a json_schema it can generate until it hits the token ceiling, and the
# request never fails — it just never produces the object.
_SCHEMA_ERROR_NAMES = {"LengthFinishReasonError", "ContentFilterFinishReasonError"}


def _is_schema_failure(exc: BaseException) -> bool:
    if isinstance(exc, _SCHEMA_ERRORS):
        return True
    if type(exc).__name__ in _SCHEMA_ERROR_NAMES:
        return True
    # openai.BadRequestError / UnprocessableEntityError — a provider rejecting the
    # response_format payload outright. Matched by status so this file needs no
    # openai import and no list of SDK exception classes to keep current.
    return getattr(exc, "status_code", None) in (400, 422)


# Appended to the messages on the json_mode retry. LangChain's json_mode sends
# `response_format={"type": "json_object"}` and nothing else, so the shape has to
# travel in the prompt; OpenAI-compatible endpoints also require the word "json"
# to appear in the messages before they accept that response_format at all.
_JSON_MODE_INSTRUCTION = (
    "Return one JSON object and nothing else — no prose, no markdown fence. "
    "It must validate against this JSON Schema:\n{schema}"
)


def _json_mode_available(model_name: str) -> bool:
    # Anthropic and Google have no json_object response format. Their own
    # structured-output paths do not trip the failure this retry exists for.
    return not model_name.startswith(("claude-", "gemini-"))


def _schema_prompt(schema) -> str | None:
    dump = getattr(schema, "model_json_schema", None)
    if dump is None:
        return None
    try:
        return json.dumps(dump(), ensure_ascii=False)
    except Exception:
        return None


class _StructuredLLM:
    """with_structured_output, wrapped so a provider that cannot honour the schema
    retries once without it, then names the node and the model instead of raising
    a bare schema error.

    OpenAI-compatible is not OpenAI-identical: an OpenAI-shaped endpoint can accept
    the request and still hand back prose. contextualize and grounding_check fail
    open on any exception, so this message is the only place an operator learns
    which node broke and which model broke it. Transient failures — rate limits,
    auth, timeouts — pass through untouched so upstream retry logic still sees
    their own shape.

    The retry drops to `method="json_mode"` because the `json_schema` request is
    itself what provokes the failure on a served reasoning model: handed a schema
    it can reason to the token ceiling and never emit the object (issue #85).
    json_mode asks for a plain JSON object and carries the shape in the prompt,
    which does not set that off.
    """

    def __init__(self, llm, schema, node: str, model_name: str):
        self._runnable = llm.with_structured_output(schema)
        self._node = node
        self._model_name = model_name
        self._schema_text = _schema_prompt(schema)
        self._fallback = (
            llm.with_structured_output(schema, method="json_mode")
            if _json_mode_available(model_name) and self._schema_text
            else None
        )

    def _wrap(self, exc: Exception):
        return StructuredOutputError(
            f"{self._node}: model {self._model_name!r} did not return output matching "
            f"its schema ({type(exc).__name__}: {exc})"
        )

    def _retry_args(self, args: tuple) -> list | None:
        """The same call with the schema moved into the prompt, or None when this
        call shape cannot be rewritten."""
        if self._fallback is None or not args:
            return None
        messages = args[0]
        if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
            return None
        instruction = _JSON_MODE_INSTRUCTION.format(schema=self._schema_text)
        return [*messages, {"role": "user", "content": instruction}]

    def _log_retry(self, exc: Exception) -> None:
        logger.warning(
            "%s: model %r failed json_schema (%s); retrying in json_mode",
            self._node,
            self._model_name,
            type(exc).__name__,
        )

    def invoke(self, *args, **kwargs):
        try:
            return self._runnable.invoke(*args, **kwargs)
        except Exception as exc:
            if not _is_schema_failure(exc):
                raise
            retry_args = self._retry_args(args)
            if retry_args is None:
                raise self._wrap(exc) from exc
            self._log_retry(exc)
            try:
                return self._fallback.invoke(retry_args, **kwargs)
            except Exception as retry_exc:
                if _is_schema_failure(retry_exc):
                    raise self._wrap(retry_exc) from retry_exc
                raise

    async def ainvoke(self, *args, **kwargs):
        try:
            return await self._runnable.ainvoke(*args, **kwargs)
        except Exception as exc:
            if not _is_schema_failure(exc):
                raise
            retry_args = self._retry_args(args)
            if retry_args is None:
                raise self._wrap(exc) from exc
            self._log_retry(exc)
            try:
                return await self._fallback.ainvoke(retry_args, **kwargs)
            except Exception as retry_exc:
                if _is_schema_failure(retry_exc):
                    raise self._wrap(retry_exc) from retry_exc
                raise

    def __getattr__(self, name):
        return getattr(self._runnable, name)


def structured_llm(llm, schema, *, node: str, model_name: str):
    return _StructuredLLM(llm, schema, node, model_name)


def system_content(text: str, model_name: str):
    """Return system message content in the correct format for the provider."""
    if model_name.startswith("claude-"):
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
    return text
