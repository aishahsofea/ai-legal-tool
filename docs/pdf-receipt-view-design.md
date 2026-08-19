# PDF Citation Receipt View — Implementation Record

> **Historical / superseded.** This describes the original five-Act UI pilot. For current corpus-wide provenance, storage, migration, and rollout, see [corpus-receipts.md](corpus-receipts.md). Kept here as a record of what was built and why — don't treat its pilot-only scope as current architecture.

## 1. What this feature does

Citations currently link out to the government's PDF. This replaces that with an in-app **Citation Receipt**: click a citation, the answer stays visible, and a drawer opens showing the exact PDF snapshot the answer was generated from — scrolled to the right page, with the supporting text highlighted. A separate link to the official AGC source stays available for practitioners who want to check the live original.

It's a trust feature, so two rules override everything else: never imply a match is exact when it isn't, and never substitute a different PDF reprint just because it's easier to embed.

## 2. Goals

**G1 — Exact source provenance.** The five pilot PDFs are byte-for-byte identical to the files the chunks and `page_number`s were extracted from. They're tracked as immutable assets in a manifest with hashes. If a file's hash doesn't match the manifest, don't serve it — ever.

**G2 — Backward-compatible citation contract.** Citations gain an optional `receipt` field. It carries an immutable `document_id` and zero or more validated Evidence Spans. We don't attach full chunks or bounding boxes to every answer — only pilot citations get a receipt.

**G3 — Verified evidence extraction.** The grounding-check call produces a short supporting quote per claim. We don't trust the model's word for it — application code independently verifies the claim appears in the answer *and* the quote appears in the retrieved chunk before it's allowed to become a highlight.

**G4 — Lazy, deterministic passage location.** A FastAPI router serves the PDF and, on request, locates an Evidence Span using PyMuPDF with strict normalized token matching. No fuzzy, semantic, or "close enough" matching is allowed to produce a highlight.

**G5 — In-app evidence viewer.** Desktop: a right-hand drawer, answer and receipt visible together. Mobile: full-screen sheet. Renders one page at a time, opens on the matched (or fallback) page, draws the highlight, and has close / prev / next / page-count / zoom controls.

**G6 — Honest failure behavior.** Receipt failures never take down the underlying legal answer. Every failure mode — missing evidence, `not_found`, `ambiguous`, corrupt asset, API/render error — has its own explicit UI state, and none of them draw an uncertain highlight. Where possible we still open the exact document at the stored section-start page, with the AGC link intact.

**G7 — Both live citation surfaces wired up.** In-prose citation links (`rehypeCitationLinks`) and the inline source row's "Open full act" action both open the shared viewer. Source-map anchors keep navigating within the answer as before. Unused legacy components don't need wiring.

**G8 — Five-Act pilot, deployed.** Receipts work for Acts 56, 265, 574, 709, 777. Everything else falls back to the existing remote-AGC behavior. Deployed Railway API serves the five tracked assets; deployed frontend loads them.

**G9 — Accessible.** Proper dialog semantics, accessible name, deterministic focus in/out, Escape to close, labeled controls. The selected claim and quote are available as text, not just color. Loading/error states are announced, focus never gets stranded.

**G10 — Verified + documented.** Backend tests, contract tests, frontend interaction tests, lint, production build, and a manual smoke pass on the deployed app all pass. Since this touches the API contract and frontend architecture, update `README.md`, `CONTRIBUTING.md`, and `CONTEXT.md` in the same change. Frozen decision records stay untouched.

## 3. What "done" means

Phases 1–3 (section 13) are sequential — all three have to land, not just the tracer bullet. Done means: G1–G10 all satisfied, every command in section 15 passes, every scenario in section 16 has recorded evidence, the pilot assets are actually in the deployed build, and the deployed smoke check (not just localhost) passes. Nothing gets quietly punted to "future work." If a credential or deploy permission is genuinely unavailable, say so and report the specific blocked gate — don't call it done, and don't wander into the non-goals in section 18 to stay busy.

## 4. Terminology

