# PDF Citation Receipt View — Cold Implementation Handoff

> **Historical pilot record (superseded):** this document describes the original five-Act UI pilot. The current corpus-wide provenance, storage, migration, rollout, and operator contract is [corpus-receipts.md](corpus-receipts.md). Preserve this file as the implementation record; do not use its pilot-only scope as current architecture.

> **Status:** Approved design. This is a build handoff, not a brainstorming document.
>
> **Audience:** An implementing agent starting cold, without the design conversation.
>
> **Execution rule:** Continue until every required end goal and completion gate in this
> document is satisfied. Completing only the tracer-bullet phase, writing code without
> verification, or passing tests while the deployed experience remains broken is not
> completion. The post-hackathon items are explicitly excluded and must not delay completion.

## 1. Mission

Replace citation links that currently leave the application with an in-app **Citation Receipt**.
The receipt must let a practitioner compare the assistant's claim with the exact government PDF
snapshot used to produce the retrieved statute chunk:

1. click a citation;
2. keep the answer visible;
3. open the exact PDF snapshot in a responsive evidence drawer;
4. navigate to the physical page containing the supporting words;
5. highlight only a deterministically verified passage; and
6. retain a separate AGC link so the practitioner can check the official remote source.

This is a trust feature. It must never imply that an uncertain match is exact, and it must never
use a different PDF reprint merely because that PDF is easier to embed.

## 2. Required end goals

All goals below are mandatory. The implementation loop must not declare completion while any goal
is unchecked.

### G1 — Exact source provenance

The five pilot PDF files served by the receipt are byte-for-byte the files used to generate the
stored chunks and `page_number` values. They are tracked as immutable deployment assets and listed
in a machine-readable manifest containing hashes and provenance. A manifest/file hash mismatch
must make that Receipt Document unavailable; it must never be served as if valid.

### G2 — Evidence-bearing citation contract

The existing citation response remains backward-compatible and gains an optional nested
`receipt`. A pilot citation identifies an immutable `document_id` and contains zero or more
validated Evidence Spans. Complete chunks and bounding boxes are not added to every answer.

### G3 — Verified evidence extraction

The existing grounding-check call emits a compact supporting quote for each supported legal claim.
Application code independently verifies both the claim-to-answer relationship and the
quote-to-retrieved-chunk relationship before exposing the Evidence Span. Model output alone is
never trusted as highlight data.

### G4 — Lazy, deterministic passage location

FastAPI exposes a receipt router that serves the immutable PDF and locates a selected Evidence
Span on demand with PyMuPDF. Location uses strict normalized token matching with word-coordinate
mapping. No general fuzzy, semantic, or nearest-looking match may produce a highlight.

### G5 — In-app evidence viewer

On desktop, a right-hand drawer keeps the answer and receipt visible together. On narrow screens,
the viewer becomes a full-screen sheet. It renders one PDF page at a time, opens on the matched or
fallback page, draws the highlight overlay, and provides close, previous/next page, page count,
and zoom controls.

### G6 — Honest failure behavior

Receipt failures never suppress an otherwise deliverable legal answer. Missing evidence, a
`not_found` or `ambiguous` locator result, a corrupt asset, and an API/render error all have an
explicit UI state. No uncertain highlight is drawn. Where possible, the exact Receipt Document
still opens at the stored section-start page, and the remote AGC action remains visible.

### G7 — Correct UI integration boundary

Both citation-opening surfaces that are active in the current workspace open the shared viewer:

- in-prose citation links produced by `rehypeCitationLinks`; and
- the inline source row's current “Open full act” action.

The source-map anchors continue to navigate within the answer. Unused legacy components are not a
required integration surface.

### G8 — Five-Act deployed pilot

Receipts work for the five Acts in the existing eval corpus: Acts 56, 265, 574, 709, and 777.
Citations to other Acts preserve the current remote-AGC behavior. The deployed Railway API can
read and serve the five tracked assets, and the deployed frontend can load them through the API.

