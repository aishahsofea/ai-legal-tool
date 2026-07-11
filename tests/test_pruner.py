"""Semantic Memory pruning (ADR 0010, Phase 4): importance+recency eviction, profile
dedupe, near-duplicate topic consolidation, and the fail-open / conservative
guarantees (never delete the sole profile, never empty a namespace).

Uses a real InMemoryStore with a deterministic stub index (shared with the eval) so
vector-search clustering scores are reproducible — the flag and the store's data are
the only inputs. The retrieval-frequency signal recorded by recall is exercised too.
"""
import asyncio
import os
import unittest
from unittest.mock import patch

from langgraph.store.memory import InMemoryStore

from agent.memory import pruner, stats
from agent.nodes.recall import recall_node
from evals.semantic_memory import STUB_INDEX

USER = "user-1"
NS = (USER, "semantic")


def _store() -> InMemoryStore:
    return InMemoryStore(index=STUB_INDEX)


def _topic(store, key, topic):
    store.put(NS, key, {"kind": "RecurringTopic", "content": {"topic": topic}})


def _profile(store, key, content):
    store.put(NS, key, {"kind": "PractitionerProfile", "content": content})


def _count(store, key, n, user_id=USER):
    store.put(stats.meta_namespace(user_id), key, {"recall_count": n}, index=False)


def _prune(store, user_id=USER, flag="on", cap=3, margin=0):
    with patch.dict(os.environ, {"SEMANTIC_MEMORY_PRUNE": flag}), \
         patch.object(pruner, "_TOPIC_CAP", cap), \
         patch.object(pruner, "_TRIGGER_MARGIN", margin):
        asyncio.run(pruner.prune_memory(store, user_id))


def _topics(store, ns=NS):
    return sorted(
        (item.value or {}).get("content", {}).get("topic")
        for item in store.search(ns, limit=100)
        if (item.value or {}).get("kind") == "RecurringTopic"
    )


def _profiles(store, ns=NS):
    return [item for item in store.search(ns, limit=100)
            if (item.value or {}).get("kind") == "PractitionerProfile"]


class EvictionTests(unittest.TestCase):
    def test_high_value_survives_low_value_evicted_at_cap(self):
        store = _store()
        _topic(store, "valuable", "unfair dismissal remedies")
        _count(store, "valuable", 6)  # frequently recalled → high importance
        for i in range(5):
            _topic(store, f"noise-{i}", f"unrelated topic number {i}")

        _prune(store, cap=3)

        topics = _topics(store)
        self.assertEqual(len(topics), 3)  # capped
        self.assertIn("unfair dismissal remedies", topics)  # importance kept it

    def test_never_empties_namespace(self):
        store = _store()
        for i in range(4):
            _topic(store, f"t-{i}", f"distinct topic {i}")

        _prune(store, cap=1)

        self.assertGreaterEqual(len(store.search(NS, limit=100)), 1)


class ProfileDedupeTests(unittest.TestCase):
    def test_multiple_profiles_collapse_to_one_merged(self):
        store = _store()
        _profile(store, "profile-a", {"background": "software engineer exploring legal tech",
                                      "response_language": "bm", "practice_areas": ["employment"]})
        _profile(store, "profile-b", {"citation_style": "prefers brief answers",
                                      "practice_areas": ["employment", "labour"]})

        _prune(store, cap=30, margin=10)  # size below cap; profiles>1 still triggers a pass

        profiles = _profiles(store)
        self.assertEqual(len(profiles), 1)
        content = profiles[0].value["content"]
        # background must survive consolidation — otherwise the pruner silently erases the
        # practitioner's identity the moment a second profile appears (ADR 0012).
        self.assertEqual(content["background"], "software engineer exploring legal tech")
        self.assertEqual(content["response_language"], "bm")
        self.assertEqual(content["citation_style"], "prefers brief answers")
        self.assertEqual(set(content["practice_areas"]), {"employment", "labour"})

    def test_sole_profile_is_never_deleted(self):
        store = _store()
        _profile(store, "only", {"response_language": "en"})
        for i in range(5):
            _topic(store, f"t-{i}", f"distinct topic {i}")

        _prune(store, cap=2)

        self.assertEqual(len(_profiles(store)), 1)


class ConsolidationTests(unittest.TestCase):
    def test_consolidation_keeps_most_recalled(self):
        store = _store()
        _topic(store, "valuable", "unfair dismissal remedies")
        _count(store, "valuable", 5)
        _topic(store, "dup", "remedies unfair dismissal")
        _count(store, "dup", 1)
        _topic(store, "other", "stamp duty exemption thresholds")

        _prune(store, cap=2)  # items(3) > cap(2) → pass runs

        topics = _topics(store)
        self.assertIn("unfair dismissal remedies", topics)  # representative kept
        self.assertNotIn("remedies unfair dismissal", topics)  # duplicate consolidated away
        self.assertIn("stamp duty exemption thresholds", topics)  # distinct topic untouched


class NoOpTests(unittest.TestCase):
    def _two_profiles(self, store, ns=NS):
        store.put(ns, "p1", {"kind": "PractitionerProfile", "content": {"response_language": "bm"}})
        store.put(ns, "p2", {"kind": "PractitionerProfile", "content": {"response_language": "en"}})

    def test_flag_off_is_noop(self):
        store = _store()
        self._two_profiles(store)
        _prune(store, flag="off")
        self.assertEqual(len(_profiles(store)), 2)

    def test_no_user_id_is_noop(self):
        store = _store()
        self._two_profiles(store)
        _prune(store, user_id=None)
        self.assertEqual(len(_profiles(store)), 2)

    def test_anonymous_user_id_is_noop(self):
        store = _store()
        ns = ("anonymous", "semantic")
        self._two_profiles(store, ns)
        _prune(store, user_id="anonymous")
        self.assertEqual(len(_profiles(store, ns)), 2)

    def test_no_store_is_noop(self):
        _prune(None)  # must not raise

    def test_pruning_error_is_swallowed(self):
        store = _store()
        self._two_profiles(store)

        async def boom(*args, **kwargs):
            raise RuntimeError("store down")

        with patch.object(InMemoryStore, "asearch", boom):
            _prune(store)  # fail-open: no exception escapes

        self.assertEqual(len(_profiles(store)), 2)  # untouched


class RecallHitRecordingTests(unittest.TestCase):
    def test_recall_records_a_hit_per_surfaced_item(self):
        store = _store()
        _topic(store, "valuable", "unfair dismissal remedies")

        with patch.dict(os.environ, {"SEMANTIC_MEMORY_RECALL": "on"}):
            out = recall_node({"query": "unfair dismissal"},
                              {"configurable": {"user_id": USER}}, store=store)

        self.assertIn("unfair dismissal remedies", out["recalled_memory"])
        meta = store.get(stats.meta_namespace(USER), "valuable")
        self.assertEqual(meta.value["recall_count"], 1)

    def test_hit_recording_error_does_not_affect_recall(self):
        store = _store()
        _topic(store, "valuable", "unfair dismissal remedies")

        with patch.dict(os.environ, {"SEMANTIC_MEMORY_RECALL": "on"}), \
             patch("agent.nodes.recall.stats.record_hits", side_effect=RuntimeError("boom")):
            out = recall_node({"query": "unfair dismissal"},
                              {"configurable": {"user_id": USER}}, store=store)

        self.assertIn("unfair dismissal remedies", out["recalled_memory"])


if __name__ == "__main__":
    unittest.main()
