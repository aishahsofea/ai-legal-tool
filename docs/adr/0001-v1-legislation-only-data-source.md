# v1 data source is legislation only (no case law)

The agent's goal includes both legislation and case law. Malaysian case law is primarily behind paywalls (CLJ Legal, eLaw, LexisNexis MY). The only free source with meaningful coverage is CommonLII (commonlii.org/my/), but its robots.txt blocks AI crawler bots and declares `ai-train=no`, making scraping legally ambiguous. lom.agc.gov.my is a government public portal with no such restrictions and provides ~1,280 Acts with full PDF reprints — a complete, scrapable, genuinely useful dataset.

v1 therefore covers legislation only. Case law via CommonLII is deferred to v2, at which point the robots.txt ambiguity (training vs. RAG retrieval) and coverage gaps should be re-evaluated.

## Considered Options

- **CommonLII for case law in v1** — rejected: robots.txt ambiguity, incomplete coverage, would delay shipping a working agent
- **Paid sources (CLJ/eLaw)** — rejected: no free tier, not viable for a solo portfolio project
