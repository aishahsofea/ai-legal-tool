# PDF Citation Receipt smoke results

Date: 2026-07-19
Environment: local production frontend build and local FastAPI, using the selectively tracked canonical PDFs

This record separates the local verification completed in this worktree from the deployment gate.
The deployment gate is still blocked and is not reported as passing.

## Five-Act visual matrix

The real React-PDF viewer was exercised against the real locator and PDF endpoints. Each row used
the corresponding pilot citation/Receipt Document and a quote that visibly appeared beneath the
returned rectangles.

| Receipt Document | Result | Located page | PDF pages | Highlight rectangles | Provenance shown |
|---|---:|---:|---:|---:|---|
| Act 56, s. 90A | matched | 72 | 120 | 2 | REPRINT ONLINE, 2017-05-23 |
| Act 265, s. 19 | matched | 30 | 127 | 2 | REPRINT ONLINE, 2023-02-01 |
| Act 574, s. 34 | matched | 42 | 326 | 2 | REPRINT ONLINE, 2023-07-20 |
| Act 709, s. 12 | matched | 23 | 111 | 2 | REPRINT ONLINE, 2016-06-17 |
| Act 777, s. 132 | matched | 157 | 621 | 3 | REPRINT ONLINE, 2022-08-07 |

For Act 56, advancing from page 72 to page 73 removed the overlay, zooming from 100% to 125%
increased the rendered page width from 658 px to 823 px, and reset restored 100%. The desktop
drawer kept the answer beside the claim, quote, PDF page, and AGC action. At a 390 x 844 viewport,
the same viewer became a full-screen sheet and kept the quote and highlight visible.

The first Act 709 locator request was deliberately observed in its interrupted/error state: the
viewer retained the answer and Official Source Link and drew no highlight. Reopening the receipt
produced the deterministic match above. Automated interaction coverage additionally verifies the
empty-evidence, not-found, ambiguous, stale-response, non-pilot, modified-click, focus-return, and
both active citation-opening paths.

## Endpoint proof

`GET /receipts/act-56-reprint-2017-c11400ad/pdf` produced SHA-256
`c11400ad1b0a9941919d7328c60fc1c2b49fb2788671bf9697c2923364c96d07`, matching the manifest.
The matching `POST .../locate` request returned `matched`, page 72, and normalized word
rectangles for the real pilot document.

## Deployment gate

Not passed. The currently configured Railway production service has no active deployment and its
latest recorded deployment is failed/stopped. The existing Vercel production deployments predate
this worktree. No deployment was attempted because publishing is an external state change that was
not authorized by this implementation request. The required Vercel/Railway Act 56 smoke therefore
remains the exact unsatisfied completion gate.
