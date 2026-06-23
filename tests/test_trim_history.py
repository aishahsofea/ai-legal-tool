"""trim_history bounds conversation history before it reaches an LLM.

It slices in whole *turns* (user+assistant pairs), not raw messages, so the
limit is honest about its unit and a slice can never begin on a dangling
assistant reply.
"""
import unittest

from agent.query_policy import trim_history


def _history(n_turns: int) -> list[dict]:
    """A clean alternating history of n complete turns (2 messages each)."""
    messages: list[dict] = []
    for i in range(n_turns):
        messages.append({"role": "user", "content": f"q{i}"})
        messages.append({"role": "assistant", "content": f"a{i}"})
    return messages


class TrimHistoryTests(unittest.TestCase):
    def test_keeps_last_n_whole_turns(self):
        history = _history(5)  # 10 messages
        result = trim_history(history, max_turns=2)
        self.assertEqual(result, history[-4:])  # 2 turns == 4 messages

    def test_never_starts_on_dangling_assistant(self):
        # Malformed input: a leading orphan assistant reply (no invariant relied on).
        history = [
            {"role": "assistant", "content": "orphan"},
            {"role": "user", "content": "q0"},
            {"role": "assistant", "content": "a0"},
        ]
        result = trim_history(history, max_turns=5)
        self.assertEqual(result[0]["role"], "user")

    def test_empty_or_none_history_returns_empty(self):
        self.assertEqual(trim_history([]), [])
        self.assertEqual(trim_history(None), [])

    def test_fewer_turns_than_limit_returns_all(self):
        history = _history(2)
        self.assertEqual(trim_history(history, max_turns=5), history)

    def test_default_limit_keeps_three_turns(self):
        history = _history(10)
        # The constant is honest about its unit: 3 means 3 turns (6 messages).
        self.assertEqual(trim_history(history), history[-6:])


if __name__ == "__main__":
    unittest.main()
