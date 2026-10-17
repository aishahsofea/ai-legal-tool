# Decisions: #246 Chat box UI (collapsible sidebar, copy, share, multi-line input, dead buttons)

This was a non-interactive run, so nobody approved these decisions. They resolve the open questions in `analysis.md` so the build can start. Anything marked **needs the user** should be confirmed before the PR merges.

I could not read the skill file at `/Users/aishahsofea/Developer/ai-standards/skills/decide/SKILL.md` because permission was denied. The structure below is my own: one section per decision, each with the choice, the reason, and what it changes.

---

## D1. Share uses the clipboard as Markdown (option a)

**Decision:** Share copies Markdown to the clipboard. There is no backend, no link, and no `navigator.share` in this issue.

**Why:**
- It is the smallest option that meets the acceptance criterion "a single response can be shared, the whole session can be shared."
- It adds no exposure of legal data. The user can already select and copy the same text.
- Option (b), a read-only link, needs storage, an endpoint and an access-rule decision. That is an API contract change, and the issue lists it as out of scope.
- I left out `navigator.share` on purpose. It would add a second code path that jsdom can't test, and a mobile share sheet is a different feature. It can come back with (b).

**Changes:**
- The issue's Open question is closed as (a).
- Read-only share links get a placeholder issue: `Read-only share links (placeholder, needs access-rule decision)`. It goes through the house structure, and the access-rule question goes in `## Problem`.
- **Needs the user:** filing that issue publishes it, so confirm before filing.

## D2. Copy and Share take the Markdown source, not the rendered text

**Decision:** Copy puts `message.content` on the clipboard exactly as stored. For a response, that is the Markdown source.

**Why:**
- Markdown pastes cleanly into documents, email and chat apps, and keeps lists and bold text.
- Rendered `innerText` loses that structure, and it depends on the DOM, which is harder to test.
- The receipt, source map, sources list, commentary and reasoning trace are separate sibling elements (`Messages.tsx:282-294`), so `message.content` already means "the answer only."

**Changes:**
- The acceptance criterion changes from "the clipboard holds exactly the visible message text" to "the clipboard holds exactly the message text as sent (Markdown for responses)." This wording goes in the PR description.
- **Copy** on a response: `message.content` only, with no sources.
- **Share** on a response: `message.content` plus a `Sources` list. This is the only difference between the two buttons, and the reason to have both.

## D3. Share output format

**Decision:** Two pure functions in a new file, `frontend/components/locus-workspace/shareFormat.ts`:

- `formatResponseForShare(message)` returns the answer Markdown, a blank line, then `Sources` with one line per citation: `[n] Act {act_number} {act_title}, {section or path label}: {pdf_url}`.
- `formatSessionForShare(title, messages)` returns `# {title}`, then each turn as `**You:**` or `**Locus:**`. Each response turn carries its own sources block.

**Why:**
- Pure functions can be unit tested without a DOM.
- For the section label, use the existing `citationMarker` fallback for Schedule items (ADR 0018). It already handles citations with an empty `section_number`, and a second label rule would drift from it.

**Changes:**
- Add `shareFormat.test.ts`. It covers a normal citation, a Schedule citation with an empty `section_number`, a response with no citations (so no `Sources` heading), and a two-turn session.

## D4. Per-response controls are two buttons, not a menu

**Decision:** Each response's action row gets two buttons: `Copy` and `Share`. User messages get `Copy` only.

**Why:**
- With the three stubs removed, the row holds only these two buttons, so a menu adds clicks and focus-management code for no gain.
- The issue said "a per-response menu." Two buttons give the same result more simply.

**Changes:**
- Both buttons get an `aria-label`: `Copy message` on user messages, `Copy response` and `Share response` on responses.
- Both buttons are hidden on a streaming response while `content` is empty.

## D5. Clipboard helper with a fallback and a visible failure state

**Decision:**
- Add `copyText(text): Promise<boolean>` and a `CopyButton` in `frontend/components/locus-workspace/CopyButton.tsx`.
- `copyText` tries `navigator.clipboard.writeText` inside try/catch. It falls back to a hidden textarea plus `document.execCommand("copy")`, and returns `false` if both fail.
- The button shows "Copied" for 1600ms, the same timing as the old `SourcesPanel` code. On failure it shows "Copy failed."
- Share uses the same `copyText`.