### G9 — Accessible, usable interaction

The drawer/sheet has dialog semantics, an accessible name, deterministic focus entry and return,
keyboard closing, and controls with accessible labels. Highlight color is not the only indication
of evidence: the selected claim and quote are also available as text. Loading and error states are
announced and do not strand focus.

### G10 — Verified implementation and living documentation

Backend tests, graph/contract tests, frontend interaction tests, lint, production build, and a
manual visual/deployed smoke matrix all pass. Because this change modifies the API contract and
frontend architecture, `README.md`, `CONTRIBUTING.md`, and `CONTEXT.md` are updated in the same
change. Frozen decision records remain untouched.

## 3. Completion semantics for an autonomous loop

The phases in section 13 are implementation order, not optional milestones. Phases 1, 2, and 3
must all be complete before the overall goal is complete.

The loop may stop successfully only when:

- every G1–G10 end goal is demonstrably satisfied;
- every required automated command in section 15 passes;
- every manual acceptance scenario in section 16 has recorded evidence;
- the exact pilot assets are present in the production build/deployment artifact;
- the deployed smoke check passes, not only localhost; and
- no required item is silently deferred into “future work.”

If an external credential or deployment permission is genuinely unavailable, preserve completed
work and report the exact unsatisfied gate as blocked. Do not describe the project as complete.
Do not broaden the work into the post-hackathon non-goals to keep the loop busy.

## 4. Canonical terminology

- **Citation Receipt** — the in-app verification experience opened from a citation.
- **Receipt Document** — an immutable PDF file whose bytes are the ones used during extraction.
- **Evidence Span** — a legal claim plus a short supporting quote that has passed deterministic
  validation against the delivered answer and retrieved chunk.
- **Locator Result** — the physical PDF page(s) and word rectangles found for one Evidence Span.
- **Official Source Link** — the existing remote AGC `pdf_url`. It is a separate escape hatch and
  is not the Receipt Document.
- **Section-start page** — the existing citation `page_number`. It records where extraction first
  detected the section; it is not guaranteed to contain every supporting passage in a long section.

Use these names in code and documentation where practical. Do not call the remote AGC PDF the
receipt, and do not call a section-start page an evidence page until the locator has matched it.

## 5. Current codebase facts

These are implementation constraints, not assumptions:

- `agent/state.py` defines `Citation` with `act_number`, `act_title`, `section_number`, `pdf_url`,
  and `page_number`.
- `agent/nodes/synthesiser.py:_finalise()` deliberately strips retrieved `content` when it builds
  citations.
- `agent/retrieval/search.py:attach_pdf_urls()` attaches the remote metadata URL.
- `scraper/step4_extract.py` computed `page_number` against `data/pdfs/en/{act}.pdf` with PyMuPDF.
- The extractor strips and rejoins lines. Stored chunk text is not a byte-for-byte substring of a
  browser PDF text layer.
- A section chunk can span several physical pages. Its stored `page_number` is only the page where
  that section began.
- `agent/nodes/grounding_check.py` already identifies answer claims, cited Act/section pairs, and
  support labels, but does not currently retain supporting quotes.
- PyMuPDF is already a backend dependency.
- The full local PDF directory contains 624 files, totals roughly 587 MB, and is gitignored.
- The five approved pilot files total roughly 7.7 MB.
- `api/evals.py` establishes the router-per-feature precedent used by `api/main.py`.
- The live workspace now renders sources inline in
  `frontend/components/locus-workspace/Messages.tsx`.
- `frontend/components/CitationCard.tsx` and
  `frontend/components/locus-workspace/SourcesPanel.tsx` remain in the tree but are not rendered by
  the current workspace.
- `frontend/components/locus-workspace/rehypeCitationLinks.ts` builds HAST anchors for in-prose
  section and Act mentions.
