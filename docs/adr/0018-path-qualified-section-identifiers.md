# Identify a chunk by its division path, not (act, section number)

Date: 2026-09-15

ADR 0002 built section-level chunking on one assumption: a section number identifies a chunk within an Act. `#75` found that false the day a schedule restarts numbering at 1. The dedup in `corpus/extraction.py:227-229` already keys on `(division, section_number)`, not on section number alone:

```python
deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
for chunk in raw:
    deduplicated[(chunk["division"], chunk["section_number"])] = chunk
```

Three places still key on `(act_number, section_number)` as if that were the whole identity: the exact-match lookup behind `lookup_section()` (`agent/retrieval/search.py:273-357`), ADR 0017's English-sibling resolution (`#50`, not yet built), and the eval dataset (`#73`). None of them can be correct while one Act holds several things numbered `1` — a body section, a schedule paragraph, sometimes both in the same page range.

This ADR supersedes ADR 0002's Phase 3 description ("regex-based section header detection on text-layer PDFs") and the citation-accuracy argument built on section number alone being a key. It settles the division model and the identifier shape that `#93`, `#94`, and `#95` implement. It changes no code — `corpus/extraction.py` is out of scope here, per `#91`.

## Decisions

**A division is one run of numbering.** CONTEXT.md already defines the term; this ADR fixes which divisions exist and gives each a place in the identifier:

- **Front matter and the table of contents.** Not addressable. No chunk carries this span's content today: text before the first heading or section match falls through `_extract_chunks` unassigned. None should carry it either — a table-of-contents row is not citable text. `#93` gives the extractor a name for this span so the section pattern can stop being tight enough to reject it by shape alone. The ADR-level decision is that this division never produces a path.
- **The body.** Exactly one per Act, from the enacting formula. Numbered by `_SECTION_RE`'s existing capture: 1 to 3 digits, optionally followed by 1 to 2 uppercase letters (`1`, `90A`).
- **A schedule.** Zero or more per Act, each its own division, numbered independently of the body and of every other schedule. A schedule declares its own item scheme: paragraphs by default, or the instrument's own scheme where it reprints one — Act 512's Geneva Conventions number by `ARTICLE <n>`. An incorporated instrument is not a fifth kind of division; it is a schedule whose item scheme is `art` instead of `para`.
- **The list of amendments.** Zero or one per Act. Like front matter, nothing in it is an item, so it never produces a path either.

A division's kind (body, schedule, amendments, front matter) is language-independent. A Malay schedule is still a schedule; only its printed heading differs.

**The path grammar:**

```
path          = body-path | schedule-path
body-path     = "s." token
schedule-path = "sched." ordinal ["/" item]
item          = ("para" | "art") "." token
ordinal       = positive integer
token         = 1-3 digits, optionally followed by 1-2 uppercase letters
```

Two segments at most, joined by one `/`. `token` is exactly `_SECTION_RE`'s capture group, upper-cased — a body section's token is byte-identical to its `section_number` today.

`ordinal` is the schedule's 1-based position in appearance order among schedule-kind divisions in the document, not a parse of the printed word. Act 777 prints "FIRST SCHEDULE" and "SECOND SCHEDULE" in that physical order, so position and label agree in the common case. Act 588 prints its only schedule as bare "Schedule", with no ordinal word to parse at all, and position still gives it `sched.1`. Position is a feature `_division_boundaries` already computes; a bilingual FIRST/PERTAMA ordinal-word parser is not needed and is not built.

`item` is omitted for a schedule's content taken as a whole — its heading to the next boundary, with no numbered paragraph inside it. Today's `current_num = ""` sentinel (`corpus/extraction.py:199`, added by `#89`) becomes "no item segment" rather than an empty string. The body never omits `item`: content before a body's first section number is front matter, never a bodiless body chunk.

The item-kind vocabulary (`para`, `art`) is open. A future numbering scheme adds a third kind without renumbering or reshaping any existing path.

`path` is a new, additive column alongside `division` and `section_number`, not a replacement for either. `division` keeps its current value and meaning — the heading as the Act prints it, per CONTEXT.md.

**`section_number` stays populated only for body chunks.** A schedule paragraph or article chunk carries `section_number = ""`, the value the whole-schedule case already uses today. This is the smallest change that removes the ambiguity at its root. Every consumer that predates this ADR reads `(act_number, section_number)`. After this change, that lookup only ever matches a body section — the safe, correct subset for it to see — so it never has to learn about schedules to stay correct.

