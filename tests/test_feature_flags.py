"""Every boolean flag must answer to the same spellings.

These predicates used to parse their own env var, and had drifted: setting
AGENTIC_RETRIEVAL=on was a silent no-op while the LangSmith metadata recorded
the run as agentic. Parity is the actual invariant, so assert it per flag
rather than only unit-testing the shared parser.
"""
import os
import unittest
from unittest.mock import patch

from agent.feature_flags import flag_enabled, parse_feature_flag
from agent.graph import _agentic_retrieval_enabled
from agent.memory.extractor import _enabled as extract_enabled
from agent.memory.pruner import _enabled as prune_enabled
from agent.nodes.recall import _enabled as recall_enabled
from agent.retrieval.reference_graph import follow_references_enabled
from api.reference_graph import reference_graph_comparison_enabled, reference_graph_enabled

TRUE_SPELLINGS = ("1", "true", "TRUE", "yes", "on", "ON", "  on  ")
FALSE_SPELLINGS = ("", "0", "off", "no", "unexpected", "onn")

FLAGS = {
    "AGENTIC_RETRIEVAL": _agentic_retrieval_enabled,
    "SEMANTIC_MEMORY_EXTRACT": extract_enabled,
    "SEMANTIC_MEMORY_PRUNE": prune_enabled,
    "SEMANTIC_MEMORY_RECALL": recall_enabled,
    "FOLLOW_REFERENCES_ENABLED": follow_references_enabled,
    "REFERENCE_GRAPH_ENABLED": reference_graph_enabled,
}


class FeatureFlagParityTests(unittest.TestCase):
    def test_every_flag_accepts_the_same_true_spellings(self):
        for name, predicate in FLAGS.items():
            for value in TRUE_SPELLINGS:
                with self.subTest(flag=name, value=value):
                    with patch.dict(os.environ, {name: value}):
                        self.assertTrue(predicate())

    def test_every_flag_stays_off_for_anything_else(self):
        for name, predicate in FLAGS.items():
            for value in FALSE_SPELLINGS:
                with self.subTest(flag=name, value=value):
                    with patch.dict(os.environ, {name: value}):
                        self.assertFalse(predicate())

    def test_every_flag_is_off_when_unset(self):
        for name, predicate in FLAGS.items():
            with self.subTest(flag=name):
                with patch.dict(os.environ, {}, clear=True):
                    self.assertFalse(predicate())

    def test_comparison_flag_stays_closed_without_its_base_flag(self):
        with patch.dict(os.environ, {"REFERENCE_GRAPH_COMPARISON_ENABLED": "on"}, clear=True):
            self.assertFalse(reference_graph_comparison_enabled())
        with patch.dict(
            os.environ,
            {"REFERENCE_GRAPH_ENABLED": "1", "REFERENCE_GRAPH_COMPARISON_ENABLED": "yes"},
        ):
            self.assertTrue(reference_graph_comparison_enabled())

    def test_parser_treats_none_as_off(self):
        self.assertFalse(parse_feature_flag(None))
        self.assertFalse(flag_enabled("A_FLAG_NOBODY_SET"))


if __name__ == "__main__":
    unittest.main()
