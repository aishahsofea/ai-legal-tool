# Embed English and BM sections separately using text-embedding-3-small

Practitioners query in both English and Bahasa Malaysia. Cross-lingual retrieval (BM query → English chunk) is unreliable even with multilingual embedding models. AGC portal provides both English (lang=BI) and BM (lang=BM) PDFs for most Acts.

Decision: embed both language versions of each section as separate chunks, linked by act_number + section_number + language metadata. BM queries hit BM chunks; English queries hit English chunks. No cross-lingual gap to bridge.

Embedding model: OpenAI text-embedding-3-small (1536 dims). Cost for ~880 Acts × ~50 sections × 2 languages × ~300 tokens ≈ $0.50 total. Straightforward LangChain integration.

## Phased rollout

**v1 pilot (June 2026):** English corpus only. BM and code-switched queries are accepted — text-embedding-3-small has cross-lingual capability so BM queries still retrieve English chunks, with somewhat degraded accuracy. Cited text is always English regardless. This is disclosed to pilot users as a known limitation.

**Before public write-up:** Add BM PDFs and re-embed. Measure retrieval accuracy improvement on BM-heavy queries as a before/after eval narrative.

## Consequences (final design)

- Phase 2 must download both English and BM PDFs (English first for pilot, BM added before write-up)
- Phase 3 must tag each chunk with a `language` field
- pgvector schema requires a `language` column for filtering
- Query router does NOT filter by language before retrieval — practitioners code-switch heavily (e.g. "tolong check Section 14 Evidence Act"), making language detection unreliable
- Retrieval searches both `en` and `bm` chunks simultaneously, ranked by similarity score
- Cited text in responses always uses the English chunk — English is the authoritative version in Malaysian courts
- Response language mirrors the dominant language of the user's query