- **Citation Receipt** — the in-app verification experience opened from a citation.
- **Receipt Document** — the immutable PDF whose exact bytes were used during extraction.
- **Evidence Span** — a claim plus a short supporting quote that's passed deterministic validation against the answer and the retrieved chunk.
- **Locator Result** — the physical page(s) and word rectangles found for one Evidence Span.
- **Official Source Link** — the existing remote AGC `pdf_url`. A separate escape hatch, not the Receipt Document.
- **Section-start page** — the existing citation `page_number`. Marks where extraction first found the section; a long section can have supporting text on later pages.

Use these terms consistently in code and docs. Don't call the remote AGC PDF "the receipt," and don't call a section-start page an "evidence page" until the locator has actually matched it.

## 5. Codebase facts to work from

- `agent/state.py` defines `Citation` with `act_number`, `act_title`, `section_number`, `pdf_url`, `page_number`.
- `agent/nodes/synthesiser.py:_finalise()` strips retrieved `content` when building citations — on purpose.
- `agent/retrieval/search.py:attach_pdf_urls()` attaches the remote metadata URL.
- `scraper/step4_extract.py` computed `page_number` against `data/pdfs/en/{act}.pdf` with PyMuPDF.
- The extractor strips and rejoins lines, so stored chunk text is *not* a byte-for-byte substring of a browser PDF text layer.
- A section can span multiple physical pages; the stored `page_number` is just where it started.
- `agent/nodes/grounding_check.py` already identifies claims, cited Act/section pairs, and support labels — it just doesn't retain supporting quotes yet.
- PyMuPDF is already a backend dependency.
- Full local PDF directory: 624 files, ~587 MB, gitignored. The five pilot files: ~7.7 MB total.
- `api/evals.py` is the router-per-feature precedent `api/main.py` follows.
- The live workspace renders sources inline in `frontend/components/locus-workspace/Messages.tsx`.
- `frontend/components/CitationCard.tsx` and `frontend/components/locus-workspace/SourcesPanel.tsx` still exist but aren't rendered by the current workspace.
- `frontend/components/locus-workspace/rehypeCitationLinks.ts` builds HAST anchors for in-prose section/Act mentions.
- No PDF rendering package installed yet. Frontend is Next.js 16.2.6 / React 19.2.4.
- `frontend/AGENTS.md` requires reading the installed Next.js guidance under `frontend/node_modules/next/dist/docs/` before touching frontend code.

Before implementing: read root `AGENTS.md`, `frontend/AGENTS.md`, the files above, and the relevant tests. Don't stomp on unrelated changes already in the dirty worktree.

## 6. Architectural decisions

**D1 — Bytes, not URLs, define correctness.** The Receipt Document is the exact local extraction PDF — not whatever the remote AGC URL happens to serve when clicked. Remote content can change under a stable URL, and pagination isn't a stable identifier across files. AGC link stays as a separate, clearly labeled action.

**D2 — Track five extraction PDFs, nothing more.** Reuse the exact files in `data/pdfs/en/` as Receipt Documents for the hackathon. Keep the manifest next to the PDF tree, with narrow `.gitignore` exceptions so only the manifest and five approved PDFs get committed:

```text
data/pdfs/
├── manifest.json
└── en/
    ├── 56.pdf
    ├── 265.pdf
    ├── 574.pdf
    ├── 709.pdf
    └── 777.pdf
```

Don't unignore the rest of the corpus, don't duplicate PDFs into a receipt-specific directory, don't add object storage for this pilot. If repo rules block committing these binaries, use whatever deployment-asset mechanism preserves the exact hashes below — never fall back to a silent live download.

**D3 — `document_id` is the real identifier, not Act number.** An Act can have multiple reprints, so Act number alone isn't enough. `document_id` must point to one specific manifest entry and change whenever the bytes change. It's an opaque API identifier — file paths only ever get resolved through the loaded manifest.

Suggested IDs: `act-56-reprint-2017-c11400ad`, `act-265-reprint-2023-6fec2f07`, `act-574-reprint-2023-89c0f2f6`, `act-709-reprint-2016-fff5cf24`, `act-777-reprint-2022-b32cc5eb`.

