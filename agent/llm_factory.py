"""
Provider-agnostic LLM factory.

Inspects the model name to select the correct LangChain provider:
  - claude-*  → ChatAnthropic (with prompt caching)
  - gemini-*  → ChatGoogleGenerativeAI
  - anything else → ChatOpenAI, aimed at CHAT_BASE_URL when one is set
"""
from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

load_dotenv()

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
    # Auth still rides on OPENAI_API_KEY; point that at the other provider's key.
    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        base_url=os.getenv("CHAT_BASE_URL") or None,
    )


def node_models() -> dict[str, str]:
    """Model each node bound at import, keyed by node name."""
    return dict(_NODE_MODELS)


class StructuredOutputError(RuntimeError):
    """A provider could not honour a node's output schema."""


# json.JSONDecodeError covers a provider that returns prose where JSON was asked for.
_SCHEMA_ERRORS = (ValidationError, OutputParserException, json.JSONDecodeError)


def _is_schema_failure(exc: BaseException) -> bool:
    if isinstance(exc, _SCHEMA_ERRORS):
        return True
    # openai.BadRequestError / UnprocessableEntityError — a provider rejecting the
    # response_format payload outright. Matched by status so this file needs no
    # openai import and no list of SDK exception classes to keep current.
    return getattr(exc, "status_code", None) in (400, 422)


class _StructuredLLM:
    """with_structured_output, wrapped so a provider that cannot honour the schema
    names the node and the model instead of raising a bare schema error.

    OpenAI-compatible is not OpenAI-identical: an OpenAI-shaped endpoint can accept
    the request and still hand back prose. contextualize and grounding_check fail
    open on any exception, so this message is the only place an operator learns
    which node broke and which model broke it. Transient failures — rate limits,
    auth, timeouts — pass through untouched so upstream retry logic still sees
    their own shape.
    """

    def __init__(self, runnable, node: str, model_name: str):
        self._runnable = runnable
        self._node = node
        self._model_name = model_name

    def _wrap(self, exc: Exception):
        return StructuredOutputError(
            f"{self._node}: model {self._model_name!r} did not return output matching "
            f"its schema ({type(exc).__name__}: {exc})"
        )

    def invoke(self, *args, **kwargs):
        try:
            return self._runnable.invoke(*args, **kwargs)
        except Exception as exc:
            if _is_schema_failure(exc):
                raise self._wrap(exc) from exc
            raise

    async def ainvoke(self, *args, **kwargs):
        try:
            return await self._runnable.ainvoke(*args, **kwargs)
        except Exception as exc:
            if _is_schema_failure(exc):
                raise self._wrap(exc) from exc
            raise

    def __getattr__(self, name):
        return getattr(self._runnable, name)


def structured_llm(llm, schema, *, node: str, model_name: str):
    return _StructuredLLM(llm.with_structured_output(schema), node, model_name)


def system_content(text: str, model_name: str):
    """Return system message content in the correct format for the provider."""
    if model_name.startswith("claude-"):
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
    return text