- No PDF rendering package is installed. The current frontend uses Next.js 16.2.6 and React 19.2.4.
- `frontend/AGENTS.md` requires reading the installed Next.js guidance under
  `frontend/node_modules/next/dist/docs/` before editing frontend code.

Before implementation, read root `AGENTS.md`, `frontend/AGENTS.md`, the files above, and the
relevant tests. Preserve unrelated changes in the existing dirty worktree.

## 6. Approved architectural decisions

### D1 — Receipt correctness is tied to exact bytes

The Receipt Document is the exact local extraction PDF, not whatever bytes the remote AGC URL
serves at click time. Remote content can change while retaining a URL, and pagination is not a
stable cross-file identifier. The Official Source Link remains a separately labelled action.

### D2 — Selectively track five canonical extraction PDFs

For the hackathon, reuse the exact extraction files in `data/pdfs/en/` as the Receipt Documents.
Keep the manifest beside the canonical PDF tree and use narrow `.gitignore` exceptions so only the
manifest and five approved PDFs are committed:

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

Do not unignore or commit the rest of the `data/pdfs/` corpus. Do not create duplicate PDF copies
under a receipt-specific directory, and do not add object storage for this pilot.
If repository-publication rules prohibit committing these public-source binaries, use an approved
deployment asset mechanism that preserves the exact hashes below; never replace them with a live
download silently.

### D3 — Use an immutable document identifier

Act number alone is not enough because an Act has multiple Reprints. `document_id` must identify a
specific manifest entry and must change when the bytes change. It is an opaque API identifier; file
paths are resolved only through the loaded manifest.

Suggested IDs:

- `act-56-reprint-2017-c11400ad`
- `act-265-reprint-2023-6fec2f07`
- `act-574-reprint-2023-89c0f2f6`
- `act-709-reprint-2016-fff5cf24`
- `act-777-reprint-2022-b32cc5eb`

### D4 — Enrich citations minimally

Keep the existing citation fields and the meaning of `pdf_url`. Add an optional nested `receipt`.
Do not send complete chunks, PDF bytes, or rectangles on every answer.

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

For a pilot citation, `receipt` should still be present when evidence extraction fails, with
`evidence: []`. That permits page-only verification against the correct snapshot. For a non-pilot
citation, `receipt` is absent and the existing AGC-link behavior remains.

### D5 — Derive Evidence Spans in the grounding check

Extend the existing grounding-check structured output rather than adding another LLM call or asking
the synthesiser to vouch for its own evidence. For each supported claim, request one short,
contiguous supporting quote and retain the existing Act/section identifiers.

Accept an Evidence Span only when deterministic application code confirms all of the following:

1. `support == "supported"`;
2. the Act/section pair exists in the structured citations and retrieved chunks;
3. normalized `claim` occurs in the draft answer;
4. normalized `quote` occurs in the matching retrieved chunk; and
5. the quote is non-empty and within a conservative configured length cap.

Group valid spans under their citation in answer order and remove exact duplicates. A `partial` or
`unsupported` claim does not receive highlight evidence. Preserve the existing grounding
violation/retry semantics unless a separate correctness bug is proven; this feature must not
silently redefine the agent's safety policy.

If the grounding call fails open, attach the pilot `document_id` deterministically and send an
empty evidence list. The legal answer lifecycle remains available.

### D6 — Locate boxes lazily with PyMuPDF

The absence of stored boxes does not require a corpus-wide re-extraction. Compute boxes only after
a click, against the selected Receipt Document. This uses the same extraction library and exact
bytes as the original pipeline, and makes matching independently testable on the backend.

### D7 — Normalize strictly; do not fuzzy-highlight

Matching may normalize representational differences:

- Unicode normalization (NFKC);
- case folding;
- whitespace collapsing;
- soft-hyphen removal;
- canonical apostrophe/dash treatment;
- surrounding punctuation differences; and
- line-end word dehyphenation where word-coordinate structure proves the break.

