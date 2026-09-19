import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from agent import web_search
from agent.web_search import empty_web_search_metrics, search_web

ALLOWLIST = ["skrine.com"]

_TAVILY_PAYLOAD = {
    "results": [
        {
            "url": "https://www.skrine.com/insights/one",
            "title": "One",
            "published_date": "2024-01-01",
            "content": "snippet one",
        },
        {"url": "https://blog.skrine.com/two", "title": "Two", "content": "snippet two"},
        {"url": "https://evil.example.com/three", "title": "Three", "content": "off-list"},
        {"url": "https://notskrine.com/four", "title": "Four", "content": "lookalike"},
    ]
}


class _FakeResponse:
    def __init__(self, payload=None, *, json_error=None, http_error=None):
        self._payload = payload
        self._json_error = json_error
        self._http_error = http_error

    def raise_for_status(self):
        if self._http_error is not None:
            raise self._http_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _FakeSession:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self._raises is not None:
            raise self._raises
        return self._response


class AllowlistFilteringTests(unittest.TestCase):
    def test_keeps_exact_and_subdomain_matches(self):
        session = _FakeSession(_FakeResponse(_TAVILY_PAYLOAD))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual(result["status"], "ok")
        urls = [r["url"] for r in result["results"]]
        self.assertEqual(
            urls,
            ["https://www.skrine.com/insights/one", "https://blog.skrine.com/two"],
        )

    def test_drops_and_counts_out_of_allowlist_domains_including_lookalikes(self):
        session = _FakeSession(_FakeResponse(_TAVILY_PAYLOAD))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        # evil.example.com and notskrine.com: a suffix check would wrongly
        # accept the second one as a "skrine.com" match on substring alone.
        self.assertEqual(result["metrics"]["results_dropped_allowlist"], 2)
        self.assertEqual(result["metrics"]["results_returned"], 2)

    def test_domain_field_is_the_allowlist_entry_not_the_raw_hostname(self):
        session = _FakeSession(_FakeResponse(_TAVILY_PAYLOAD))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertTrue(all(r["domain"] == "skrine.com" for r in result["results"]))

    def test_allowlist_comparison_is_case_insensitive(self):
        payload = {"results": [{"url": "https://WWW.Skrine.com/x", "title": "X", "content": "c"}]}
        session = _FakeSession(_FakeResponse(payload))
        result = search_web("query", ["SKRINE.COM"], api_key="k", session=session)

        self.assertEqual(result["metrics"]["results_returned"], 1)
        self.assertEqual(result["results"][0]["domain"], "skrine.com")


class NormalisationTests(unittest.TestCase):
    def test_missing_published_date_becomes_empty_string(self):
        session = _FakeSession(_FakeResponse(_TAVILY_PAYLOAD))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual(result["results"][0]["published_date"], "2024-01-01")
        self.assertEqual(result["results"][1]["published_date"], "")

    def test_snippet_comes_from_the_content_field(self):
        session = _FakeSession(_FakeResponse(_TAVILY_PAYLOAD))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual(result["results"][0]["snippet"], "snippet one")

    def test_retrieved_at_is_stamped_on_every_result(self):
        session = _FakeSession(_FakeResponse(_TAVILY_PAYLOAD))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertTrue(all(r["retrieved_at"] for r in result["results"]))

    def test_non_dict_items_are_skipped_without_raising(self):
        payload = {
            "results": ["not-a-dict", {"url": "https://skrine.com/x", "title": "X", "content": "c"}]
        }
        session = _FakeSession(_FakeResponse(payload))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual(result["metrics"]["results_returned"], 1)


