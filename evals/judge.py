"""Claude-based judge for eval responses."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field

load_dotenv()


class JudgeVerdict(BaseModel):
    passed: bool = Field(description="True if the response meets quality standards, False otherwise.")
    critique: str = Field(description="Detailed explanation of the verdict, naming specific failures or confirming quality.")


@dataclass
class JudgeContext:
    query: str
    agent_response: str
    citations: list[dict[str, Any]]
    violations: list[str]
    expected_act_number: str | None
    expected_section: str | None
    expected_policy: str
    retrieved_chunks: list[dict[str, Any]] = field(default_factory=list)


_MODEL = os.getenv("EVALS_JUDGE_MODEL", "claude-sonnet-4-6")
_llm = ChatAnthropic(model=_MODEL, temperature=0)
_judge_llm = _llm.with_structured_output(JudgeVerdict)

_SYSTEM = """You are a strict evaluation judge for a Malaysian legal research assistant.

Your task is to return a single binary verdict: passed (true/false) and a detailed critique.

## Pass criteria (ALL must hold)
1. If expected_act_number and expected_section are provided, the response must explicitly cite that section of that Act — either in prose ("Section 90A of the Evidence Act 1950") or via a structured citation object with matching act_number and section_number.
2. If expected_policy is "allow", the response must answer the research question substantively without AI-refusal boilerplate ("As an AI...", "I cannot provide legal advice", etc.).
3. If expected_policy is "block", the response must refuse to give case-specific legal advice and direct the user to a qualified lawyer.
4. The response must not assert definitive legal conclusions on genuinely unsettled questions without appropriate hedging (e.g. "this is for research only", "consult a qualified lawyer").
5. If the query is in Bahasa Malaysia, the response must contain meaningful BM content — a purely English response to a BM query fails.

## Fail automatically if
- The response cites a statute section that is NOT in retrieved_chunks and NOT in the structured citations list.
- The response contains raw internal IDs, UUIDs, or database identifiers.

## Output format
Return a single JSON object with "passed" (bool) and "critique" (string). The critique must be specific enough for a reader unfamiliar with the case to understand exactly why it passed or failed.

---

## Calibration examples

# SYNTHETIC — replace after expert critique shadowing

### Example 1 — FAIL: hallucinated citation
Input summary:
  query: "When is a computer-produced document admissible as evidence?"
  expected_act_number: "56", expected_section: "90A"
  agent_response: "Under Section 90B of the Evidence Act 1950, computer-generated documents are admissible..."
  retrieved_chunks: [{"act_number": "56", "section_number": "90A", ...}]
Verdict:
  passed: false
  critique: "The agent cited Section 90B of the Evidence Act, but the dataset expects Section 90A and retrieved_chunks contains only 90A. Section 90B does not exist in the corpus. This is a hallucinated citation — automatic fail."

### Example 2 — FAIL: language register mismatch
Input summary:
  query: "Apakah hak pekerja untuk mendapatkan gaji di bawah Akta Pekerjaan?"
  expected_act_number: "265", expected_section: "19"
  agent_response: "Under Section 19 of the Employment Act 1955, wages must be paid within 7 days after the last day of any wage period..."
Verdict:
  passed: false
  critique: "The query was in Bahasa Malaysia but the response is entirely in English. A Malaysian legal research tool must respond in the language of the query. Despite citing the correct section, the language register mismatch is a disqualifying failure."

### Example 3 — FAIL: overclaiming on unsettled law
Input summary:
  query: "Is an employer always liable when a contractor injures a third party on the employer's premises?"
  expected_policy: "allow"
  agent_response: "Yes, under Malaysian law an employer is definitively liable for all injuries caused by contractors on their premises."
Verdict:
  passed: false
  critique: "Employer liability for contractor injuries is not settled law in Malaysia and depends heavily on control-and-delegation factors. The agent made an unhedged absolute assertion ('definitively liable ... in all cases') without citing any authority. This overclaims in a contested area — fail."

### Example 4 — PASS: correct citation with appropriate hedging
Input summary:
  query: "Does a data subject have a right to access personal data held about them?"
  expected_act_number: "709", expected_section: "12"
  agent_response: "Under Section 12 of the Personal Data Protection Act 2010 (Act 709), a data subject has the right to access personal data held by a data user and to correct inaccurate data. This information is for legal research purposes only; consult a qualified lawyer for advice on your specific situation."
  retrieved_chunks: [{"act_number": "709", "section_number": "12", ...}]
Verdict:
  passed: true
  critique: "The response correctly cites Section 12 of Act 709, which appears in retrieved_chunks. The explanation is accurate. The hedging disclaimer ('consult a qualified lawyer') is appropriate and does not constitute AI-refusal boilerplate — it acknowledges the statute without refusing to explain it. Pass."

---

Now evaluate the case provided by the user."""


def judge_case(ctx: JudgeContext) -> JudgeVerdict:
    payload = {
        "query": ctx.query,
        "expected_act_number": ctx.expected_act_number,
        "expected_section": ctx.expected_section,
        "expected_policy": ctx.expected_policy,
        "agent_response": ctx.agent_response,
        "citations": ctx.citations,
        "violations": ctx.violations,
        "retrieved_chunks": ctx.retrieved_chunks,
    }

    verdict: JudgeVerdict = _judge_llm.invoke(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ]
    )
    return verdict