**D4 — Keep the citation payload lean.** Existing citation fields and `pdf_url` meaning stay as-is; we just add an optional nested `receipt`. No full chunks, PDF bytes, or rectangles on every answer:

```jsonc
{
  "act_number": "56",
  "act_title": "EVIDENCE ACT 1950",
  "section_number": "90A",
  "pdf_url": "https://lom.agc.gov.my/...",
  "page_number": 72,
  "receipt": {
    "document_id": "act-56-reprint-2017-c11400ad",
    "evidence": [
      {
        "claim": "Computer-produced documents may be admissible...",
        "quote": "In any criminal or civil proceeding..."
      }
    ]
  }
}
```

For a pilot citation, `receipt` is present even when evidence extraction fails — just with `evidence: []`, so page-only verification still works. For a non-pilot citation, `receipt` is absent entirely and the existing AGC-link behavior is unchanged.

**D5 — Derive Evidence Spans inside the existing grounding check.** Extend its structured output instead of adding another LLM call or having the synthesiser vouch for itself. Per supported claim, ask for one short contiguous quote plus the existing Act/section identifiers.

An Evidence Span only becomes valid once deterministic code confirms all of:
1. `support == "supported"`
2. the Act/section pair exists in both the structured citations and retrieved chunks
3. the normalized claim occurs in the draft answer
4. the normalized quote occurs in the matching retrieved chunk
5. the quote is non-empty and under the configured length cap

Group valid spans under their citation in answer order, dedupe exact repeats. `partial`/`unsupported` claims get no highlight evidence. Keep the existing grounding retry/violation behavior as-is unless there's a proven separate bug — this feature isn't a backdoor to redefine the safety policy. If the grounding call fails open, still attach the pilot `document_id` deterministically with an empty evidence list, so the answer keeps flowing.

**D6 — Locate boxes lazily, per click.** No corpus-wide re-extraction needed. Boxes get computed on demand against the selected document, using the same extraction library and exact bytes as the original pipeline — which also makes matching independently testable on the backend.

**D7 — Normalize strictly, never fuzzy-match.** Allowed normalization: Unicode NFKC, case folding, whitespace collapsing, soft-hyphen removal, canonical apostrophe/dash treatment, surrounding punctuation, and line-end dehyphenation where the word-coordinate structure proves the break. After normalization, the match must still be a contiguous exact token sequence. No edit-distance thresholds, embeddings, semantic similarity, or "best guess" matching — those can be future diagnostics, never proof.

**D8 — Fail open on the UI, fail closed on highlights.** A receipt is a nice-to-have verification layer, so its failure can't take the legal answer down with it. A highlight is a trust claim, so any uncertainty means no highlight — but the UI still explains what happened and offers the page + Official Source Link where it can.

**D9 — React-PDF, bundled worker, no CDN.** Use the current `react-pdf` line compatible with React 19, matching `pdfjs-dist` version. Client-only module, following both the installed Next.js 16 guidance and React-PDF's worker guidance — worker ships with the app, not fetched from a third-party CDN at runtime. Render one page at a time; since the backend already returns normalized rectangles, no frontend PDF text search is needed. Overlay rectangles in the page wrapper using percentage coordinates.

**D10 — Responsive drawer, not a modal.** Desktop: right-side drawer, answer stays visible. Narrow screens: full-screen sheet. A modal that covers the answer defeats the point — side-by-side comparison is the whole value here.

**D11 — Section-level links for the pilot, nothing fancier.** No explicit claim markers in generated Markdown. When a section has multiple Evidence Spans, default to the first verified one and show a compact, keyboard-accessible list to pick another — selecting one re-runs/reuses its locator result and updates the highlight.

**D12 — Wire only the two live surfaces.** One receipt-viewer state at the workspace level, routed through a single `openReceipt(citation, evidenceIndex?)` action. Don't spend hackathon time wiring or deleting the unused `CitationCard`/`SourcesPanel`.

## 7. Pilot manifest

Minimum manifest fields: schema version, `document_id`, Act number/title/language, relative asset path, SHA-256, byte size, page count, source URL (from Act metadata), timeline date/type, and metadata scrape timestamp. The source URL is provenance, not a promise the URL still serves the same bytes — SHA-256 is what actually identifies the Receipt Document.