The matched legal-word sequence must remain a contiguous exact token sequence after normalization.
Do not use edit-distance thresholds, embeddings, semantic similarity, or “best-looking” matches to
draw a highlight. Those techniques can be future diagnostics, not proof.

### D8 — Fail open for the UI, fail closed for false highlights

A receipt is a non-critical verification affordance, so its failure must not discard the legal
answer. A highlight is a trust assertion, so uncertainty must yield no highlight. The UI explains
the state and still offers the page and Official Source Link where possible.

### D9 — Use a focused React PDF renderer

Use the current `react-pdf` package line compatible with React 19, backed by its matching
`pdfjs-dist` version. The viewer is client-only and must follow both the installed Next.js 16
guidance and the React-PDF worker guidance. Bundle the worker with the application; do not depend
on a third-party CDN at runtime.

Render one page at a time. The backend supplies normalized rectangles, so frontend PDF text search
is unnecessary. Overlay rectangles in the page wrapper using percentage coordinates.

### D10 — Use a responsive evidence drawer

Desktop uses a right-side drawer that leaves the answer visible. Narrow screens use a full-screen
sheet. A modal that obscures the claim is rejected because side-by-side verification is the core
user value.

### D11 — Keep section-level links for the pilot

Do not introduce explicit claim markers into generated Markdown. When a section has multiple
Evidence Spans, default to the first verified span and show a compact, keyboard-accessible evidence
list. Selecting another claim re-runs/uses its locator result and updates the highlight.

### D12 — Integrate only active citation surfaces

Create one receipt-viewer state at the workspace level and route the two live surfaces through one
`openReceipt(citation, evidenceIndex?)` action. Do not spend hackathon time wiring or deleting the
unused `CitationCard` and `SourcesPanel` components.

## 7. Pilot Receipt Document manifest

The manifest must include at least:

- schema version;
- `document_id`;
- Act number/title and language;
- relative asset path;
- SHA-256, byte size, and page count;
- source URL recorded in Act metadata;
- timeline date/type; and
- metadata scrape timestamp.

The recorded source URL is provenance, not proof that the URL still serves identical bytes. The
SHA-256 is the Receipt Document identity.

| Act | Title | Bytes | Pages | SHA-256 | Metadata timeline |
|---|---|---:|---:|---|---|
| 56 | Evidence Act 1950 | 771,581 | 120 | `c11400ad1b0a9941919d7328c60fc1c2b49fb2788671bf9697c2923364c96d07` | REPRINT ONLINE, 23 May 2017 |
| 265 | Employment Act 1955 | 1,309,405 | 127 | `6fec2f07b49d8f381851906781259b1e09a2152db8dcf1599ab77a592eae100b` | REPRINT ONLINE, 1 Feb 2023 |
| 574 | Penal Code | 1,736,926 | 326 | `89c0f2f6f13f20c0b085a0de404d3d056de92374c9f300704d42c50800a77fa0` | REPRINT ONLINE, 20 Jul 2023 |
| 709 | Personal Data Protection Act 2010 | 656,188 | 111 | `fff5cf244ad9a5f464e4b7e8f8baa97e3f2cfbccdb1abd4d47f6c9416bbc6387` | REPRINT ONLINE, 17 Jun 2016 |
| 777 | Companies Act 2016 | 3,616,000 | 621 | `b32cc5ebddf96726e51a3ffdaa38da430b8fa0bcb89c6c6aeb7fdd7698280814` | REPRINT ONLINE, 7 Aug 2022 |

Generate/copy the assets from the current `data/pdfs/en/` files, then independently re-hash and
page-count the committed copies. Add a test that validates every manifest entry. Resolve paths
relative to a stable repository/module location, not the process working directory.

On missing bytes or a hash mismatch:

- do not serve the file;
- mark the document unavailable for receipt enrichment or return a receipt integrity error;
- log the `document_id` and failure without leaking filesystem paths; and
- leave the main query API healthy.

## 8. Backend API contract

Create `api/receipts.py` with its own `APIRouter`, included from `api/main.py` in the same style as
the eval router.

