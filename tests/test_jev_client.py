import os
import unittest
from unittest.mock import MagicMock, patch

import requests

from agent.jev_client import JevError, supported_probability

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
            self.assertEqual(supported_probability("the claim", "the source"), 0.93)

        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "jev-1.13.0")
        self.assertIn("the claim", body["state"])
        self.assertIn("the source", body["state"])
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer test-key"})
        self.assertIsNotNone(post.call_args.kwargs["timeout"])

    def test_timeout_raises(self):
        with patch.dict(os.environ, _ENV), patch(
            "agent.jev_client.requests.post", side_effect=requests.exceptions.Timeout()
        ):
            with self.assertRaises(JevError):
                supported_probability("c", "s")

    def test_bad_status_raises(self):
        error = requests.exceptions.HTTPError("500")
        with patch.dict(os.environ, _ENV), patch(
            "agent.jev_client.requests.post", return_value=_response({}, status_error=error)
        ):
            with self.assertRaises(JevError):
                supported_probability("c", "s")

    def test_malformed_response_raises(self):
        for body in ({}, {"answers": {"verdict": {"probabilities": {}}}}, {"answers": None}):
            with self.subTest(body=body), patch.dict(os.environ, _ENV), patch(
                "agent.jev_client.requests.post", return_value=_response(body)
            ):
                with self.assertRaises(JevError):
                    supported_probability("c", "s")

    def test_out_of_range_probability_raises(self):
        with patch.dict(os.environ, _ENV), patch(
            "agent.jev_client.requests.post", return_value=_ok(1.5)
        ):
            with self.assertRaises(JevError):
                supported_probability("c", "s")

    def test_jev_latest_is_rejected_before_any_request(self):
        with patch.dict(os.environ, {**_ENV, "JEV_MODEL": "jev-latest"}), patch(
            "agent.jev_client.requests.post"
        ) as post:
            with self.assertRaises(JevError):
                supported_probability("c", "s")
        post.assert_not_called()

    def test_missing_model_or_key_raises_before_any_request(self):
        for drop in ("JEV_MODEL", "TYPESAFE_API_KEY"):
            env = {k: v for k, v in _ENV.items() if k != drop}
            with self.subTest(missing=drop), patch.dict(os.environ, env, clear=True), patch(
                "agent.jev_client.requests.post"
            ) as post:
                with self.assertRaises(JevError):
                    supported_probability("c", "s")
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
