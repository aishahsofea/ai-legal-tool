"""The practitioner profile is recalled DETERMINISTICALLY, not by winning a vector
search (ADR 0012). A store double lets the profile fetch (by kind) and the query-ranked
search return independently, so we can prove the profile surfaces even when the
similarity search finds nothing relevant.
"""
import os
import unittest
from unittest.mock import patch

from agent.nodes.recall import recall_node


class _Item:
    """Duck-typed SearchItem: recall only reads .key and .value."""

    def __init__(self, key, value):
        self.key = key
        self.value = value


class _PartitionStore:
    """Returns the profile list for a kind-filtered search and the relevant list for a
    query search — so the two halves of recall can be exercised in isolation."""

    def __init__(self, *, profiles, relevant):
        self._profiles = profiles
        self._relevant = relevant

    def search(self, _ns, *, query=None, filter=None, limit=10):
        if filter and filter.get("kind") == "PractitionerProfile":
            return list(self._profiles)
        return list(self._relevant)


def _profile(background):
    return _Item("profile", {"kind": "PractitionerProfile", "content": {"background": background}})


def _topic(topic):
    return _Item("topic-" + topic, {"kind": "RecurringTopic", "content": {"topic": topic}})


def _recall(store, query="what is my profession"):
    with patch.dict(os.environ, {"SEMANTIC_MEMORY_RECALL": "on"}):
        return recall_node(
            {"query": query},
            {"configurable": {"user_id": "user-1"}},
            store=store,
        ).get("recalled_memory", "")


class ProfileAlwaysRecalledTests(unittest.TestCase):
    def test_profile_surfaces_even_when_query_matches_nothing(self):
        # The whole point: relevance search returns [], profile still comes through.
        store = _PartitionStore(profiles=[_profile("software engineer exploring legal tech")], relevant=[])

        recalled = _recall(store, query="totally unrelated gibberish")

        self.assertIn("background: software engineer exploring legal tech", recalled)

    def test_profile_is_listed_before_relevant_topics(self):
        store = _PartitionStore(
            profiles=[_profile("software engineer")],
            relevant=[_topic("unfair dismissal remedies")],
        )

        recalled = _recall(store)

        self.assertIn("background: software engineer", recalled)
        self.assertIn("topic: unfair dismissal remedies", recalled)
        self.assertLess(
            recalled.index("background: software engineer"),
            recalled.index("topic: unfair dismissal remedies"),
        )

    def test_profile_not_duplicated_when_also_query_relevant(self):
        # If the similarity search also returns the profile, the merge dedupes by key.
        prof = _profile("software engineer")
        store = _PartitionStore(profiles=[prof], relevant=[prof])

        recalled = _recall(store)

        self.assertEqual(recalled.count("background: software engineer"), 1)

    def test_empty_everything_is_noop(self):
        store = _PartitionStore(profiles=[], relevant=[])

        recalled = _recall(store)

        self.assertEqual(recalled, "")


if __name__ == "__main__":
    unittest.main()
