# Autoresearch: UI layout responsiveness and inline sources

## Objective
Improve the frontend research workspace so the layout remains sensible across widths and sources are integrated into the answer text rather than isolated in a right-hand panel. The target experience is closer to a research report: readable central text, inline source markers/cards near the relevant answer, and no awkward citations sidebar.

## Metrics
- **Primary**: layout_debt (unitless, lower is better) — static UX debt score for source placement, responsive grid, and inline citation affordances.
- **Secondary**: lint_exit, build_exit, source_panel_refs, inline_citation_refs — correctness and implementation-shape monitors.

## How to Run
`./autoresearch.sh` — outputs `METRIC name=number` lines.

## Files in Scope
- `frontend/app/page.tsx` — workspace composition and top-level responsive layout.
- `frontend/app/globals.css` — grid/layout utilities and readable width tokens.
- `frontend/components/locus-workspace/*` — message rendering, markdown, source/citation UI, composer/sidebar/header.
- `frontend/components/CitationCard.tsx`, `frontend/components/chamber.tsx` — reusable citation/source presentation primitives.
- `frontend/lib/useResearchThreads.ts`, `frontend/lib/useQuery.ts`, `frontend/lib/queryTransport.ts` — citation data shaping if needed for inline rendering.

## Off Limits
- Do not change backend/legal answer behavior to game metrics.
- Do not remove citations data or hide source information; sources must remain available in-context.
- Do not add heavy dependencies unless clearly necessary.

## Constraints
- Keep the app building and linting.
- Do not cheat by special-casing `autoresearch.sh`; improve real UI code.
- Prefer simple, reviewable UX changes over benchmark-specific hacks.

## What's Been Tried
- Baseline showed layout debt from the three-column desktop grid, right-hand `SourcesPanel`, and sources separated from assistant answers. Existing lint also failed in `useResearchThreads`.
- Kept experiment `dfbb9ee`: removed the right sources rail, simplified the desktop grid to nav + content, rendered citations inside each assistant message as a `Sources Used` section, and got lint/build passing.
- Kept experiment `14f840b`: added a compact pre-answer source map with `[1]` style links to detailed source rows below the answer.
- Kept experiment `d578cbe`: removed duplicated `CitationCard` content from message source rows and added accessible open-source labels plus back-to-map links.
- Next focus: keep the pre-answer source map manageable when an answer has many citations; long citation lists should not push the answer prose too far down.
