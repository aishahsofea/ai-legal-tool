import unittest
from unittest.mock import MagicMock

from evals.assertions import (
    BM_FUNCTION_WORDS,
    check_ai_refusal,
    check_citation_existence,
    check_expected_section,
    check_language_register,
    check_tool_selection,
    check_uuid_leakage,
)


class CheckToolSelectionTests(unittest.TestCase):
    def test_not_applicable_when_no_expected_tool(self):
        self.assertIsNone(check_tool_selection([], None))
        self.assertIsNone(check_tool_selection(["search_statutes"], None))

    def test_passes_when_expected_tool_in_trace(self):
        self.assertIsNone(check_tool_selection(["lookup_section"], "lookup_section"))
        # extra tools alongside the expected one still pass (e.g. fallback search)
        self.assertIsNone(check_tool_selection(["lookup_section", "search_statutes"], "lookup_section"))

    def test_fails_when_expected_tool_absent(self):
        msg = check_tool_selection(["search_statutes"], "lookup_section")
        self.assertIsNotNone(msg)
        self.assertIn("lookup_section", msg)

    def test_fails_on_empty_trace(self):
        self.assertIsNotNone(check_tool_selection([], "search_statutes"))


def _make_db_conn(exists: bool) -> MagicMock:
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = (1,) if exists else None
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


class CheckCitationExistenceTests(unittest.TestCase):
    def test_passes_when_no_citations(self):
        self.assertIsNone(check_citation_existence([], _make_db_conn(exists=True)))

    def test_passes_when_citation_found_in_db(self):
        conn = _make_db_conn(exists=True)
        self.assertIsNone(check_citation_existence([{"act_number": "56", "section_number": "90A"}], conn))

    def test_canonicalizes_citation_before_database_lookup(self):
        conn = _make_db_conn(exists=True)

        result = check_citation_existence(
            [{"act_number": " Act 56 ", "section_number": "Section 90a(1)"}],
            conn,
        )

        self.assertIsNone(result)
        query_params = conn.cursor.return_value.execute.call_args.args[1]
        self.assertEqual(query_params, ("56", "90A"))

    def test_fails_when_citation_not_in_db(self):
        conn = _make_db_conn(exists=False)
        result = check_citation_existence([{"act_number": "56", "section_number": "999Z"}], conn)
        self.assertIsNotNone(result)
        self.assertIn("999Z", result)

    def test_skips_citation_missing_act_number(self):
        conn = _make_db_conn(exists=False)
        self.assertIsNone(check_citation_existence([{"section_number": "90A"}], conn))

    def test_skips_citation_missing_section_number(self):
        conn = _make_db_conn(exists=False)
        self.assertIsNone(check_citation_existence([{"act_number": "56"}], conn))

    def test_boundary_multiple_citations_one_missing(self):
        cur = MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchone.side_effect = [(1,), None]
        conn = MagicMock()
        conn.cursor.return_value = cur

        citations = [
            {"act_number": "56", "section_number": "90A"},
            {"act_number": "56", "section_number": "999Z"},
        ]
        result = check_citation_existence(citations, conn)
        self.assertIsNotNone(result)
        self.assertIn("999Z", result)
        self.assertNotIn("90A", result)


class CheckExpectedSectionTests(unittest.TestCase):
    def test_passes_when_expected_section_in_citations(self):
        citations = [{"act_number": "56", "section_number": "90A"}]
        self.assertIsNone(check_expected_section(citations, "56", "90A"))

    def test_passes_case_insensitive(self):
        citations = [{"act_number": "56", "section_number": "90a"}]
        self.assertIsNone(check_expected_section(citations, "56", "90A"))

    def test_passes_for_formatted_citation_identifiers(self):
        citations = [{"act_number": "Act 56", "section_number": "Section 90a(1)"}]
        self.assertIsNone(check_expected_section(citations, "56", "90A"))

    def test_fails_when_expected_section_absent_from_citations(self):
        citations = [{"act_number": "56", "section_number": "90A"}]
        result = check_expected_section(citations, "56", "73A")
        self.assertIsNotNone(result)
        self.assertIn("73A", result)

    def test_not_applicable_when_both_expected_fields_none(self):
        self.assertIsNone(check_expected_section([], None, None))

    def test_not_applicable_when_expected_act_number_none(self):
        self.assertIsNone(check_expected_section([], None, "90A"))

    def test_not_applicable_when_expected_section_none(self):
        self.assertIsNone(check_expected_section([], "56", None))

    def test_boundary_fails_when_citations_empty_but_section_expected(self):
        result = check_expected_section([], "56", "90A")
        self.assertIsNotNone(result)
        self.assertIn("90A", result)

    def test_fails_when_act_number_does_not_match(self):
        citations = [{"act_number": "574", "section_number": "90A"}]
        result = check_expected_section(citations, "56", "90A")
        self.assertIsNotNone(result)


class CheckLanguageRegisterTests(unittest.TestCase):
    def test_passes_for_english_only_query(self):
        self.assertIsNone(
            check_language_register("What is defamation?", "Defamation is defined in section 499...")
        )

    def test_passes_when_bm_query_has_bm_response(self):
        self.assertIsNone(
            check_language_register(
                "Apakah definisi fitnah dalam Kanun Keseksaan?",
                "Fitnah di bawah akta ini bermaksud...",
            )
        )

    def test_fails_when_bm_query_gets_english_only_response(self):
        result = check_language_register(
            "Apakah hak pekerja untuk mendapatkan gaji?",
            "An employee has the right to receive wages on time under the Employment Act.",
        )
        self.assertIsNotNone(result)

    def test_boundary_empty_query_is_not_bm(self):
        self.assertIsNone(check_language_register("", "Some English response."))

    def test_boundary_bm_word_in_response_is_sufficient(self):
        self.assertIsNone(
            check_language_register(
                "Bagaimana mahkamah menentukan niat?",
                "The court (mahkamah) determines intent by examining...",
            )
        )


class CheckUuidLeakageTests(unittest.TestCase):
    def test_passes_with_no_uuid_in_response(self):
        self.assertIsNone(check_uuid_leakage("Section 90A of the Evidence Act 1950 applies."))

    def test_fails_when_uuid_present(self):
        result = check_uuid_leakage(
            "The chunk id 550e8400-e29b-41d4-a716-446655440000 was retrieved."
        )
        self.assertIsNotNone(result)

    def test_boundary_empty_response(self):
        self.assertIsNone(check_uuid_leakage(""))

    def test_uuid_detection_is_case_insensitive(self):
        result = check_uuid_leakage("ID: 550E8400-E29B-41D4-A716-446655440000.")
        self.assertIsNotNone(result)


class CheckAiRefusalTests(unittest.TestCase):
    def test_passes_on_block_policy_regardless_of_content(self):
        self.assertIsNone(
            check_ai_refusal("As an AI, I cannot provide legal advice.", "block")
        )

    def test_passes_on_allow_policy_with_clean_response(self):
        self.assertIsNone(
            check_ai_refusal("Section 90A of the Evidence Act applies here.", "allow")
        )

    def test_fails_on_allow_policy_with_as_an_ai_phrase(self):
        result = check_ai_refusal(
            "As an AI, I cannot provide legal advice on this matter.", "allow"
        )
        self.assertIsNotNone(result)

    def test_fails_on_allow_policy_with_i_am_not_able_to(self):
        result = check_ai_refusal("I am not able to assist with legal questions.", "allow")
        self.assertIsNotNone(result)

    def test_boundary_allow_policy_empty_response(self):
        self.assertIsNone(check_ai_refusal("", "allow"))


if __name__ == "__main__":
    unittest.main()