**A NULL `path` reads as a body section.** `path` arrives the way `division` did: a nullable additive column (`#95`, following the pattern ADR 0016 set for provenance columns). A row with no `path` predates schedule support entirely, so by construction it is a body row — its `division` is already `NULL`/`'body'` for the same reason. It is read as `COALESCE(path, 's.' || section_number)`, the same COALESCE-at-read-time approach `_select_columns` already uses for `division` (`agent/retrieval/search.py:164-171`) — computed at query time, not backfilled. Two kinds of pre-`#94` row have an empty `section_number` but no path: a list-of-amendments chunk, and a schedule chunk extracted before this ADR. Both COALESCE to the inert path `"s."`, which matches no real lookup. `#94` stops emitting these rows for anything but a genuine schedule, so the case does not outlive its own implementation window.

**`exact_section_lookup` and `lookup_section()` keep their external shape and gain path matching.** The tool's `section` parameter still accepts a bare number, unchanged for the LLM and every existing caller. Internally: an input that parses against the grammar above is matched against the `path` column exactly. Anything else is matched against `section_number`, as today. That fallback is now unambiguous, because only body rows have a `section_number` to match. An unqualified "section 1" resolves to the body section not because of an ordering trick, but because it is the only row a bare `section_number` lookup can see. The `body_first` `CASE WHEN` in `exact_section_lookup` (`agent/retrieval/search.py:321-327`) becomes dead code once this ships; `#95` should remove it. A schedule paragraph or article is reachable only by its path (`sched.2/para.1`), which `lookup_section` cannot express until `#95` teaches it the grammar — `#95`'s scope, not this ADR's.

**Named answers for the three consumers `#91` raised:**

- `agent/retrieval/search.py`'s exact-match lookup: keys on `path`, falls back to `section_number` (body-only) for a bare number, per the "`section_number` stays populated only for body chunks" and "A NULL `path` reads as a body section" decisions above.
- ADR 0017's English-sibling resolution (`#50`): the decision survives unchanged — the English sibling of a Malay body section is still an English body section. What moves is the key it resolves through: after this ADR, only a body chunk populates `section_number` — which means `(act_number, section_number)` was implicitly body-scoped all along. `#50` can be written against `exact_section_lookup`'s existing signature with no new parameter. ADR 0017 is not edited; this is noted on `#50` instead.
- The eval dataset (`#73`): wherever a case would have keyed on `(act_number, section_number)`, it now keys on `(act_number, path)` — `path` subsumes `section_number` as the structural half of the key and makes a schedule-paragraph case expressible for the first time. `#73`'s own open question, whether and how a case also states a `language`, is untouched here.

## Considered options

- **Parse the schedule's printed ordinal word (FIRST/SECOND, PERTAMA/KEDUA) into the path.** Rejected. It needs a bilingual ordinal lexicon and fails outright on a bare "Schedule" (Act 588) or a lettered/numbered suffix ("SCHEDULE A") that `DIVISION_PATTERN` already accepts. Appearance order is already computed, always defined, and agrees with the printed label whenever one exists.
- **Reuse the Statutory Reference Graph's `provision_id` grammar** (`act:<n>/section:<num>/subsection:<x>/paragraph:<label>`, `reference_graph/resolver.py:33-95`). Rejected. That grammar resolves references down to subparagraph offsets within one Act's graph. A retrieval chunk is section-level by ADR 0002 and stays that way — it has no subsection identity to name. The two grammars solve different problems at different granularity and are kept separate rather than forced into one shape.
- **Give every chunk a `section_number`, schedule items included, and let consumers filter on `division`.** Rejected. This is what today's code already does, and it is the bug. A consumer that forgets to filter silently collides a schedule paragraph with a body section — and three consumers currently do forget. Leaving `section_number` populated only for the case it was always meant for removes the failure mode instead of asking every future consumer to remember a filter.
- **Add an explicit `path` parameter to the `lookup_section()` tool signature now.** Rejected for this ADR. The grammar sniff keeps the LLM-facing tool shape stable through `#95`; a new parameter is only worth adding once something can populate and query it.

## Consequences

- `corpus/extraction.py`'s dedup key, `exact_section_lookup`, `Citation`, and the receipt locator all gain `path` in `#95`. No code changes here.
- The `body_first` ordering in `exact_section_lookup` becomes removable for the same reason (see Decisions above) — `#95` inherits the simplification, not an extra task.
- `docs/adr/0002-section-level-chunking.md` is unedited — see the opening paragraph for what it supersedes. Its scanned-PDF exclusion stands.
- `docs/adr/0017-english-sibling-resolution-for-bm-retrieval-wins.md` is unedited, per Decisions above.
- CONTEXT.md's Division term is unedited. It still correctly describes today's `(division, section_number)` key — `path` is not real until `#95` ships. `#95`'s PR updates it, per CLAUDE.md's rule that living docs change in the same change that makes them true.
- `#95` inherits a settled grammar and can be written without reopening the division model, the identifier shape, or the lookup signature.

## Related

- ADR 0002 — section-level chunking. Superseded as described above; not edited.
- ADR 0016 — immutable corpus provenance; sets the nullable-additive-column pattern `path` follows.
- ADR 0017 — English-sibling resolution; confirmed to survive, per Decisions above.
