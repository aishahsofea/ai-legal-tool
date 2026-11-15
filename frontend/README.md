# Frontend

The Next.js client provides the research workspace, Citation Receipt inspector, eval dashboard, and the standalone `/reference-graph` page.

```bash
npm install
npm run dev
npm run lint
npm run test
npx tsc --noEmit
```

Set `NEXT_PUBLIC_API_URL` to the API origin. `NEXT_PUBLIC_EVALS=1` exposes `/evals` at build time.

Every colour is a CSS variable in `app/globals.css`. `:root` holds the light values and `:root[data-theme="dark"]` holds the dark ones. A small script in `app/layout.tsx` sets `data-theme` before first paint. It reads the saved choice from the `localStorage` key `locus.theme.v1`, or uses the OS setting if nothing is saved. The two Cytoscape graphs cannot read CSS variables. They get real colour values from `lib/cssColors.ts` and restyle when the theme changes. The PDF page stays white in dark mode on purpose, because it shows the original scan.

The Citation Inspector loads the PDF receipt client-only. Its **References** tab lazily imports the pinned `cytoscape` package directly (no React graph wrapper) and retains the Phase 1 `/reference-graph/neighborhood` behavior for one immutable snapshot.

When both backend graph flags are enabled, the existing explorer can select two promoted, audited Act 265 snapshots and request `/reference-graph/compare` for one focused one-hop overlay. It computes deterministic preset positions once from the union, so base/comparison/overlay and Explore/Trace toggles do not move nodes. Added, removed, and unchanged references use color plus line/marker cues and an accessible legend. Base and comparison evidence link to their own receipts; offsets and pages are never shared between PDFs.

The standalone page preserves `document_id`, `compare_document_id`, `focus_provision_id`, `layout`, and `overlay` in its URL. Focus navigation pushes history, layout/overlay/selector changes replace state, browser Back restores focus, and “Open larger” preserves the complete state. Snapshot labels are observations, not exact effective dates. There is no chat, global search, whole-Act/corpus graph, or reference-following retrieval.

If the backend has no promoted graph for that immutable snapshot, the UI says: `Reference graph not yet indexed for this snapshot.`