### `GET /receipts/{document_id}/pdf`

Behavior:

- look up `document_id` in the loaded manifest;
- reject unknown IDs with 404;
- reject a known but unavailable/corrupt asset without serving bytes;
- return the exact file as `application/pdf` with inline disposition;
- use the full hash as an ETag and an immutable cache policy; and
- support the browser/PDF renderer's normal range-fetch behavior if the installed FastAPI/Starlette
  `FileResponse` supports it.

Never interpolate `document_id` or Act number into a filesystem path from the request.

### `POST /receipts/{document_id}/locate`

Suggested request:

```jsonc
{
  "evidence_quote": "In any criminal or civil proceeding...",
  "start_page": 72
}
```

`evidence_quote` may be null/absent when the citation has no verified span; the endpoint can still
return document metadata and the validated fallback page. Cap non-null quote length. All API page
numbers are 1-based.

Suggested response:

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

`status` is one of:

- `matched` — one confident normalized token match;
- `not_found` — no match, including no supplied Evidence Span; or
- `ambiguous` — the nearest candidate page contains multiple indistinguishable matches.

For `not_found` and `ambiguous`, `pages` is empty. Return 200 because these are handled receipt
outcomes, not missing HTTP resources. Invalid input is 422; unknown document is 404; asset-integrity
failure is a clear server error that the frontend converts to the receipt error state.

## 9. Locator algorithm

Use PyMuPDF word extraction, e.g. `page.get_text("words", sort=True)`, so every normalized token
retains its source page, block, line, word order, and rectangle.

Recommended deterministic flow:

1. Validate and load the manifest document.
2. Clamp/validate `start_page` against the physical page count.
3. Normalize the Evidence Span into legal-word tokens.
4. Starting at `start_page`, extract word tokens page by page.
5. Maintain enough rolling context to match a quote crossing a page boundary.
6. On the first physical page range containing candidates:
   - one contiguous normalized-token match becomes `matched`;
   - multiple indistinguishable matches become `ambiguous`;
   - otherwise continue forward.
7. If the end of the document is reached, return `not_found`.
8. Group matched word boxes into line-level rectangles.
9. Normalize rectangle values to `[0, 1]` relative to the rendered page bounds.

Do not assume the quote is on `start_page`; that page is only a search hint. If rotation or crop
boxes occur in the pilot corpus, verify that PyMuPDF page coordinates map to React-PDF's rendered
viewport and add the necessary deterministic transform. A visual guess is not sufficient.

An in-process bounded cache keyed by `(document_id, normalized_quote)` is allowed after correctness
is established, but it is not required for completion unless deployed latency is unacceptable.

## 10. Agent and response-contract changes

Expected touchpoints:

- `agent/state.py` — add typed Evidence Span/Receipt structures and optional receipt on `Citation`;
- `agent/nodes/synthesiser.py` or a small deterministic helper it calls — attach the manifest
  `document_id` to pilot citations even before evidence is available;
- `agent/nodes/grounding_check.py` — request, validate, group, and attach Evidence Spans;
- tests around grounding output coercion, supported/partial/unsupported behavior, validation, and
  fail-open handling;
- `frontend/lib/queryTransport.ts`, `frontend/lib/useQuery.ts`, and workspace message types — mirror
  the optional contract without making receipt fields mandatory for old/non-pilot responses.

Do not add a lazy database endpoint for section text. The quote needed by the locator is already a
small validated part of the answer response. Do not mutate `pdf_url` into an internal URL.

Be careful with the graph lifecycle:

- only final, validated evidence from the delivered attempt should survive retries;
- a grounding-check exception must not erase ordinary citation data;
- a policy/evidence fallback response must not expose stale Evidence Spans from a rejected draft;
- conversation history remains the delivered prose, not receipt metadata; and
- eval assertions that inspect citations must remain compatible.

## 11. Frontend behavior

### Viewer ownership