| Act | Title | Bytes | Pages | SHA-256 | Metadata timeline |
|---|---|---:|---:|---|---|
| 56 | Evidence Act 1950 | 771,581 | 120 | `c11400ad1b0a9941919d7328c60fc1c2b49fb2788671bf9697c2923364c96d07` | REPRINT ONLINE, 23 May 2017 |
| 265 | Employment Act 1955 | 1,309,405 | 127 | `6fec2f07b49d8f381851906781259b1e09a2152db8dcf1599ab77a592eae100b` | REPRINT ONLINE, 1 Feb 2023 |
| 574 | Penal Code | 1,736,926 | 326 | `89c0f2f6f13f20c0b085a0de404d3d056de92374c9f300704d42c50800a77fa0` | REPRINT ONLINE, 20 Jul 2023 |
| 709 | Personal Data Protection Act 2010 | 656,188 | 111 | `fff5cf244ad9a5f464e4b7e8f8baa97e3f2cfbccdb1abd4d47f6c9416bbc6387` | REPRINT ONLINE, 17 Jun 2016 |
| 777 | Companies Act 2016 | 3,616,000 | 621 | `b32cc5ebddf96726e51a3ffdaa38da430b8fa0bcb89c6c6aeb7fdd7698280814` | REPRINT ONLINE, 7 Aug 2022 |

Generate/copy from the current `data/pdfs/en/` files, then independently re-hash and re-count pages on the committed copies — add a test that checks every manifest entry against this. Resolve paths relative to a stable repo/module location, never the process working directory.

If bytes are missing or a hash mismatches: don't serve the file, mark the document unavailable (or return a receipt integrity error), log the `document_id` and failure without leaking filesystem paths, and keep the main query API healthy regardless.

## 8. Backend API

New `api/receipts.py` with its own `APIRouter`, included from `api/main.py` the same way the eval router is.

### `GET /receipts/{document_id}/pdf`

Look up `document_id` in the manifest. Unknown ID → 404. Known but unavailable/corrupt → don't serve bytes. Otherwise return the exact file as `application/pdf`, inline disposition, full hash as ETag, immutable cache policy, and range-fetch support if the installed FastAPI/Starlette `FileResponse` supports it. Never build a filesystem path by interpolating `document_id` or Act number from the request.

### `POST /receipts/{document_id}/locate`

Request:

```jsonc
{
  "evidence_quote": "In any criminal or civil proceeding...",
  "start_page": 72
}
```

`evidence_quote` can be null when the citation has no verified span — the endpoint still returns document metadata and a fallback page. Cap quote length. All page numbers are 1-based.

Response:

```jsonc
{
  "status": "matched",
  "fallback_page": 72,
  "document": {
    "document_id": "act-56-reprint-2017-c11400ad",
    "act_number": "56",
    "act_title": "EVIDENCE ACT 1950",
    "timeline_date": "2017-05-23",
    "timeline_type": "REPRINT ONLINE",
    "sha256": "c11400ad..."
  },
  "pages": [
    {
      "page_number": 72,
      "rectangles": [
        {"x": 0.12, "y": 0.31, "width": 0.71, "height": 0.025}
      ]
    }
  ]
}
```

`status`: `matched` (one confident normalized-token match), `not_found` (no match, or no span was supplied), `ambiguous` (nearest candidate page has multiple indistinguishable matches). For `not_found`/`ambiguous`, `pages` is empty — still return 200, since these are handled outcomes, not missing resources. `422` for invalid input, `404` for unknown document, and a clear server error for asset-integrity failure (frontend turns that into the receipt error state).

## 9. Locator algorithm

Use PyMuPDF word extraction (`page.get_text("words", sort=True)`) so every normalized token keeps its page, block, line, word order, and rectangle.

