from contextlib import ExitStack
from unittest.mock import patch


def patch_async_happy_path(stack: ExitStack, asynthesiser) -> None:
    """Topical happy path for the ASYNC (astream) execution: classify topical,
    retrieve nothing, pass every check. synthesiser is supplied by the caller so a
    test can make it block. Sync-only nodes (retriever/citation/supervisor) run
    their sync func in a threadpool during astream, so they are patched by base name."""
    stack.enter_context(patch("agent.graph.arouter_node", side_effect=lambda s: {"query_type": "topical"}))
    stack.enter_context(patch("agent.graph.acontextualize_node", side_effect=lambda s: {"standalone_query": ""}))
    stack.enter_context(patch("agent.graph.agrounding_check_node", side_effect=lambda s: {"violations": []}))
    stack.enter_context(patch("agent.graph.retriever_node", return_value={"retrieved_chunks": []}))
    stack.enter_context(patch("agent.graph.citation_validator_node", return_value={"violations": []}))
    stack.enter_context(patch("agent.graph.supervisor_node", side_effect=lambda s: {"violations": [], "final_response": s["draft_response"]}))
    stack.enter_context(patch("agent.graph.asynthesiser_node", side_effect=asynthesiser))
