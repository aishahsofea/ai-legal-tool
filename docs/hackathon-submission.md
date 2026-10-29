# About the project

## Inspiration

Malaysian lawyers, pupils and paralegals look up statutes on the AGC portal. There, an Act is a PDF, and some PDFs are scans. A reprint can be out of date the moment an amendment passes. Nothing on the page says so.

[One or two sentences in your own voice: why this problem, who you watched struggle with it.]

An AI assistant could save that search time. But a legal tool that sounds sure and cites nothing is worse than no tool. So the goal was narrow: answer from the statute text, cite the exact page, say when the Act may be out of date, and refuse to give legal advice.

## What it does

You ask about Malaysian legislation in English, Bahasa Malaysia, or a mix of both. You get an answer with citations. Each citation is an Act, a section and a PDF page. A verified citation opens a Citation Receipt: the official PDF at that page, with the supporting quote highlighted. If the match is uncertain, the app shows no highlight rather than guess, and links to the official source instead.

Each cited Act carries a label: repealed, superseded, current as indexed, or unknown. A client-specific question ("am I liable...") is not answered. It goes to a human lawyer.

## How we built it

The agent is a LangGraph graph. Every query passes through these steps:

1. Route the query: legal question, small talk, client-specific, or too vague.
2. Rewrite a follow-up into a standalone query.
3. Retrieve. A ReAct agent chooses between semantic search and exact section lookup, and searches again when hits are weak.
4. Draft the answer with citations.
5. Reject any citation that is not in the retrieved sources.
6. Check each claim against the sources, and keep only claims with a verified quote.
7. Label each cited Act with its currency.
8. Enforce policy: no advice phrasing, a disclaimer, one retry, then fail closed.

The corpus is section-level chunks scraped from the AGC portal, stored in Postgres with pgvector. PDFs live on Cloudflare R2. The API is FastAPI on Railway and the chat UI is Next.js on Vercel.

Every chat model runs on open-weights NVIDIA Nemotron, served by Nebius Token Factory:

- Nemotron-3.5-Lightning (30B) handles the light steps: classifying, rewriting follow-ups, small talk and memory extraction.
- Nemotron-3-Ultra (550B) searches the statutes, writes the cited answer, and runs the grounding check.

The chat UI has a PROCESS panel that names the model behind each step. Tavily powers web search for Commentary Notes, which are shown beside the answer but never cited as law.

We measured quality with a hand-validated benchmark of 79 cases, 40 of them in Bahasa Malaysia or mixed language. Deterministic checks and an LLM judge run in CI.

## Challenges

**Scanned Acts.** Vision models on Nebius read a scanned page correctly but invented the word positions, so highlights landed in the wrong place. Local Tesseract gives exact, repeatable word coordinates at no cost, so receipts use that.

**A language check that could never fail.** Our test for "answer is in Bahasa Malaysia" matched Malay words as substrings. "dan" sits inside the English word "abundant". Fixing it changed our measured BM results.

**A parser that read the wrong Act.** The Contracts Act 1950 has an unusual enacting clause that matched none of our patterns. The parser found the "BE IT ENACTED" of an amending Act reprinted on page 87 and treated the real Act as front matter.

**Nemotron on Nebius.**

- Ultra gave wrong answers on prompt-cache hits for repeated prompts. Giving each call a unique salt fixed it.
- Nebius cut reasoning off at its default `max_tokens` of 8,192. Raising the limit fixed it.

**Retrieval in Bahasa Malaysia.** Retrieval ranks the expected section first for about 61% of 59 benchmark questions: 41% in Bahasa Malaysia and 74% in mixed language. We state this in the README rather than hide it.

## What we learned

Measure the retrieval step by itself. We report top-1 retrieval accuracy as

$$
\text{top-1} = \frac{\text{questions where the expected section ranks first}}{N}, \qquad N = 59
$$

so a weak retriever shows up as a number and is not hidden behind a fluent answer.

Other lessons:

- A legal answer is only as trustworthy as its checks. Validating citations structurally, and failing closed when a violation survives one retry, mattered more than prompt wording.
- Switching the whole chat stack to Nemotron was cheap because models are config, not code. Lightning cut per-step cost about 3x on light steps, but those steps are a small share of the total, so the overall saving was within noise.
- A check that cannot fail looks like a passing check. Test your tests.

## What's next

- Fix Bahasa Malaysia retrieval, and load the corrected BM section splitting into the corpus.
- Add Malay expected answers to the benchmark so BM answers are not judged against English ones.
- Review the 23 scanned documents from the last re-extraction.
- Close the known gaps listed in the README: a missing chunk for section 60A of the Employment Act, and a synthesiser crash when the model hits its reasoning limit.

**Built with:** LangGraph, FastAPI, Next.js, Postgres, pgvector, NVIDIA Nemotron, Nebius Token Factory, Tavily, Cloudflare R2, Railway, Vercel, Supabase, OpenAI embeddings.
