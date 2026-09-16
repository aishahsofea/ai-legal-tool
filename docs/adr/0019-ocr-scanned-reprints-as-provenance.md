# Recover scanned reprints through OCR, not exclusion

Date: 2026-09-16

ADR 0002 excluded scanned PDFs from v1, detected by average characters per page under 100. Its own last line: "Coverage gap acknowledged." `#104` measured that gap. 23 of 1124 registered documents are blocked `scanned_image_only`, holding 796 pages. Because of them, seven Acts have no readable document in either language: 115, 119, 135, 150, 296, 465, 627.

This ADR replaces that consequence. ADR 0002's section-level chunking decision is untouched and stays current. This ADR settles what kind of provenance OCR text is and what has to stay reproducible about it. It does not pick how OCR is wired into `_extract_chunks` and `sidecar_payload` — `#104`'s Scope leaves two implementation shapes open, and the PR that builds the fallback decides between them. It does not fix `act-114-bm`'s missing enacting clause (`#101`, `#97`) or reopen the section-boundary regex.

## Decisions

- **OCR is a fallback inside the existing pipeline, not a second one.** The scanned check still decides whether OCR runs, at the same 100-characters-per-page threshold ADR 0002 set. When it says a document is scanned, every page of that document is OCR'd before extraction. When it doesn't, OCR never runs — the 1099 documents with a text layer go through extraction exactly as they do today.
- **OCR text is a different kind of provenance from a publisher's text layer, and this ADR accepts it as one.** ADR 0016 ties an Extraction Run's identity to its document, extractor, extractor version, and configuration hash, and rejects a replay that produces different output under the same identity. That guarantee asks for reproducibility, not a particular text source. The determinism evidence below shows Tesseract OCR reproduces exactly, so it qualifies under ADR 0016's existing rule rather than a new, lesser-trusted one.
- **Every OCR input that can change output joins `EXTRACTOR_CONFIG`.** Render DPI, the Tesseract language string per document language, and the Tesseract and Leptonica versions. Skipping the engine versions would let a Tesseract upgrade on a future machine silently change a scanned Act's chunk text under an extraction identity that claims to be unchanged. `EXTRACTOR_VERSION` bumps in the same change; Consequences covers what that means for the rest of the corpus.
- **One OCR pass supplies both the chunk text and the coordinate sidecar for a scanned document.** The Citation Receipt locator matches a quoted chunk against the sidecar's words; two separate OCR runs could disagree by a word and turn a real match into `not_found`. A scanned Act's sidecar is checked against its own original page geometry, the same way every other sidecar is. That holds regardless of which of the two implementation shapes the fallback ends up using.

### What was measured

23 documents (796 pages) were rendered at 300 DPI and OCR'd page by page with Tesseract through PyMuPDF — `eng` for English documents, `msa+eng` for Malay. The output went unchanged into `_extract_chunks`.

| set | docs | pages | chunks | chunks/page |
| --- | --- | --- | --- | --- |
| English | 8 | 325 | 335 | 1.03 |
| Malay | 15 | 471 | 480 | 1.02 |
| ready corpus, for comparison | 1099 | 53,622 | 62,310 | 1.16 |

Close to the rest of the corpus's rate. `msa+eng` beat `eng` alone on every Malay document tested — 194 chunks against 185 across six documents. Character counts differed by under 0.1%, so the gain is in finding section boundaries, not in reading more text.

One document, `act-114-bm`, produced 1 chunk from 10 pages under both language settings. That is `#101`'s missing-enacting-clause defect, not an OCR failure, and stays out of scope here.

**Determinism.** With Tesseract 5.5.2 and Leptonica 1.87.0, three separate processes OCR-ing the same page of Act 627 produced the identical word list (same SHA-256). Two separate processes extracting all of Act 150 produced the identical `chunk_set_hash`. Confirmed on one machine only — the engine-version keys in `EXTRACTOR_CONFIG` are what would turn a second machine's drift, if there is any, into a new identity instead of silent divergence.

**Coordinates.** On a scanned page, `page.get_textpage_ocr()` returns the same eight-field word tuples that `sidecar_payload` already keeps from a text-layer page's `get_text("words")` — both in that page's own PDF coordinates. A scanned Act can get real Citation Receipt highlights on its original bytes.

## Considered options

- **Vision-language models for scanned pages.** Rejected. Nebius has no Nemotron vision or parsing model — its available vision models are `google/gemma-3-27b-it` and `openbmb/MiniCPM-V-4_5`. Both were asked for bounding boxes around three known phrases on Act 627 page 20; neither model's boxes overlapped Tesseract's coordinates for the same words. Gemma missed by up to 305 pixels, MiniCPM by up to 118. Both read the text correctly and invented the positions. A highlight built from either would land on the wrong paragraph and still look verified.
- **A model-assisted approach with a cache in front of it, as `#77` sketches.** Not needed here. `#77`'s cache exists because a model's output isn't guaranteed to repeat; the determinism evidence above shows Tesseract's does, with no cache.
- **Loosen the section-boundary regex to fix `act-114-bm` instead of leaving it to `#101`.** Already tried and reverted before this ADR. It let the table of contents read as body text and pushed the real section numbers out of range.

## Consequences

- `EXTRACTOR_VERSION` bumps and `CONFIGURATION_HASH` changes once OCR support and its new config keys land. That mints a new extraction identity for all 1124 documents, not only the 23 this recovers. A full re-extraction is already owed under `#89` — the manifest holds runs at extractor 2.0.0 while `main` computes a newer version, and the live database still serves 2.0.0 everywhere. This ADR's version bump rides that same re-extraction instead of asking for a second one.
- `docs/adr/0002-section-level-chunking.md` stays unedited — see the opening paragraph for what it supersedes.
- Activation stays gated by ADR 0016. A recovered document reaches `ready` and can be shadow-embedded, but nothing moves from the 23 currently blocked documents into what retrieval serves until an operator activates its verified extraction.
- `act-114-bm` stays effectively unreadable to a practitioner until `#101`/`#97` land, even though it reaches `ready` as a single low-value chunk. The PR that ships OCR support says so rather than counting it as recovered.
- Only two of the three `_is_scanned` copies `#104` named are reachable. `corpus/extraction.py`'s and `corpus/manifest.py`'s inline duplicate are both live. `scraper/step4_extract.py`'s `_is_scanned`, `_extract_chunks`, and `extract_act` have no caller — `run_step4()` already delegates to `corpus.extraction.extract_manifest`. The shared-check PR deletes that copy instead of adding a third import.

## Related

- ADR 0002 — section-level chunking; this ADR replaces its scanned-PDF exclusion and leaves the rest standing.
- ADR 0016 — immutable corpus provenance; this ADR extends its identity and activation guarantees to say OCR text qualifies.
- `#104` — the issue this ADR is part of; the OCR fallback, config keys, version bump, and re-extraction it describes are separate PRs sequenced after this one.
- `#89` — extractor version drift and the owed re-extraction this ADR's version bump rides instead of duplicating.
- `#101`, `#97` — `act-114-bm`'s missing enacting clause and the table-of-contents boundary problem, out of scope here.
