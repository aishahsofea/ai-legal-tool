import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://example")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.nodes import retriever


class RetrieverExactLookupTests(unittest.TestCase):
    def test_extracts_section_numbers(self):
        self.assertEqual(retriever._extract_section_number("Section 90A of the Evidence Act"), "90A")
        self.assertEqual(retriever._extract_section_number("s. 60K Employment Act"), "60K")
        self.assertEqual(retriever._extract_section_number("sec 114A Evidence Act"), "114A")

    def test_extracts_act_hints(self):
        self.assertEqual(retriever._extract_act_hint("Section 90A of Act 56"), ("56", None))
        self.assertEqual(
            retriever._extract_act_hint("Section 90A of the Evidence Act 1950"),
            ("56", "EVIDENCE ACT 1950"),
        )
        self.assertEqual(
            retriever._extract_act_hint("Section 40 PDPA"),
            ("709", "PERSONAL DATA PROTECTION ACT 2010"),
        )
        self.assertEqual(
            retriever._extract_act_hint("Section 34 of the Penal Code"),
            ("574", "PENAL CODE"),
        )

    def test_statute_lookup_uses_exact_lookup_without_embedding_when_it_hits(self):
        conn = Mock()
        row = {"act_number": "56", "section_number": "90A"}

        with patch.object(retriever.psycopg2, "connect", return_value=conn), \
             patch.object(retriever, "_exact_statute_lookup", return_value=[row]) as exact_lookup, \
             patch.object(retriever, "_vector_search") as vector_search, \
             patch.object(retriever, "_attach_pdf_urls", side_effect=lambda rows: rows):
            result = retriever.retriever_node({
                "query": "What does Section 90A of the Evidence Act say?",
                "query_type": "statute_lookup",
            })

        exact_lookup.assert_called_once_with(conn, "What does Section 90A of the Evidence Act say?")
        vector_search.assert_not_called()
        conn.close.assert_called_once()
        self.assertEqual(result["retrieved_chunks"], [row])

    def test_statute_lookup_falls_back_to_vector_search_when_exact_lookup_misses(self):
        conn = Mock()
        row = {"act_number": "56", "section_number": "90A"}

        with patch.object(retriever.psycopg2, "connect", return_value=conn), \
             patch.object(retriever, "_exact_statute_lookup", return_value=[]), \
             patch.object(retriever, "_vector_search", return_value=[row]) as vector_search, \
             patch.object(retriever, "_attach_pdf_urls", side_effect=lambda rows: rows):
            result = retriever.retriever_node({
                "query": "What does Section 90A say?",
                "query_type": "statute_lookup",
            })

        vector_search.assert_called_once_with(conn, "What does Section 90A say?")
        self.assertEqual(result["retrieved_chunks"], [row])


if __name__ == "__main__":
    unittest.main()
