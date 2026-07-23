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

The Citation Inspector loads the PDF receipt client-only. Its **References** tab lazily imports the pinned `cytoscape` package directly (no React graph wrapper) and requests only `/reference-graph/neighborhood` for the selected citation provision. The standalone graph page preserves `document_id`, `focus_provision_id`, `layout`, and reserved `compare_document_id` URL values, but deliberately has no chat, Act-wide browser, search, or comparison mode.

If the backend has no promoted graph for that immutable snapshot, the UI says: `Reference graph not yet indexed for this snapshot.`
