import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://example")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.nodes import retriever
from agent.retrieval import search


class SearchHelperTests(unittest.TestCase):
    def test_extracts_section_numbers(self):
        self.assertEqual(search.extract_section_number("Section 90A of the Evidence Act"), "90A")
        self.assertEqual(search.extract_section_number("s. 60K Employment Act"), "60K")
        self.assertEqual(search.extract_section_number("sec 114A Evidence Act"), "114A")

    def test_extracts_bm_section_numbers(self):
        self.assertEqual(search.extract_section_number("seksyen 34 Kanun Keseksaan"), "34")
        self.assertEqual(search.extract_section_number("seksyen 60A Akta Pekerjaan"), "60A")
        self.assertEqual(search.extract_section_number("Seksyen 90A Akta Keterangan"), "90A")

    def test_extracts_act_hints(self):
        self.assertEqual(search.extract_act_hint("Section 90A of Act 56"), ("56", None))
        self.assertEqual(
            search.extract_act_hint("Section 90A of the Evidence Act 1950"),
            ("56", "EVIDENCE ACT 1950"),
        )
        self.assertEqual(
            search.extract_act_hint("Section 40 PDPA"),
            ("709", "PERSONAL DATA PROTECTION ACT 2010"),
        )
        self.assertEqual(
            search.extract_act_hint("Section 34 of the Penal Code"),
            ("574", "PENAL CODE"),
        )

    def test_extracts_bm_act_hints(self):
        self.assertEqual(
            search.extract_act_hint("seksyen 34 Kanun Keseksaan"),
            ("574", "PENAL CODE"),
        )
        self.assertEqual(
            search.extract_act_hint("seksyen 60A Akta Pekerjaan 1955"),
            ("265", "EMPLOYMENT ACT 1955"),
        )
        self.assertEqual(
            search.extract_act_hint("seksyen 90A Akta Keterangan"),
            ("56", "EVIDENCE ACT 1950"),
        )
        self.assertEqual(
            search.extract_act_hint("Akta Perlindungan Data Peribadi seksyen 5"),
            ("709", "PERSONAL DATA PROTECTION ACT 2010"),
        )
        self.assertEqual(
            search.extract_act_hint("seksyen 10 Akta Syarikat"),
            ("777", "COMPANIES ACT 2016"),
        )


class RetrieverNodeTests(unittest.TestCase):
    def test_statute_lookup_uses_exact_lookup_without_semantic_when_it_hits(self):
        row = {"act_number": "56", "section_number": "90A"}
        with patch.object(retriever, "exact_section_lookup", return_value=[row]) as exact_lookup, \
             patch.object(retriever, "semantic_search") as sem_search:
            result = retriever.retriever_node({
                "query": "What does Section 90A of the Evidence Act say?",
                "query_type": "statute_lookup",
            })

        exact_lookup.assert_called_once_with("90A", "56", "EVIDENCE ACT 1950")
        sem_search.assert_not_called()
        self.assertEqual(result["retrieved_chunks"], [row])

    def test_statute_lookup_falls_back_to_semantic_when_exact_lookup_misses(self):
        row = {"act_number": "56", "section_number": "90A"}
        with patch.object(retriever, "exact_section_lookup", return_value=[]), \
             patch.object(retriever, "semantic_search", return_value=[row]) as sem_search:
            result = retriever.retriever_node({
                "query": "What does Section 90A of the Evidence Act say?",
                "query_type": "statute_lookup",
            })

        sem_search.assert_called_once()
        self.assertEqual(result["retrieved_chunks"], [row])

    def test_topical_query_uses_semantic_search_only(self):
        row = {"act_number": "709", "section_number": "5"}
        with patch.object(retriever, "exact_section_lookup") as exact_lookup, \
             patch.object(retriever, "semantic_search", return_value=[row]) as sem_search:
            result = retriever.retriever_node({
                "query": "which laws cover data privacy for employers?",
                "query_type": "topical",
            })

        exact_lookup.assert_not_called()
        sem_search.assert_called_once()
        self.assertEqual(result["retrieved_chunks"], [row])

    def test_uses_standalone_query_when_present(self):
        with patch.object(retriever, "semantic_search", return_value=[]) as sem_search:
            retriever.retriever_node({
                "query": "what about it?",
                "standalone_query": "what is the penalty under the Employment Act?",
                "query_type": "topical",
            })
        sem_search.assert_called_once_with("what is the penalty under the Employment Act?")


if __name__ == "__main__":
    unittest.main()