Keep selected receipt/evidence state at the workspace level so every live citation surface opens
the same drawer. Do not create independent viewer instances inside every assistant message.

Suggested state contains:

- the selected citation;
- selected evidence index;
- opener element/focus-return reference;
- locator loading/result/error; and
- viewer page/zoom state.

Opening a different citation while the drawer is visible replaces the selected receipt. Closing
returns focus to the triggering control.

### React-PDF integration

- Implement the PDF surface in a client-only module.
- Follow the installed Next.js 16 documentation before choosing `next/dynamic`/worker placement.
- Follow current React-PDF documentation and keep its PDF.js worker version aligned.
- Bundle the worker with the app; do not use a runtime CDN.
- Load the internal `/receipts/{document_id}/pdf` URL.
- Render a single `Page`, then draw normalized rectangles in an absolutely positioned overlay.
- Highlights appear only on pages included in a `matched` Locator Result.
- Cancel/ignore stale loads when the selected citation changes or the drawer closes.

### Drawer/sheet layout

Desktop:

- right-side panel around half the viewport;
- answer remains readable and scroll position is preserved;
- receipt has its own scroll region.

Mobile/narrow:

- full-screen sheet;
- clear back/close action;
- page scales to available width.

Header/content:

- “Source used for this answer” label;
- Act title/number, section, located or fallback page;
- Reprint timeline date/type from locator metadata;
- selected claim and supporting quote as text;
- selectable list when `evidence.length > 1`;
- “Check latest on AGC ↗” using the unchanged `pdf_url`;
- previous/next, `page X of Y`, zoom in/out/reset; and
- honest match/error note.

### Active click surfaces

1. Replace the inline source row's external-only action with a receipt-opening button when
   `citation.receipt` exists. When it does not exist, retain the external anchor.
2. Adapt the in-prose citation path so an unmodified primary click opens the receipt when present.
   Preserve a real `href={pdf_url}` for middle-click, modified click, open-in-new-tab, and no-JS
   fallback. A citation index/data attribute plus the shared React click path is preferable to
   embedding serialized receipt data in HAST.
3. Leave source-map links as within-answer navigation.

Do not wire the unused legacy `CitationCard` or `SourcesPanel` in this feature.

### Required UI states

| Condition | Required behavior |
|---|---|
| Pilot receipt + matched evidence | Open located page and draw highlight rectangles. |
| Pilot receipt + multiple evidence spans | Default to first; allow selection; update page/highlight. |
| Pilot receipt + empty evidence | Open exact PDF at section-start page; show “No verified passage was available.” |
| Locator `not_found` | Open fallback page without highlight; show “Exact passage could not be pinpointed.” |
| Locator `ambiguous` | Open fallback page without highlight; explain that no unique match was selected. |
| Receipt API/PDF/integrity error | Show receipt error state and Official Source Link; do not draw a highlight. |
| Non-pilot citation | Preserve current AGC new-tab behavior. |
| Citation without `pdf_url` | Omit external action; keep any available internal receipt behavior. |

Do not automatically open a popup after an asynchronous failure; browsers may block it. Present a
clear user-initiated link/button instead.

## 12. Accessibility requirements

At minimum:

- drawer/sheet uses appropriate dialog semantics and an accessible title;
- focus moves inside on open, is contained while open, and returns to the opener on close;
- Escape closes unless an existing higher-priority interaction owns Escape;
- backdrop/close button behavior is consistent and keyboard operable;
- page and zoom controls have accessible labels and disabled states;
- loading, not-found, ambiguous, and error messages use suitable live-region behavior;
- selected evidence is communicated in text, not only bronze/yellow rectangles;
- highlight styling preserves legibility and adequate contrast in the existing chamber theme; and
- reduced-motion preferences are respected for drawer animation.

## 13. Required implementation phases

Each phase should leave the code coherent. Overall completion still requires all three.

### Phase 1 — End-to-end tracer bullet

Deliver one complete Evidence Act path before generalizing:

