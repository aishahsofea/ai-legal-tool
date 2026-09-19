"""
Allowlisted web search transport, shared by callers that do not exist yet:
the commentary channel (#56) and the Act-currency check (#60).

Tavily's search API is a single HTTPS POST, and `requests` is already the
first dependency in requirements.txt, so this calls it directly instead of
adding `tavily-python`. Every other outbound call in this repo already sets
its own timeout explicitly (scraper/step3_pdfs.py, corpus/storage.py) —
same rule here.

This module owns the client, the allowlist filter, and the error contract.
It takes no position on which domains to trust or who is allowed to call it:
the allowlist is an argument, not a module constant, and there is no feature
flag here — a caller that never calls this module gets no behaviour change,
and each caller (#56, #60) brings its own flag and its own list.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, TypedDict
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class WebResult(TypedDict):
    url: str
    title: str
    domain: str            # the allowlist entry that served it
    published_date: str    # "" when the source gives none
    retrieved_at: str
    snippet: str


def empty_web_search_metrics() -> dict[str, int]:
    return {
        "calls": 0,
        "results_returned": 0,
        "results_dropped_allowlist": 0,
        "failures_missing_api_key": 0,
        "failures_http_error": 0,
        "failures_timeout": 0,
        "failures_malformed_response": 0,
        "failures_empty_result": 0,
    }


def _result(
    status: str, reason: str, results: list[WebResult], metrics: dict[str, int]
) -> dict[str, Any]:
    return {"status": status, "reason": reason, "results": results, "metrics": metrics}


def _hostname(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _matching_allowlist_entry(hostname: str, allowlist: list[str]) -> str | None:
    """A hostname matches when it equals an allowlist entry or is one of its
    subdomains: `www.skrine.com` and `blog.skrine.com` match `skrine.com`,
    `notskrine.com` does not. Case-insensitive. Every caller gets this same
    rule — none gets to loosen it to a substring check."""
    if not hostname:
        return None
    for entry in allowlist:
        normalised = str(entry or "").strip().lower()
        if normalised and (hostname == normalised or hostname.endswith("." + normalised)):
            return normalised
    return None


def search_web(
    query: str,
    allowlist: list[str],
    *,
    max_results: int = 5,
    timeout: float = 10.0,
    api_key: str | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Search Tavily and keep only results from `allowlist`.

    Never raises: a missing key, a transport error, a timeout, a response
    that doesn't parse, and a search with no hits at all are each a distinct
    failure reason in the returned dict, not an exception. `status` is "ok"
    only once results have been fetched and allowlist-filtered, even when
    every result was dropped for being off the list.
    """
    metrics = empty_web_search_metrics()
    metrics["calls"] = 1

    key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY")
    if not key:
        metrics["failures_missing_api_key"] = 1
        return _result("error", "missing_api_key", [], metrics)

    http = session if session is not None else requests
    try:
        response = http.post(
            _TAVILY_SEARCH_URL,
            json={"api_key": key, "query": query, "max_results": max_results},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        metrics["failures_timeout"] = 1
        return _result("error", "timeout", [], metrics)
    except requests.exceptions.RequestException as exc:
        logger.warning("Tavily search failed: %s", exc)
        metrics["failures_http_error"] = 1
        return _result("error", "http_error", [], metrics)

    try:
        body = response.json()
    except ValueError as exc:
        logger.warning("Tavily search returned a response that isn't JSON: %s", exc)
        metrics["failures_malformed_response"] = 1
        return _result("error", "malformed_response", [], metrics)

    raw_results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(raw_results, list):
        logger.warning("Tavily search response had no `results` list")
        metrics["failures_malformed_response"] = 1
        return _result("error", "malformed_response", [], metrics)
    if not raw_results:
        metrics["failures_empty_result"] = 1
        return _result("error", "empty_result", [], metrics)

    retrieved_at = datetime.now(timezone.utc).isoformat()
    results: list[WebResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        domain = _matching_allowlist_entry(_hostname(url), allowlist)
        if domain is None:
            metrics["results_dropped_allowlist"] += 1
            continue
        results.append(
            WebResult(
                url=url,
                title=str(item.get("title") or ""),
                domain=domain,
                published_date=str(item.get("published_date") or ""),
                retrieved_at=retrieved_at,
                snippet=str(item.get("content") or ""),
            )
        )

    metrics["results_returned"] = len(results)
    return _result("ok", "", results, metrics)
