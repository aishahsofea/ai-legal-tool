from dataclasses import dataclass
from typing import Literal

NodeKind = Literal["llm", "deterministic", "control"]


@dataclass(frozen=True)
class NodeMeta:
    kind: NodeKind
    description: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    rank: int  # row, top to bottom
    lane: int  # column, left to right


# Declares what LangGraph cannot report. reads/writes are hand-kept: tests check field names, not accuracy.
NODE_META: dict[str, NodeMeta] = {
    "start_turn": NodeMeta(
        "control",
        "Resets per-turn fields so turn N does not inherit turn N-1. history is kept.",
        (),
        (
            "query_type", "standalone_query", "response_language", "retrieved_chunks",
            "draft_response", "citations", "violations", "evidence_violations",
            "recalled_memory", "retrieval_feedback", "tool_trace", "reference_trace",
            "reference_metrics", "commentary", "grounding_metrics", "currency_labels",
            "final_response", "retry_count", "clarifying_question", "clarified",
        ),
        0, 2,
    ),
    "router": NodeMeta(
        "llm",
        "Regex escalation check first (no LLM). Otherwise an LLM classifies the query and detects its language.",
        ("query", "history"),
        ("query_type", "response_language", "clarifying_question"),
        1, 2,
    ),
    "escalate": NodeMeta(
        "deterministic",
        "Fixed escalation text. No LLM, no retrieval.",
        (),
        ("final_response",),
        2, 0,
    ),
    "clarify": NodeMeta(
        "control",
        "interrupt() pauses for the user, merges the answer into query, then back to router. Max once per turn.",
        ("query", "clarifying_question"),
        ("query", "clarifying_question", "clarified"),
        2, 1,
    ),
    "contextualize": NodeMeta(
        "llm",
        "Rewrites a follow-up into a standalone query using history.",
        ("query", "history"),
        ("standalone_query",),
        2, 2,
    ),
    "recall_conversational": NodeMeta(
        "deterministic",
        "Same code as recall, feeding small talk. Reads remembered user preferences. Fails open.",
        ("query", "standalone_query"),
        ("recalled_memory",),
        2, 4,
    ),
    "conversational": NodeMeta(
        "llm",
        "Small-talk answer, no retrieval.",
        ("query", "history", "recalled_memory", "response_language"),
        ("draft_response", "final_response"),
        3, 4,
    ),
    "retriever": NodeMeta(
        "deterministic",
        "Searches chunks. Becomes a ReAct tool-calling LLM agent when AGENTIC_RETRIEVAL is on; same node id and edges.",
        ("query", "standalone_query", "query_type", "retrieval_feedback"),
        ("retrieved_chunks", "tool_trace", "reference_trace", "reference_metrics", "commentary"),
        3, 2,
    ),
    "recall": NodeMeta(
        "deterministic",
        "Reads remembered user preferences. Fails open.",
        ("query", "standalone_query"),
        ("recalled_memory",),
        4, 2,
    ),
    "synthesiser": NodeMeta(
        "llm",
        "Drafts the answer and builds citations from retrieved chunks.",
        ("query", "retrieved_chunks", "response_language", "recalled_memory", "commentary", "history"),
        ("draft_response", "citations"),
        5, 2,
    ),
    "citation_validator": NodeMeta(
        "deterministic",
        "Pure Python. Checks each cited act and section exists in the retrieved chunks.",
        ("citations", "retrieved_chunks", "draft_response", "violations", "evidence_violations"),
        ("violations", "evidence_violations"),
        6, 2,
    ),
    "grounding_check": NodeMeta(
        "llm",
        "LLM judge. Does the cited text support each claim? Fails open, counted in grounding_metrics.",
        ("draft_response", "citations", "retrieved_chunks", "violations", "evidence_violations", "grounding_metrics"),
        ("violations", "evidence_violations", "grounding_metrics"),
        7, 2,
    ),
    "currency_check": NodeMeta(
        "deterministic",
        "Labels each cited Act repealed, superseded or current_as_indexed from local data.",
        ("citations", "retrieved_chunks"),
        ("currency_labels",),
        8, 2,
    ),
    "supervisor": NodeMeta(
        "deterministic",
        "Regex policy rules (advice phrases, citation present, disclaimer). Routes to retry or finish.",
        ("draft_response", "violations", "retry_count"),
        ("violations",),
        9, 2,
    ),
    "increment_retry": NodeMeta(
        "control",
        "Re-draft path. Bumps retry_count and clears findings; keeps the same chunks.",
        ("retry_count",),
        ("retry_count", "violations", "evidence_violations", "retrieval_feedback"),
        9, 1,
    ),
    "retry_retrieve": NodeMeta(
        "control",
        "Re-retrieve path for an evidence gap. Builds feedback for the retriever.",
        ("retry_count", "evidence_violations"),
        (
            "retry_count", "violations", "evidence_violations", "retrieval_feedback",
            "reference_trace", "reference_metrics", "commentary",
        ),
        9, 3,
    ),
    "record_turn": NodeMeta(
        "control",
        "Computes the delivered response (safe fallback if violations remain) and appends the turn to history.",
        ("query", "citations", "violations", "draft_response"),
        ("final_response", "history", "citations"),
        10, 2,
    ),
}

# Keyed by (source, target) as LangGraph reports them, so the router's END branch is "escalate".
EDGE_LABELS: dict[tuple[str, str], str] = {
    ("router", "escalate"): "escalate",
    ("router", "recall_conversational"): "conversational",
    ("router", "contextualize"): "legal query",
    ("router", "clarify"): "clarify",
    ("supervisor", "increment_retry"): "draft violation",
    ("supervisor", "retry_retrieve"): "evidence gap",
    ("supervisor", "record_turn"): "pass or retries used up",
}
