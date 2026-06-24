"""trim_history bounds conversation history before it reaches an LLM.

It trims by a *token budget*, dropping whole oldest turns (user+assistant pairs)
until the remaining history fits. The budget is a soft target with a hard floor:
the most recent turn always survives, even if it alone exceeds the budget.
"""
import unittest

from agent.query_policy import count_tokens, trim_history


def _history(n_turns: int, words_per_msg: int = 4) -> list[dict]:
    """A clean alternating history of n complete turns (2 messages each)."""
    messages: list[dict] = []
    for i in range(n_turns):
        messages.append({"role": "user", "content": f"u{i} " + "x " * words_per_msg})
        messages.append({"role": "assistant", "content": f"a{i} " + "y " * words_per_msg})
    return messages


def _turns_tokens(messages: list[dict]) -> int:
    return sum(count_tokens(m["content"]) for m in messages)


class TrimHistoryTests(unittest.TestCase):
    def test_drops_oldest_whole_turns_to_fit_budget(self):
        history = _history(5)  # 5 equal-sized turns
        # Budget that fits exactly the last 2 turns; a 3rd would overflow.
        budget = _turns_tokens(history[-4:])
        result = trim_history(history, max_tokens=budget)
        self.assertEqual(result, history[-4:])

    def test_newest_turn_survives_even_when_over_budget(self):
        history = _history(1, words_per_msg=80)  # one large turn
        result = trim_history(history, max_tokens=1)  # absurdly tight budget
        self.assertEqual(result, history)

    def test_history_within_budget_returned_whole(self):
        history = _history(3)
        result = trim_history(history, max_tokens=100_000)
        self.assertEqual(result, history)

    def test_never_starts_on_dangling_assistant(self):
        # Malformed input: a leading orphan assistant reply (no invariant relied on).
        history = [
            {"role": "assistant", "content": "orphan"},
            {"role": "user", "content": "q0"},
            {"role": "assistant", "content": "a0"},
        ]
        result = trim_history(history, max_tokens=100_000)
        self.assertEqual(result[0]["role"], "user")

    def test_empty_or_none_history_returns_empty(self):
        self.assertEqual(trim_history([]), [])
        self.assertEqual(trim_history(None), [])


if __name__ == "__main__":
    unittest.main()