1. Validate and load the manifest document.
2. Clamp/validate `start_page` against the physical page count.
3. Normalize the Evidence Span into legal-word tokens.
4. Starting at `start_page`, extract word tokens page by page.
5. Keep enough rolling context to catch a quote crossing a page boundary.
6. On the first page range with candidates: one contiguous normalized-token match → `matched`; multiple indistinguishable matches → `ambiguous`; otherwise keep scanning forward.
7. Hit end of document → `not_found`.
8. Group matched word boxes into line-level rectangles.
9. Normalize rectangles to `[0, 1]` relative to the rendered page bounds.

Don't assume the quote is actually on `start_page` — it's only a search hint. If rotation or crop boxes show up in the pilot corpus, verify PyMuPDF page coordinates map correctly to React-PDF's rendered viewport and add whatever transform that requires; don't eyeball it.

An in-process bounded cache keyed by `(document_id, normalized_quote)` is fine to add once correctness is solid, but it's not required for completion unless deployed latency turns out to need it.

## 10. Agent and response-contract changes

Touchpoints:

- `agent/state.py` — typed Evidence Span/Receipt structures, optional `receipt` on `Citation`.
- `agent/nodes/synthesiser.py` (or a small deterministic helper it calls) — attach the manifest `document_id` to pilot citations even before evidence is available.
- `agent/nodes/grounding_check.py` — request, validate, group, and attach Evidence Spans.
- Tests around grounding output coercion, supported/partial/unsupported behavior, validation, fail-open handling.
- `frontend/lib/queryTransport.ts`, `frontend/lib/useQuery.ts`, and workspace message types — mirror the optional contract without making receipt fields mandatory on old/non-pilot responses.

Don't add a lazy database endpoint for section text — the locator only needs the quote that's already a small validated part of the answer response. Don't mutate `pdf_url` into an internal URL.

Graph-lifecycle care: only final validated evidence from the delivered attempt should survive retries; a grounding-check exception must not erase ordinary citation data; a policy/evidence fallback response must not expose stale Evidence Spans from a rejected draft; conversation history stays the delivered prose, not receipt metadata; eval assertions that inspect citations need to stay compatible.

## 11. Frontend behavior

**Viewer ownership.** Keep selected receipt/evidence state at the workspace level so every citation surface opens the same drawer — don't spin up independent viewer instances per message. State needs: selected citation, selected evidence index, opener element/focus-return ref, locator loading/result/error, and viewer page/zoom state. Opening a new citation while the drawer's open just replaces the selection; closing returns focus to whatever triggered it.

**React-PDF integration.** Client-only module. Follow the installed Next.js 16 docs before picking `next/dynamic`/worker placement, and current React-PDF docs for the worker version. Bundle the worker, no runtime CDN. Load `/receipts/{document_id}/pdf` internally. Render a single `Page`, draw normalized rectangles in an absolutely positioned overlay. Highlights only appear on pages from a `matched` result. Cancel/ignore stale loads when the citation changes or the drawer closes.

**Drawer/sheet layout.** Desktop: right-side panel, roughly half the viewport, answer stays readable with scroll position preserved, receipt gets its own scroll region. Mobile: full-screen sheet, clear back/close, page scales to width. Header/content needs: "Source used for this answer" label, Act title/number, section, located-or-fallback page, reprint timeline date/type, the selected claim and quote as text, a selectable list when there's more than one evidence span, a "Check latest on AGC ↗" link using the unchanged `pdf_url`, prev/next + `page X of Y` + zoom controls, and an honest match/error note.

**Active click surfaces.**
1. Replace the inline source row's external-only action with a receipt-opening button when `citation.receipt` exists; keep the external anchor when it doesn't.
2. In-prose citations: an unmodified primary click opens the receipt when present, but keep a real `href={pdf_url}` for middle-click / modified-click / open-in-new-tab / no-JS. A citation index/data attribute plus the shared React click handler beats embedding serialized receipt data in HAST.
3. Source-map links keep doing in-answer navigation, unchanged.

Don't wire the unused `CitationCard`/`SourcesPanel` for this feature.

**Required UI states**