- tracked Act 56 Receipt Document and manifest entry;
- manifest loading and integrity validation;
- optional citation receipt types and Act 56 `document_id` enrichment;
- grounding output with deterministically validated Evidence Span;
- both receipt endpoints and strict locator;
- client-only React-PDF drawer opened from one inline source row;
- exact page/highlight for a representative Act 56 citation; and
- page-only/no-highlight fallback.

This phase is demoable but is not the final completion condition.

### Phase 2 — Complete five-Act pilot and active integration

- add and verify Acts 265, 574, 709, and 777;
- wire in-prose citations through the shared viewer;
- support multiple selectable Evidence Spans;
- add page navigation, count, zoom, loading, and error states;
- preserve non-pilot and modified-click AGC behavior; and
- add contract and interaction regression tests.

### Phase 3 — Demo hardening and deployment proof

- responsive full-screen mobile sheet;
- focus/keyboard/live-region accessibility;
- cross-page Evidence Span matching and highlighting;
- hash-integrity, path-safety, normalization, ambiguous, and not-found tests;
- production lint/build and full backend tests;
- manual visual matrix across all five Acts;
- update living docs; and
- verify the deployed Railway/Vercel path end to end.

## 14. Testing requirements

### Backend/agent tests

Add focused tests for:

- manifest parses and every declared file matches size, page count, and SHA-256;
- unknown `document_id` cannot reach filesystem resolution;
- missing/corrupt/hash-mismatched document is never served;
- PDF endpoint returns correct media type, identity headers, and exact bytes;
- start-page validation and 1-based indexing;
- whitespace, Unicode, punctuation, soft-hyphen, and line-hyphen normalization;
- a strict successful token match returns normalized line rectangles;
- cross-page quote returns page-grouped rectangles;
- repeated/ambiguous candidate returns no highlight;
- no match returns fallback page and no rectangles;
- rectangle coordinates remain within `[0, 1]`;
- supported grounding claim with a real quote becomes Evidence Span;
- hallucinated/non-substring quote is discarded;
- non-answer claim is discarded;
- partial/unsupported claim receives no Evidence Span;
- grounding exception preserves ordinary citation plus pilot document identity;
- non-pilot citation has no `receipt`; and
- retries/fallbacks do not leak stale evidence from rejected drafts.

Use tiny generated PDF fixtures for most locator unit tests and at least one real pilot PDF
integration case. Tests must not depend on the live AGC network.

### Frontend tests

The repository currently has no frontend test runner. Add the smallest maintained test setup that
works with Next.js 16/React 19, then test at least:

- pilot click opens shared drawer;
- non-pilot click keeps external-link behavior;
- matched result selects returned page and renders overlay data;
- empty/not-found/ambiguous results render the right honest message without rectangles;
- evidence selection changes the selected quote/location;
- API/render error exposes the Official Source Link;
- close/Escape returns focus; and
- stale locator results cannot overwrite a newly selected citation.

Do not try to prove canvas pixel correctness in jsdom. Cover state/DOM behavior automatically and
use the required visual matrix for geometry.

## 15. Required automated verification

Run from the repository root unless noted:

```bash
pytest -q
```

Run from `frontend/`:

```bash
npm run lint
npm test
npm run build
```

If the chosen frontend test script uses a different non-watch command, document it in
`CONTRIBUTING.md` and ensure `npm test` itself terminates in CI rather than entering watch mode.

Also exercise both receipt endpoints locally against a real pilot document. Verify the served
file's SHA-256 rather than merely checking for HTTP 200.

## 16. Manual and deployed acceptance matrix

Use these existing eval questions so receipt behavior is exercised against known Act/section
pairs:

