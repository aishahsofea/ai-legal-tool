"""Which evals exercise each graph node, for the eval dashboard's workflow map."""
from typing import NotRequired, TypedDict


class NodeEval(TypedDict):
    set: NotRequired[str]  # an EVAL_SETS key: runnable from the dashboard
    script: NotRequired[str]  # a manual instrument under evals/


def _set(name: str) -> NodeEval:
    return {"set": name}


def _script(path: str) -> NodeEval:
    return {"script": path}


# Lives in api/, not agent/: it names eval sets, and agent/ must not import api/.
NODE_EVALS: dict[str, list[NodeEval]] = {
    "start_turn": [],
    "router": [_set("routing")],
    "escalate": [],
    "clarify": [],
    "contextualize": [_script("evals/history_budget.py")],
    "recall_conversational": [],
    "conversational": [],
    "retriever": [_script("evals/retrieval_recall.py")],
    "recall": [_script("evals/semantic_memory.py")],
    "synthesiser": [_set("end_to_end")],
    "citation_validator": [_set("end_to_end")],
    "grounding_check": [_set("grounding")],
    "currency_check": [_set("end_to_end"), _script("evals/currency_split.py")],
    "supervisor": [],
    "increment_retry": [],
    "retry_retrieve": [],
    "record_turn": [],
}
