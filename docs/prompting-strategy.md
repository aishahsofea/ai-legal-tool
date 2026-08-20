# Prompting Strategy

We split legal research into six small LLM calls instead of one big one: router, contextualize, retrieval (tool-calling agent), synthesiser, grounding_check, conversational. Each has its own small prompt and its own job. This doc lists the ideas we reuse across those prompts. Each bullet points to a real example in the code and an outside source, so this isn't just us patting ourselves on the back.

- **One small model per step, not one big model for everything.** Every node picks its model through an env var, so cheap steps use a cheap model and only the hard steps use a strong one.
  Example: [router.py:26](../agent/nodes/router.py:26) uses `gpt-4.1`, [contextualize.py:31](../agent/nodes/contextualize.py:31) uses `gpt-4.1-mini`.
  Backed by: Anthropic recommends exactly this — "routing easy/common questions to smaller, cost-efficient models... and hard/unusual questions to more capable models" ([Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)). The [RouteLLM paper](https://arxiv.org/pdf/2605.18796) (UC Berkeley, ICLR 2025) measured over 85% cost reduction from this kind of routing with output quality staying near-identical.

- **Ask for structured output, not prose to parse.** Every classification or judgment step returns a typed object, not free text we regex apart. This removes a whole class of "the model phrased it slightly differently" bugs.
  Example: [router.py:30](../agent/nodes/router.py:30), `_RouterOutput`.
  Backed by: OpenAI's own numbers — with Structured Outputs, `gpt-4o-2024-08-06` hit 100% schema-following reliability, versus under 40% for the older model without it ([Introducing Structured Outputs in the API](https://openai.com/index/introducing-structured-outputs-in-the-api/)).

- **Put the reasoning field before the decision field.** Structured output fills fields in the order they're declared. Reasoning after the decision is just an excuse for a choice already made. Reasoning before the decision actually shapes it.
  Example: [router.py:30-36](../agent/nodes/router.py:30) — `reasoning` is declared before `query_type`.
  Backed by: Claude's own docs state the principle directly — "Claude should always output its thinking... without outputting the thought process, no thinking occurs" ([Let Claude think](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/chain-of-thought)).

- **A tool's docstring is a prompt too.** In the tool-calling retrieval agent, the model reads each tool's docstring to decide when to call it. Hard rules go straight into the docstring, not only the system prompt.
  Example: [tools.py:127-144](../agent/retrieval/tools.py:127), the `follow_references` docstring gives three rules: "only after lookup_section or search_statutes"; "never in the same batch"; "one call per run".
  Backed by: Anthropic's tool-building guide says the same — Claude relies heavily on tool descriptions, and even small refinements to them "yield dramatic improvements"; their own team cut error rates and raised completion on SWE-bench purely by rewriting tool descriptions ([Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)).

- **Tell the agent explicitly when to stop.** Left alone, a tool-calling loop can keep searching forever. We cap it in the prompt ("call again ONCE with a reformulated query... do not keep searching indefinitely"). We cap it again in code with a hard recursion limit, so a prompt slip-up can't cause a runaway loop.
  Example: stop language at [agent.py:41-55](../agent/retrieval/agent.py:41), hard cap at [agent.py:39](../agent/retrieval/agent.py:39).
  Backed by: Anthropic's agent-building guide flags this as standard practice — "it's also common to include stopping conditions (such as a maximum number of iterations) to maintain control" ([Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)).

- **Repeat guardrail wording word-for-word across prompts.** When two nodes need the same rule, we copy the exact sentence instead of rephrasing it per node — for example, "practitioner memory is a hint, never legal authority." One wording is easier to audit and update than several near-duplicates that can quietly drift apart.
  Example: compare [synthesiser.py:54](../agent/nodes/synthesiser.py:54) and [conversational.py:56-59](../agent/nodes/conversational.py:56).
  Backed by (weaker source — flagging this honestly): this is closer to general software discipline (DRY, single source of truth) applied to prompts than a named, citable LLM best practice. The clearest write-up we found is a practitioner piece arguing prompt reuse should be exact, not paraphrased, and that a clear source of truth beats rewriting phrasing ([Prompt Engineering in MCP](https://medium.com/tech-ai-made-easy/prompt-engineering-in-mcp-structured-prompts-parameterization-reuse-versioning-and-7dcc598858bd)) — a Medium post, not a primary lab source. Treat this bullet as sound engineering judgment we're applying to prompts, not as an industry-canon rule.

- **Decide fail-open vs fail-closed per node, on purpose.** An LLM call breaking shouldn't always mean the same thing. Each node picks whether a broken call should quietly degrade (fail open) or block the answer (fail closed), with a comment saying why.
  Example: [contextualize.py:76-79](../agent/nodes/contextualize.py:76) fails open to the raw query; [conversational.py:101-104](../agent/nodes/conversational.py:101) fails closed to a static reply.
  Backed by (general engineering, not LLM-specific): this is a standard reliability-engineering trade-off, not something unique to prompting — "fail open prioritizes availability over control, while fail closed prioritizes control over availability" ([Fail Open vs. Fail Closed](https://authzed.com/blog/fail-open)). We're applying a pre-LLM systems-design principle here, not following an AI-specific playbook.

- **Have a second LLM check the first LLM's work.** The node that writes the answer (synthesiser) is separate from the node that checks each claim is actually backed by the cited statute text (grounding_check). Different call, same evidence — the writer can't grade its own homework.
  Example: [grounding_check.py:205-225](../agent/nodes/grounding_check.py:205).
  Backed by: this is Anthropic's named "evaluator-optimizer" workflow — "one LLM call generates a response while another provides evaluation and feedback in a loop" ([Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)). The underlying idea, that a strong LLM judge can score another model's output reliably, is validated in the peer-reviewed ["Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena"](https://arxiv.org/abs/2306.05685) (Zheng et al., NeurIPS 2023), which found LLM judges agree with human preference over 80% of the time — matching human-to-human agreement.

- **Turn on prompt caching for Claude models automatically.** One shared helper decides the message format per provider, so every node gets Claude's prompt caching for free without repeating that logic.
  Example: [llm_factory.py:22-26](../agent/llm_factory.py:22), called from every node's message-building function, including [grounding_check.py:113](../agent/nodes/grounding_check.py:113).
  Backed by: Anthropic's own benchmark for this feature — prompt caching cut response time on a 100K-token example from 11.5s to 2.4s, up to 85% latency reduction for long prompts ([Anthropic prompt caching docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)).

- **Spell out the tie-break, don't leave it implicit.** When two categories could plausibly both fit, the prompt states which one wins and why, instead of hoping the model infers it.
  Example: [router.py:59-61](../agent/nodes/router.py:59) — "only use conversational when the message is UNAMBIGUOUSLY social or meta... when in doubt, classify it as one of the three legal types."
  Backed by: Anthropic's prompt-engineering guidance says to give the model explicit instructions for ambiguous or unexpected input rather than let it guess, to stop it from confidently giving a wrong answer ([Be clear, direct, and detailed](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/be-clear-and-direct)).