| Act/section | Query |
|---|---|
| Act 56, s. 90A | “Can a computer-produced document be used as evidence in criminal or civil proceedings under the Evidence Act?” |
| Act 265, s. 19 | “When must wages be paid after the wage period ends?” |
| Act 574, s. 34 | “Under section 34 of the Penal Code, when a criminal act is done by several people in furtherance of a common intention, how are they each liable?” |
| Act 709, s. 12 | “Does a data subject have a right to access and correct personal data held by a data user?” |
| Act 777, s. 132 | “When may directors authorize a distribution to shareholders under section 132 of the Companies Act, and what solvency test must be satisfied?” |

For every row, confirm:

1. the delivered response contains a pilot `receipt`;
2. opening from the inline source row opens the in-app viewer;
3. opening from an in-prose citation opens the same viewer;
4. the document title/section/provenance are correct;
5. the physical page visibly contains the selected quote;
6. the rectangles cover the quoted words and not unrelated text;
7. previous/next and zoom work;
8. “Check latest on AGC” remains available; and
9. closing restores answer context and focus.

Additionally verify:

- one non-pilot citation still opens its AGC link in a new tab;
- one deliberately unmatchable Evidence Span shows page-only/no-highlight behavior;
- one simulated receipt API failure shows the error state without affecting the answer;
- narrow viewport uses the full-screen sheet; and
- desktop keeps claim and PDF visible together.

Repeat the core Act 56 scenario against the deployed Vercel/Railway application. Confirm the PDF is
served by the deployed API from the immutable asset bundle and not from `lom.agc.gov.my`.

## 17. Living documentation required in the implementation change

Per root `AGENTS.md`, update:

- `README.md` — Citation Receipt behavior, two endpoints, and five-Act pilot boundary;
- `CONTRIBUTING.md` — tracked receipt assets/manifest verification, frontend PDF worker/test setup,
  and local receipt smoke commands; and
- `CONTEXT.md` — canonical Citation Receipt/Receipt Document/Evidence Span terminology and the
  relationship between Receipt Documents and Official Source Links.

Do not edit these frozen records to rewrite history:

- `docs/PRD.md`;
- `docs/agent-hardening-backlog.md`;
- `docs/adr/*`; or
- `docs/build-log.md`.

This handoff itself records the approved design. Create a new ADR only if implementation discovers
a genuinely hard-to-reverse, surprising trade-off that invalidates an approved decision; do not
use an ADR to avoid implementing the agreed scope.

## 18. Explicit non-goals

These items are outside the hackathon completion gate:

- receipts for all 624 Acts;
- object storage/CDN migration for Receipt Documents;
- automatic live re-download or reprint synchronization;
- using the remote AGC PDF as the receipt;
- remote-PDF iframe embedding;
- precomputing or persisting corpus-wide bounding boxes;
- a new database table or lazy section-content endpoint;
- fuzzy, semantic, OCR, or vision-based passage matching;
- Bahasa Malaysia Receipt Documents;
- continuous full-document scrolling;
- thumbnails, document search, annotations, printing, or highlighted-PDF download;
- explicit claim-level markers inserted into generated Markdown;
- wiring or deleting unused `CitationCard`/`SourcesPanel` components; and
- changing the agent's substantive legal-answer or retry policy beyond carrying validated receipt
  evidence.

## 19. Final completion checklist

The implementing loop must check every required item before stopping:

- [ ] G1 exact source provenance is complete for all five documents.
- [ ] G2 optional backward-compatible receipt contract is delivered end to end.
- [ ] G3 grounding-derived Evidence Spans are independently validated.
- [ ] G4 strict lazy locator and both API endpoints are complete.
- [ ] G5 responsive focused PDF viewer is complete.
- [ ] G6 every honest failure/fallback state is implemented.
- [ ] G7 both active UI surfaces use the shared viewer.
- [ ] G8 all five pilot Acts work and non-pilot behavior is preserved.
- [ ] G9 accessibility requirements are verified.
- [ ] G10 tests, build, living docs, manual matrix, and deployed smoke pass.
- [ ] No frozen record was edited.
- [ ] No post-hackathon non-goal was substituted for an unmet required goal.

Only after every box above is true may the implementation be reported complete.
