"""Both memory-consuming nodes must carry the same caveat, in the same words.

The synthesiser and the conversational node each receive recalled Semantic Memory
(ADR 0010), and a prompt inherits nothing from the node before it — so each states
the rule itself. Two hand-written copies drift, and the drift is invisible: the
looser copy is the one that starts letting preferences act as legal authority.
These tests pin the shared wording so a future edit to one node can't quietly
weaken the other.
"""
import unittest

from agent.nodes import conversational, synthesiser
from agent.query_policy import MEMORY_BLOCK_LABEL, memory_soft_context_rule, preferences_block

_RECALLED = "- prefers Bahasa Malaysia\n- focus: unfair dismissal"


def _conversational_messages(recalled: str) -> list[dict]:
    return conversational._build_messages(
        {"query": "hi", "history": [], "response_language": "en", "recalled_memory": recalled}
    )


def _synthesiser_messages(recalled: str) -> list[dict]:
    return synthesiser._build_messages(
        {
            "query": "hi",
            "history": [],
            "response_language": "en",
            "recalled_memory": recalled,
            "retrieved_chunks": [],
        }
    )


class MemoryCaveatConvergenceTests(unittest.TestCase):
    def test_labelled_block_is_byte_identical_across_nodes(self):
        block = preferences_block(_RECALLED)
        self.assertIn(block, _conversational_messages(_RECALLED)[1]["content"])
        self.assertIn(block, _synthesiser_messages(_RECALLED)[1]["content"])

    def test_no_block_when_recall_found_nothing(self):
        self.assertEqual(preferences_block(""), "")
        for messages in (_conversational_messages(""), _synthesiser_messages("")):
            self.assertNotIn(MEMORY_BLOCK_LABEL, messages[1]["content"])

    def test_system_prompts_share_the_rule_up_to_the_override_target(self):
        """Only the thing preferences lose to differs — the caveat itself does not."""
        conversational_rule = memory_soft_context_rule("the hard guardrails below")
        synthesiser_rule = memory_soft_context_rule("the retrieved sections or the query")

        self.assertIn(conversational_rule, _conversational_messages(_RECALLED)[0]["content"])
        self.assertIn(synthesiser_rule, _synthesiser_messages(_RECALLED)[0]["content"])

        shared = memory_soft_context_rule("").rsplit("never let them override", 1)[0]
        self.assertIn(shared, conversational_rule)
        self.assertIn(shared, synthesiser_rule)


if __name__ == "__main__":
    unittest.main()
