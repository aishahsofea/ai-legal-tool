# Prompting Strategy

This doc is about the words we send the model, and nothing else. Graph shape,
which model each node uses, and what happens when a call fails are in
[CONTRIBUTING.md](../CONTRIBUTING.md#model-overrides) and [README.md](../README.md).

Legal research runs as six LLM calls — router, contextualize, retrieval
(tool-calling agent), synthesiser, grounding_check, conversational — and each one
has its own prompt. Below are the prompting ideas we reuse across them. Each has a
real example in the code and an outside source.

- **One prompt per step, not one prompt for everything.** Each node's prompt does a
  single job, and the next node reads its output. A prompt that only has to classify
  a query is easier to write, test, and fix than one that also has to search, cite,
  and check itself.
  Example: the six node prompts, one per file in [agent/nodes/](../agent/nodes/) plus
  [agent/retrieval/agent.py](../agent/retrieval/agent.py).
  Backed by: Anthropic calls this prompt chaining — "decomposes a task into a sequence
  of steps, where each LLM call processes the output of the previous one"
  ([Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)).
  Their current prompting guide keeps it for the case we're in: "still useful when you
  need to inspect intermediate outputs or enforce a specific pipeline structure"
  ([Chain complex prompts](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#chain-complex-prompts)).

- **Ask for structured output, not prose to parse.** Every classification or judgment
  step returns a typed object, not free text we regex apart. This removes a whole class
  of "the model phrased it slightly differently" bugs.
  Example: [router.py:30](../agent/nodes/router.py:30), `_RouterOutput`.
  Backed by: OpenAI's own docs — "only Structured Outputs ensure schema adherence"
  ([Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)).

- **Put the reasoning field before the decision field.** Structured output fills fields
  in the order they're declared. Reasoning after the decision is an excuse for a choice
  already made. Reasoning before it actually shapes it.
  Example: [router.py:30-36](../agent/nodes/router.py:30) — `reasoning` is declared
  before `query_type`.
  Example: [grounding_check.py:30-45](../agent/nodes/grounding_check.py:30) — the judge
  declares `quote`, then `reason`, then `support`. It has to find the passage in the cited
  section before it labels the claim, instead of labelling first and hunting for a quote
  that fits. The system prompt names the same order in words, because the field order alone
  is easy for a model to read past.
  Backed by: the original chain-of-thought paper — "generating a chain of thought — a
  series of intermediate reasoning steps — significantly improves the ability of large
  language models to perform complex reasoning" (Wei et al.,
  ["Chain-of-Thought Prompting Elicits Reasoning in Large Language Models"](https://arxiv.org/abs/2201.11903),
  NeurIPS 2022). The gain comes from reasoning produced *before* the answer, which is
  exactly what field order buys us here.

- **Long data first, the question last.** In a prompt that mixes retrieved text with a short
  question, put the text at the top. Put the question at the bottom, next to the instruction
  that acts on it. A question stranded above eight statute
  sections is a question the model has to hold in mind while it reads past everything else.
  Example: [synthesiser.py:118-126](../agent/nodes/synthesiser.py:118) — retrieved sections,
  then history, then preferences, then the query and "Answer the query using only the
  sections above". Same order in the grounding judge's payload at
  [grounding_check.py:126](../agent/nodes/grounding_check.py:126): cited sources first, the
  answer under judgment last.
  Backed by: Anthropic's long-context guidance — "Place your long documents and inputs near
  the top of your prompt, above your query, instructions, and examples", and "Queries at the
  end can improve response quality by up to 30 percent in tests"
  ([Long context prompting](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#long-context-prompting)).

- **A tool's docstring is a prompt too.** In the tool-calling retrieval agent, the model
  reads each tool's docstring to decide when to call it. Hard rules go straight into the
  docstring, not only the system prompt.
  Example: [tools.py:127-144](../agent/retrieval/tools.py:127), the `follow_references`
  docstring gives three rules: only after `lookup_section` or `search_statutes`; never
  for an ordinary lookup; one call per retrieval run.
  Backed by: Anthropic's tool-building guide — "Even small refinements to tool
  descriptions can yield dramatic improvements." Their own team hit state of the art on
  SWE-bench Verified "after we made precise refinements to tool descriptions, dramatically
  reducing error rates and improving task completion"
  ([Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)).

- **Tell the agent explicitly when to stop.** Left alone, a tool-calling loop can keep
  searching forever. The prompt caps it — "call `search_statutes` again ONCE with a
  reformulated query... Do not keep searching indefinitely" — and a hard recursion limit
  in code catches a prompt slip-up.
  Example: stop language at [agent.py:41-55](../agent/retrieval/agent.py:41), hard cap at
  [agent.py:39](../agent/retrieval/agent.py:39).
  Backed by: Anthropic's agent guide calls this standard — "it's also common to include
  stopping conditions (such as a maximum number of iterations) to maintain control"
  ([Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)).

- **Spell out the tie-break, don't leave it implicit.** When two categories could both
  fit, the prompt says which one wins and why, instead of hoping the model infers it.
  Example: [router.py:59-61](../agent/nodes/router.py:59) — "only use conversational when
  the message is UNAMBIGUOUSLY social or meta... When in doubt... classify it as one of
  the three legal types."
  Backed by: Anthropic's guidance is to be explicit rather than let the model infer —
  "Claude responds well to clear, explicit instructions... Think of Claude as a brilliant
  but new employee who lacks context on your norms and workflows"
  ([Be clear and direct](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#be-clear-and-direct)).

- **Name the shape you want, not only the shape you don't.** A ban tells the model which
  words to avoid and leaves it to invent the replacement. Showing the wanted form first, and
  the ban second, gives it somewhere to go.
  Example: [synthesiser.py:55](../agent/nodes/synthesiser.py:55) — "Write about the
  provision, not about the reader" with two model phrasings, then the banned second-person
  phrases. The rule also says what happens if it slips: the supervisor rejects those phrases
  and forces a re-draft. A model that knows the cost reframes on the first pass. The prompt
  lists every phrase the supervisor rejects. An earlier, partial list left the missing
  phrases free to appear and then fail the check.
  Backed by: Anthropic's formatting guidance — "Tell Claude what to do instead of what not to
  do", with the worked example of replacing "Do not use markdown in your response" with "Your
  response should be composed of smoothly flowing prose paragraphs"
  ([Control the format of responses](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#control-the-format-of-responses)).

- **Put the caveat on the data, not only in the system prompt.** Recalled practitioner memory
  reaches the model already labelled — "Known practitioner preferences (framing only, not legal
  authority)". The caveat sits on the block being read, not forty lines above it.
  Two nodes read that memory. A prompt inherits nothing from the node before it, so each states
  the caveat again in its own system prompt. The label and the caveat sentence both come from
  [query_policy.py](../agent/query_policy.py), as `preferences_block` and
  `memory_soft_context_rule`, so they can't drift. See
  [synthesiser.py:60](../agent/nodes/synthesiser.py:60) and
  [conversational.py:60-62](../agent/nodes/conversational.py:60). One clause is a parameter,
  because the ranking genuinely differs: in the synthesiser, preferences lose to the retrieved
  sections; in small talk, they lose to the hard guardrails. Hand-written copies said it in
  different words for a while. That is how one node ends up looser than the other and nobody
  notices. `tests/test_memory_caveat_convergence.py` pins it.
  Backed by: Anthropic's prompt-structure guidance — wrapping "each type of content in its own tag
  (for example, `<instructions>`, `<context>`, `<input>`) reduces misinterpretation", and "Use
  consistent, descriptive tag names across your prompts"
  ([Structure prompts with XML tags](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#structure-prompts-with-xml-tags)).
  We label with a header line rather than a tag, which is the weaker form of the same idea. Their
  context-engineering post names the failure this avoids: guidance that "falsely assumes shared
  context"
  ([Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).
