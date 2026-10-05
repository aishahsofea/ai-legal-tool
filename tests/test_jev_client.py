import json
import os
import unittest
from unittest.mock import MagicMock, patch

import requests

from agent.jev_client import JevError, classify, supported_probability

_ENV = {"TYPESAFE_API_KEY": "test-key", "JEV_MODEL": "jev-1.13.0"}


def _response(body, status_error=None):
    response = MagicMock()
    response.json.return_value = body
    response.raise_for_status.side_effect = status_error
    return response


def _ok(supported=0.93):
    return _response(
        {"answers": {"verdict": {"choice": "supported", "probabilities": {"supported": supported}}}}
    )


class JevClientTests(unittest.TestCase):
    def test_returns_supported_probability_and_sends_the_pinned_model(self):
        with patch.dict(os.environ, _ENV), patch(
            "agent.jev_client.requests.post", return_value=_ok(0.93)
        ) as post:
            self.assertEqual(supported_probability("the answer", [{"content": "the section"}]), 0.93)

        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "jev-1.13.0")
        self.assertEqual(
            json.loads(body["state"]),
            {"cited_sources": [{"content": "the section"}], "answer": "the answer"},
        )
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer test-key"})
        self.assertIsNotNone(post.call_args.kwargs["timeout"])

    def test_timeout_raises(self):
        with patch.dict(os.environ, _ENV), patch(
            "agent.jev_client.requests.post", side_effect=requests.exceptions.Timeout()
        ):
            with self.assertRaises(JevError):
                supported_probability("a", [])

    def test_bad_status_raises(self):
        error = requests.exceptions.HTTPError("500")
        with patch.dict(os.environ, _ENV), patch(
            "agent.jev_client.requests.post", return_value=_response({}, status_error=error)
        ):
            with self.assertRaises(JevError):
                supported_probability("a", [])

    def test_malformed_response_raises(self):
        for body in ({}, {"answers": {"verdict": {"probabilities": {}}}}, {"answers": None}):
            with self.subTest(body=body), patch.dict(os.environ, _ENV), patch(
                "agent.jev_client.requests.post", return_value=_response(body)
            ):
                with self.assertRaises(JevError):
                    supported_probability("a", [])

    def test_out_of_range_probability_raises(self):
        with patch.dict(os.environ, _ENV), patch(
            "agent.jev_client.requests.post", return_value=_ok(1.5)
        ):
            with self.assertRaises(JevError):
                supported_probability("a", [])

    def test_jev_latest_is_rejected_before_any_request(self):
        with patch.dict(os.environ, {**_ENV, "JEV_MODEL": "jev-latest"}), patch(
            "agent.jev_client.requests.post"
        ) as post:
            with self.assertRaises(JevError):
                supported_probability("a", [])
        post.assert_not_called()

    def test_missing_model_or_key_raises_before_any_request(self):
        for drop in ("JEV_MODEL", "TYPESAFE_API_KEY"):
            env = {k: v for k, v in _ENV.items() if k != drop}
            with self.subTest(missing=drop), patch.dict(os.environ, env, clear=True), patch(
                "agent.jev_client.requests.post"
            ) as post:
                with self.assertRaises(JevError):
                    supported_probability("a", [])
            post.assert_not_called()

    def test_classify_returns_answers_and_sends_questions(self):
        answers = {"query_type": {"choice": "topical", "probabilities": {"topical": 0.9}}}
        questions = {"query_type": {"type": "choice", "instructions": "x", "criteria": {"topical": "y"}}}
        with patch.dict(os.environ, _ENV), patch(
            "agent.jev_client.requests.post", return_value=_response({"answers": answers})
        ) as post:
            self.assertEqual(classify("the query", questions, timeout=2.0), answers)

        body = post.call_args.kwargs["json"]
        self.assertEqual(body["questions"], questions)
        self.assertEqual(body["state"], "the query")
        self.assertEqual(body["model"], "jev-1.13.0")
        self.assertEqual(post.call_args.kwargs["timeout"], 2.0)

    def test_classify_reports_usage_to_observer(self):
        from agent.jev_client import usage_observer

        seen = []
        body = {"answers": {}, "usage": {"input_tokens": 7, "output_tokens": 2}}
        token = usage_observer.set(lambda *args: seen.append(args))
        try:
            with patch.dict(os.environ, _ENV), patch(
                "agent.jev_client.requests.post", return_value=_response(body)
            ):
                classify("s", {})
        finally:
            usage_observer.reset(token)
        self.assertEqual(seen, [("jev-1.13.0", 7, 2)])

    def test_classify_bad_shape_raises(self):
        for body in ({}, {"answers": None}, {"answers": []}, None):
            with self.subTest(body=body), patch.dict(os.environ, _ENV), patch(
                "agent.jev_client.requests.post", return_value=_response(body)
            ):
                with self.assertRaises(JevError):
                    classify("s", {})

    def test_classify_missing_key_or_floating_model_raises_before_any_request(self):
        cases = (
            {k: v for k, v in _ENV.items() if k != "TYPESAFE_API_KEY"},
            {**_ENV, "JEV_MODEL": "jev-latest"},
        )
        for env in cases:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), patch(
                "agent.jev_client.requests.post"
            ) as post:
                with self.assertRaises(JevError):
                    classify("s", {})
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