| Condition | Required behavior |
|---|---|
| Pilot receipt + matched evidence | Open located page and draw highlight rectangles. |
| Pilot receipt + multiple evidence spans | Default to first; allow selection; update page/highlight. |
| Pilot receipt + empty evidence | Open exact PDF at section-start page; show "No verified passage was available." |
| Locator `not_found` | Open fallback page without highlight; show "Exact passage could not be pinpointed." |
| Locator `ambiguous` | Open fallback page without highlight; explain no unique match was selected. |
| Receipt API/PDF/integrity error | Show receipt error state and Official Source Link; no highlight. |
| Non-pilot citation | Preserve current AGC new-tab behavior. |
| Citation without `pdf_url` | Omit external action; keep any available internal receipt behavior. |

Don't auto-open a popup after an async failure (browsers may block it) — use a clear user-initiated link/button instead.

## 12. Accessibility

Dialog semantics with an accessible title. Focus moves in on open, stays contained while open, returns to the opener on close. Escape closes unless something higher-priority already owns it. Backdrop/close-button behavior is consistent and keyboard-operable. Page/zoom controls have accessible labels and disabled states. Loading/not-found/ambiguous/error messages use appropriate live-region behavior. Selected evidence is communicated in text, not just colored rectangles. Highlight styling keeps legible contrast in the existing theme. Reduced-motion preferences are respected for the drawer animation.

## 13. Implementation phases

All three phases have to land — each should leave the code coherent on its own.

**Phase 1 — end-to-end tracer bullet.** Tracked Act 56 document + manifest entry, manifest loading/validation, optional citation receipt types with Act 56 `document_id` enrichment, grounding output with a validated Evidence Span, both receipt endpoints, strict locator, client-only React-PDF drawer opened from one inline source row, exact page/highlight for a representative Act 56 citation, and the page-only fallback. Demoable, but not the finish line.

**Phase 2 — complete the five-Act pilot + active integration.** Add and verify Acts 265, 574, 709, 777. Wire in-prose citations through the shared viewer. Support multiple selectable Evidence Spans. Add page navigation, count, zoom, loading, error states. Preserve non-pilot and modified-click AGC behavior. Add contract and interaction regression tests.

**Phase 3 — demo hardening + deployment proof.** Responsive full-screen mobile sheet. Focus/keyboard/live-region accessibility. Cross-page Evidence Span matching and highlighting. Hash-integrity, path-safety, normalization, ambiguous, and not-found tests. Production lint/build and full backend tests. Manual visual matrix across all five Acts. Update living docs. Verify the deployed Railway/Vercel path end to end.

## 14. Testing

**Backend/agent tests** — manifest parses and every declared file matches size/page-count/SHA-256; unknown `document_id` can't reach filesystem resolution; missing/corrupt/hash-mismatched document is never served; PDF endpoint returns correct media type, identity headers, exact bytes; start-page validation and 1-based indexing; whitespace/Unicode/punctuation/soft-hyphen/line-hyphen normalization; a strict successful token match returns normalized line rectangles; cross-page quote returns page-grouped rectangles; repeated/ambiguous candidate returns no highlight; no match returns fallback page with no rectangles; rectangle coordinates stay within `[0, 1]`; supported grounding claim with a real quote becomes an Evidence Span; hallucinated/non-substring quote is discarded; non-answer claim is discarded; partial/unsupported claim gets no Evidence Span; grounding exception preserves ordinary citation data plus pilot document identity; non-pilot citation has no `receipt`; retries/fallbacks don't leak stale evidence from rejected drafts.

Use tiny generated PDF fixtures for most locator unit tests, plus at least one real pilot-PDF integration case. No test should depend on the live AGC network.

**Frontend tests** — there's currently no frontend test runner; add the smallest maintained setup that works with Next.js 16/React 19. Cover: pilot click opens shared drawer; non-pilot click keeps external-link behavior; matched result selects the returned page and renders overlay data; empty/not-found/ambiguous results render the right honest message with no rectangles; evidence selection changes the selected quote/location; API/render error exposes the Official Source Link; close/Escape returns focus; stale locator results can't overwrite a newly selected citation.

Don't try to prove canvas pixel correctness in jsdom — cover state/DOM behavior automatically, use the manual visual matrix for geometry.

## 15. Automated verification

From the repo root:

```bash
pytest -q
```

From `frontend/`:

```bash
npm run lint
npm test
npm run build
```

