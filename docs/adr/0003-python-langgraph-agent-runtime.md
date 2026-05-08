# Agent logic lives in Python (LangGraph), not TypeScript

The project owner is a Senior Frontend Engineer with a TypeScript background. However, the agent engineering skills to demonstrate for hiring (tool orchestration, state machines, supervision layers, eval harnesses) are substantially better supported in the Python ecosystem: LangGraph, LangSmith, and the broader LangChain tooling are Python-first. Running agent logic in TypeScript (Mastra/Vercel AI SDK) would fragment tracing and evals across two runtimes and lose the depth of LangGraph's graph primitives.

Decision: all agent logic, tools, tracing, and evals live in Python. A TypeScript/Next.js UI is a thin layer on top, sufficient to demonstrate frontend capability without splitting the agent runtime.
