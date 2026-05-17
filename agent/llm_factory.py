"""
Provider-agnostic LLM factory.

Inspects the model name to select the correct LangChain provider:
  - claude-*  → ChatAnthropic (with prompt caching)
  - gemini-*  → ChatGoogleGenerativeAI
  - anything else → ChatOpenAI
"""
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


def make_llm(model_name: str):
    if model_name.startswith("claude-"):
        return ChatAnthropic(model=model_name, temperature=0)
    if model_name.startswith("gemini-"):
        return ChatGoogleGenerativeAI(model=model_name, temperature=0)
    return ChatOpenAI(model=model_name, temperature=0)


def system_content(text: str, model_name: str):
    """Return system message content in the correct format for the provider."""
    if model_name.startswith("claude-"):
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
    return text