class ErrorContractTests(unittest.TestCase):
    def test_missing_api_key(self):
        result = search_web("query", ALLOWLIST, api_key="", session=_FakeSession())

        self.assertEqual((result["status"], result["reason"]), ("error", "missing_api_key"))
        self.assertEqual(result["metrics"]["failures_missing_api_key"], 1)
        self.assertEqual(result["results"], [])

    def test_missing_api_key_falls_back_to_the_environment_when_not_passed(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TAVILY_API_KEY", None)
            result = search_web("query", ALLOWLIST, session=_FakeSession())

        self.assertEqual(result["reason"], "missing_api_key")

    def test_timeout(self):
        session = _FakeSession(raises=requests.exceptions.Timeout("slow"))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual((result["status"], result["reason"]), ("error", "timeout"))
        self.assertEqual(result["metrics"]["failures_timeout"], 1)

    def test_http_error(self):
        response = _FakeResponse(http_error=requests.exceptions.HTTPError("500"))
        session = _FakeSession(response)
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual((result["status"], result["reason"]), ("error", "http_error"))
        self.assertEqual(result["metrics"]["failures_http_error"], 1)

    def test_connection_error_is_also_an_http_error(self):
        session = _FakeSession(raises=requests.exceptions.ConnectionError("refused"))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual(result["reason"], "http_error")

    def test_malformed_response_not_json(self):
        response = _FakeResponse(json_error=ValueError("no json"))
        session = _FakeSession(response)
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual((result["status"], result["reason"]), ("error", "malformed_response"))
        self.assertEqual(result["metrics"]["failures_malformed_response"], 1)

    def test_malformed_response_missing_results_key(self):
        session = _FakeSession(_FakeResponse({"answer": "no results key here"}))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual(result["reason"], "malformed_response")

    def test_malformed_response_results_is_not_a_list(self):
        session = _FakeSession(_FakeResponse({"results": "not-a-list"}))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual(result["reason"], "malformed_response")

    def test_empty_result(self):
        session = _FakeSession(_FakeResponse({"results": []}))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual((result["status"], result["reason"]), ("error", "empty_result"))
        self.assertEqual(result["metrics"]["failures_empty_result"], 1)

    def test_all_results_dropped_by_allowlist_is_ok_not_empty_result(self):
        """Tavily found things; none of them were trusted — different from Tavily
        finding nothing, so this must not collapse into the empty_result reason."""
        payload = {"results": [{"url": "https://evil.example.com/x", "title": "X", "content": "c"}]}
        session = _FakeSession(_FakeResponse(payload))
        result = search_web("query", ALLOWLIST, api_key="k", session=session)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["results"], [])
        self.assertEqual(result["metrics"]["results_dropped_allowlist"], 1)


class CounterAndCallContractTests(unittest.TestCase):
    def test_empty_metrics_has_a_fixed_zero_filled_shape(self):
        metrics = empty_web_search_metrics()

        self.assertTrue(all(v == 0 for v in metrics.values()))
        self.assertEqual(
            set(metrics),
            {
                "calls",
                "results_returned",
                "results_dropped_allowlist",
                "failures_missing_api_key",
                "failures_http_error",
                "failures_timeout",
                "failures_malformed_response",
                "failures_empty_result",
            },
        )

    def test_calls_counted_even_on_the_earliest_failure(self):
        result = search_web("query", ALLOWLIST, api_key="", session=_FakeSession())
        self.assertEqual(result["metrics"]["calls"], 1)

    def test_caller_supplied_timeout_reaches_the_request(self):
        session = _FakeSession(_FakeResponse({"results": []}))
        search_web("query", ALLOWLIST, api_key="k", timeout=2.5, session=session)

        self.assertEqual(session.calls[0]["timeout"], 2.5)

    def test_query_and_max_results_reach_the_request_payload(self):
        session = _FakeSession(_FakeResponse({"results": []}))
        search_web("privacy act", ALLOWLIST, api_key="k", max_results=3, session=session)

        payload = session.calls[0]["json"]
        self.assertEqual(payload["query"], "privacy act")
        self.assertEqual(payload["max_results"], 3)

    def test_api_key_never_appears_in_the_returned_result(self):
        session = _FakeSession(_FakeResponse(_TAVILY_PAYLOAD))
        result = search_web("query", ALLOWLIST, api_key="a-secret-key", session=session)

        self.assertNotIn("a-secret-key", str(result))


class NoCallerCouplingTests(unittest.TestCase):
    def test_module_imports_nothing_from_agent_state_graph_or_retrieval(self):
        source = Path(web_search.__file__).read_text()
        tree = ast.parse(source)
        forbidden = ("agent.state", "agent.graph", "agent.retrieval")

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(
                    any(node.module.startswith(mod) for mod in forbidden),
                    f"web_search.py must not import from {node.module}",
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(
                        any(alias.name.startswith(mod) for mod in forbidden),
                        f"web_search.py must not import {alias.name}",
                    )


if __name__ == "__main__":
    unittest.main()