If the frontend test script needs a non-default non-watch command, document it in `CONTRIBUTING.md` and make sure `npm test` terminates in CI rather than sitting in watch mode.

Also exercise both receipt endpoints locally against a real pilot document — check the served file's SHA-256, not just an HTTP 200.

## 16. Manual and deployed acceptance matrix

| Act/section | Query |
|---|---|
| Act 56, s. 90A | "Can a computer-produced document be used as evidence in criminal or civil proceedings under the Evidence Act?" |
| Act 265, s. 19 | "When must wages be paid after the wage period ends?" |
| Act 574, s. 34 | "Under section 34 of the Penal Code, when a criminal act is done by several people in furtherance of a common intention, how are they each liable?" |
| Act 709, s. 12 | "Does a data subject have a right to access and correct personal data held by a data user?" |
| Act 777, s. 132 | "When may directors authorize a distribution to shareholders under section 132 of the Companies Act, and what solvency test must be satisfied?" |

For every row, confirm: the response contains a pilot `receipt`; the inline source row opens the in-app viewer; an in-prose citation opens the same viewer; document title/section/provenance are correct; the physical page visibly contains the quoted text; rectangles cover the quoted words and nothing else; prev/next and zoom work; "Check latest on AGC" is still there; closing restores answer context and focus.

Also verify: a non-pilot citation still opens its AGC link in a new tab; one deliberately unmatchable Evidence Span shows page-only/no-highlight behavior; one simulated receipt API failure shows the error state without touching the answer; narrow viewport uses the full-screen sheet; desktop keeps claim and PDF visible together.

Repeat the core Act 56 scenario against the deployed Vercel/Railway app, and confirm the PDF is served from the deployed API's immutable asset bundle — not from `lom.agc.gov.my`.

## 17. Living docs to update alongside this change

Per root `AGENTS.md`:

- `README.md` — Citation Receipt behavior, the two endpoints, five-Act pilot boundary.
- `CONTRIBUTING.md` — tracked receipt assets/manifest verification, frontend PDF worker/test setup, local receipt smoke commands.
- `CONTEXT.md` — canonical Citation Receipt/Receipt Document/Evidence Span terminology and how Receipt Documents relate to Official Source Links.

Leave these frozen records alone: `docs/PRD.md`, `docs/agent-hardening-backlog.md`, `docs/adr/*`, `docs/build-log.md`. This handoff is itself the approved-design record. Only open a new ADR if implementation turns up a genuinely hard-to-reverse, surprising trade-off that invalidates an approved decision — not as a way to dodge the agreed scope.

## 18. Explicit non-goals

Out of scope for this pilot: receipts for all 624 Acts; object storage/CDN migration for Receipt Documents; automatic live re-download or reprint sync; using the remote AGC PDF as the receipt; remote-PDF iframe embedding; precomputing or persisting corpus-wide bounding boxes; a new database table or lazy section-content endpoint; fuzzy/semantic/OCR/vision-based matching; Bahasa Malaysia Receipt Documents; continuous full-document scrolling; thumbnails, document search, annotations, printing, or highlighted-PDF download; explicit claim-level markers in generated Markdown; wiring or deleting the unused `CitationCard`/`SourcesPanel`; and changing the agent's substantive legal-answer or retry policy beyond carrying validated receipt evidence.

## 19. Completion checklist

- [ ] G1 exact source provenance complete for all five documents.
- [ ] G2 optional backward-compatible receipt contract delivered end to end.
- [ ] G3 grounding-derived Evidence Spans independently validated.
- [ ] G4 strict lazy locator and both API endpoints complete.
- [ ] G5 responsive focused PDF viewer complete.
- [ ] G6 every honest failure/fallback state implemented.
- [ ] G7 both active UI surfaces use the shared viewer.
- [ ] G8 all five pilot Acts work, non-pilot behavior preserved.
- [ ] G9 accessibility requirements verified.
- [ ] G10 tests, build, living docs, manual matrix, deployed smoke all pass.
- [ ] No frozen record was edited.
- [ ] No post-hackathon non-goal substituted for an unmet required goal.