**Why:**
- The issue asks for a graceful fallback.
- The only existing clipboard code (`SourcesPanel.tsx:34-39`) awaits without a catch. That leaves an unhandled rejection in insecure contexts, so the new code must not copy that part.

**Changes:**
- Tests mock `navigator.clipboard.writeText` and check that it is called with exactly `message.content`.
- They check that "Copied" appears.
- They check the fallback path when `navigator.clipboard` is undefined.

## D6. Delete all of `SourcesPanel.tsx`, not just its Filter button

**Decision:** Delete the file.

**Why:**
- Nothing renders it. The barrel `index.ts` doesn't export it, `page.tsx` doesn't import it, and CodeGraph shows no callers.
- If only the Filter button goes, a dead component stays behind that "suggests features that don't exist," which is the issue's own reason for removing stubs.

**Changes:**
- This widens the scope slightly, and the PR description must say so.
- Verify the deletion with a repo-wide search for `SourcesPanel` that returns nothing. The analysis run couldn't do this search because grep was blocked, so it has to run before deleting.
- If the search finds a reference, fall back to removing only the Filter button and note that in the PR.

## D7. The sidebar toggle goes in `ConversationHeader`, left of the title

**Decision:**
- The toggle button sits before `THREAD /` and outside `.conversation-header-actions`.
- It has `aria-expanded`, `aria-controls="thread-sidebar"`, and an `aria-label` of `Hide thread list` or `Show thread list`.
- It is hidden below `md`.

**Why:**
- When the sidebar is hidden, the toggle must still be reachable, so it can't live inside the sidebar.
- The container queries at `globals.css:214-235` hide the whole actions group on panes under 420px wide, so the toggle can't sit inside that group either.
- Below `md` the mobile strip layout stays as it is, as the issue requires, so the toggle has nothing to do there.

**Changes:**
- `ThreadSidebar`'s `<aside>` gets `id="thread-sidebar"`.
- `ConversationHeader` gets new props: `sidebarCollapsed`, `onToggleSidebar`, `messages`.
- Add a header test that the toggle flips `aria-expanded` and calls the callback.

## D8. Sidebar state is saved under `locus.sidebar-collapsed.v1`, with try/catch, read after mount

**Decision:**
- The state lives in `WorkspaceInner`.
- It is read from localStorage in a mount effect and written on change. Both are wrapped in try/catch, and a failure means "expanded."
- The grid gets a `sidebar-collapsed` class.

**Why:**
- This matches the existing `RECEIPT_WIDTH_STORAGE_KEY` pattern.
- The try/catch, which the issue asks for, covers Safari private mode and storage that is turned off.

**Accepted cost:** a user who collapsed the sidebar sees it open for one frame on reload. The receipt pane width already has the same flash. I'm not adding an inline pre-hydration script for this.

**Changes:**
- At ≥768px: a `.sidebar-collapsed.chamber-grid-app` rule with one column, and the aside hidden.
- At ≥1200px: a matching receipt-open rule with three columns, with `grid-column` shifted for main, the resizer and the receipt layer.

## D9. The receipt-pane clamp takes the sidebar width as a parameter

**Decision:**
- `maxReceiptPaneWidth`, `clampReceiptPaneWidth` and `defaultReceiptPaneWidth` gain a `sidebarWidth` parameter that defaults to `WORKSPACE_SIDEBAR_WIDTH` (256).
- Callers pass `0` when the sidebar is collapsed.

**Why:** without it, a collapsed sidebar leaves the receipt pane capped 256px narrower than the space it has. Nothing visibly breaks, so the bug would go unnoticed. The default keeps today's behaviour for every existing caller (`page.tsx:101,142` and the resizer).

**Changes:**
- This is the first commit of the sidebar phase.
- Add a unit test with `sidebarWidth=0`.

## D10. Composer: textarea, Enter and IME rules, button alignment, hint

