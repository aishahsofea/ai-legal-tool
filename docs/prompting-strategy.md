# Prompting Strategy

We split legal research into six small LLM calls instead of one big one: router, contextualize, retrieval (tool-calling agent), synthesiser, grounding_check, conversational. Each has its own small prompt and its own job. This doc lists the ideas we reuse across those prompts. Each bullet points to a real example in the code.

- **One small model per step, not one big model for everything.** Every node picks its model through an env var, so cheap steps use a cheap model and only the hard steps use a strong one.
  Example: [router.py:26](../agent/nodes/router.py:26) uses `gpt-4.1`, [contextualize.py:31](../agent/nodes/contextualize.py:31) uses `gpt-4.1-mini`.

- **Ask for structured output, not prose to parse.** Every classification or judgment step returns a typed object, not free text we regex apart. This removes a whole class of "the model phrased it slightly differently" bugs.
  Example: [router.py:30](../agent/nodes/router.py:30), `_RouterOutput`.

- **Put the reasoning field before the decision field.** Structured output fills fields in the order they're declared. Reasoning after the decision is just an excuse for a choice already made. Reasoning before the decision actually shapes it.
  Example: [router.py:30-36](../agent/nodes/router.py:30) — `reasoning` is declared before `query_type`.

- **A tool's docstring is a prompt too.** In the tool-calling retrieval agent, the model reads each tool's docstring to decide when to call it. Hard rules go straight into the docstring, not only the system prompt.
  Example: [tools.py:127-144](../agent/retrieval/tools.py:127), the `follow_references` docstring gives three rules: "only after lookup_section or search_statutes"; "never in the same batch"; "one call per run".

- **Tell the agent explicitly when to stop.** Left alone, a tool-calling loop can keep searching forever. We cap it in the prompt ("call again ONCE with a reformulated query... do not keep searching indefinitely"). We cap it again in code with a hard recursion limit, so a prompt slip-up can't cause a runaway loop.
  Example: stop language at [agent.py:41-55](../agent/retrieval/agent.py:41), hard cap at [agent.py:39](../agent/retrieval/agent.py:39).

- **Repeat guardrail wording word-for-word across prompts.** When two nodes need the same rule, we copy the exact sentence instead of rephrasing it per node — for example, "practitioner memory is a hint, never legal authority." One wording is easier to audit and update than several near-duplicates that can quietly drift apart.
  Example: compare [synthesiser.py:54](../agent/nodes/synthesiser.py:54) and [conversational.py:56-59](../agent/nodes/conversational.py:56).

- **Decide fail-open vs fail-closed per node, on purpose.** An LLM call breaking shouldn't always mean the same thing. Each node picks whether a broken call should quietly degrade (fail open) or block the answer (fail closed), with a comment saying why.
  Example: [contextualize.py:76-79](../agent/nodes/contextualize.py:76) fails open to the raw query; [conversational.py:101-104](../agent/nodes/conversational.py:101) fails closed to a static reply.

- **Have a second LLM check the first LLM's work.** The node that writes the answer (synthesiser) is separate from the node that checks each claim is actually backed by the cited statute text (grounding_check). Different call, same evidence — the writer can't grade its own homework.
  Example: [grounding_check.py:205-225](../agent/nodes/grounding_check.py:205).

- **Turn on prompt caching for Claude models automatically.** One shared helper decides the message format per provider, so every node gets Claude's prompt caching for free without repeating that logic.
  Example: [llm_factory.py:22-26](../agent/llm_factory.py:22), called from every node's message-building function, including [grounding_check.py:113](../agent/nodes/grounding_check.py:113).

- **Spell out the tie-break, don't leave it implicit.** When two categories could plausibly both fit, the prompt states which one wins and why, instead of hoping the model infers it.
  Example: [router.py:59-61](../agent/nodes/router.py:59) — "only use conversational when the message is UNAMBIGUOUSLY social or meta... when in doubt, classify it as one of the three legal types."