**Decision:**
- Replace the `<input>` with `<textarea rows={1}>`, styled `resize-none overflow-y-auto` and capped at about 6 lines.
- A layout effect keyed on `input` sets the height to `auto`, then to `scrollHeight`. It is keyed on the value, not on `onChange`, so the `?q=` prefill at `page.tsx:74-82` also resizes the box.
- `onKeyDown` handles Enter:

| Key | When | Result |
|---|---|---|
| Enter, no Shift | input is not blank, not loading, not composing | `preventDefault()`, then `form.requestSubmit()` |
| Enter, no Shift | input is blank or whitespace | `preventDefault()`, nothing sent |
| Enter, no Shift | IME composition active | nothing sent |
| Shift+Enter | any time | browser default, which inserts a newline |

- "Composing" means `e.nativeEvent.isComposing || e.keyCode === 229`.
- The Upload and Send buttons use `self-end` and a fixed height equal to one row of the textarea, so they don't stretch as the box grows.
- The `⇧⏎ NEWLINE` hint stays, but is hidden below `sm`. Touch keyboards have no Shift key, so there the hint would be false again.

**Why:**
- The alignment was the one visual question left open. Buttons pinned to the bottom match common chat composers and avoid 6-line-tall buttons.
- Hiding the hint on mobile goes slightly beyond the issue's "keep the hint." The reason is the issue's own: the hint must be true.

**Changes:**
- New `Composer.test.tsx` cases:
  - Shift+Enter adds `\n` and does not submit.
  - Enter submits.
  - Enter on whitespace does not submit.
  - Enter while composing does not submit.
  - The textarea is disabled while loading.
- The existing test that finds the field by placeholder and clicks Send must still pass.

## D11. Dead-button removal is split around Share

**Decision:**
- Phase 3 removes the three response stubs, `Highlights` and `Memo` from the header, and `SourcesPanel`.
- `Export` stays until Phase 5. There it turns into an enabled `Share thread` button, which keeps the `conversation-header-export*` classes and the ↗ icon so the responsive label still works.
- `Share thread` is disabled when the thread has no messages.

**Why:** the issue's `## Sequence` asks that the header slot not go empty twice.

**Changes:**
- Remove the unused `.conversation-header-secondary-action` CSS.
- Remove the `OutlineButton` imports that end up unused.
- When Phase 5 lands, a repo search for `Coming soon` returns nothing.

## D12. Fix the issue's evidence in the PR, not by editing the issue now

**Decision:** two claims in #246 are wrong:
- `grep -i clipboard` does find something: `SourcesPanel.tsx:34-39`.
- The hint is at `Composer.tsx:47`, not `:51`.

Both corrections, plus the scope changes in D2, D4, D6 and D10, go in a short comment on #246 when the PR opens, and the PR references the issue.

**Why:** the issue is where the reasoning lives, so the record should be corrected there. Posting is outward-facing, so it waits for the human step rather than happening in this non-interactive run. **Needs the user:** approve posting the comment.

## D13. Build order

The phases follow `analysis.md`:
1. Multi-line composer
2. Copy
3. Remove dead buttons, except Export
4. Collapsible sidebar, starting with the clamp parameter
5. Share, including `Export` → `Share thread`

Each phase is its own commit on `agent/246-chat-box-ui-collapsible-sidebar-copy-share-mul`, and all of it ships in one PR. After each phase, run `npm test`, `npm run lint` and `npx tsc --noEmit`. Bash-tool shells need nvm and Node 22 set up first (see memory `project_frontend_node_test_setup`). The analysis run couldn't run the suite at all, so the first step is to confirm the baseline is green.

## D14. No doc sync, no ADR impact, no paid runs

- The change doesn't touch the agent graph, the API contract, env vars or the top-level structure. `README.md`, `CONTRIBUTING.md` and `CONTEXT.md` stay as they are.
- No ADR guarantee changes. D3 reuses ADR 0018's citation fallback without changing it.
- Nothing calls a model API, and every check finishes in under a few minutes, so there is no cost to report under the long-or-paid-runs rule.

---

## Needs the user before merge

1. Confirm share via the clipboard (D1), and approve filing the read-only-links placeholder issue.
2. Confirm the new copy criterion: Markdown source, not rendered text (D2).
3. Confirm deleting all of `SourcesPanel.tsx` (D6).
4. Approve posting the evidence-correction comment on #246 (D12).