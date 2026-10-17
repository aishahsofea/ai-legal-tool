# Chat box UI: collapsible sidebar, copy, share, multi-line input

## Problem

Five gaps in the chat workspace UI.

1. **Sidebar can't collapse.** `ThreadSidebar` (`frontend/components/locus-workspace/ThreadSidebar.tsx:5`) is always open. On desktop it takes a fixed column in the `chamber-grid-app` grid (`frontend/app/workspace/page.tsx:166`). There is no toggle.
2. **No copy.** Neither user messages nor model responses have a copy control. `grep -i clipboard` over `frontend/components` and `frontend/app` finds nothing.
3. **No share.** `ConversationHeader.tsx` has `Highlights`, `Memo` and `Export` buttons. All three are `disabled` with title "Coming soon". Nothing shares a whole session or a single response.
4. **Shift+Enter does not insert a newline.** `Composer.tsx` renders a single-line `<input>` (`Composer.tsx:25`), so a newline can't be typed at all. The hint under the send button still says `⇧⏎ NEWLINE` (`Composer.tsx:51`). The hint is wrong today.

5. **Dead buttons.** These render but do nothing. Each is `disabled` with title "Coming soon" and has no handler:
   - `Save as memo`, `Highlight passage`, `Cite all` under every model response (`Messages.tsx:301-303`).
   - `Highlights`, `Memo`, `Export` in the thread header (`ConversationHeader.tsx:12-14`).
   - `Filter` in the sources panel (`SourcesPanel.tsx:50`).
   Nothing else in the repo references them (checked with grep). They suggest features that don't exist.

Cause of 4 is read from the code. I have not reproduced it in the browser.

## Scope

1. **Collapsible sidebar.** Add a toggle that hides and shows `ThreadSidebar`. Grid collapses so the conversation takes the freed width. Remember the state across reloads (localStorage, wrapped in try/catch). Keep the existing mobile layout (`max-md`) as is.
2. **Copy.** A copy button on every message, user and model. Copies the plain message text. For a model response, copy the answer text only, not the receipt or citation chrome. Show a short "Copied" confirmation. Fall back gracefully when `navigator.clipboard` is unavailable.
3. **Share.** Two actions:
   - Share a single response.
   - Share the whole session.
   Decide the mechanism in this issue before building (see Open question).
4. **Multi-line input.** Replace the `<input>` with an auto-growing `<textarea>`. Enter sends. Shift+Enter inserts a newline. Cap the height (about 6 lines), then scroll. Don't send while an IME composition is active. Keep the `⇧⏎ NEWLINE` hint, which becomes true.

5. **Remove dead buttons.** Delete the seven stubs listed in Problem item 5. Drop the `OutlineButton` import from `Messages.tsx` if it ends up unused. Export is replaced by the share work in item 3. If a stub is wanted later, it comes back with a working handler.

## Open question

What does "share" produce?
- (a) Copy as Markdown or plain text to the clipboard. No backend. Smallest.
- (b) A read-only link. Needs a backend endpoint, storage, and a decision about who can open it. This is legal-domain data, so access rules matter.

Proposal: ship (a) first via the `Export` slot in the header and a per-response menu. File (b) as a separate placeholder issue. Needs the user's call.

## Acceptance criteria

- [ ] Sidebar toggle hides and shows the thread list. State survives reload. Mobile layout unchanged.
- [ ] Every message has a copy control. The clipboard holds exactly the visible message text.
- [ ] A single response can be shared. The whole session can be shared. Output matches what the chosen mechanism promises.
- [ ] Shift+Enter inserts a newline. Enter sends. Empty or whitespace-only input still can't send. Input is disabled while loading, as now.
- [ ] Textarea grows with content up to the cap, then scrolls.
- [ ] No disabled "Coming soon" button remains in the thread view, header or sources panel.
- [ ] Keyboard reachable and labelled (`aria-label`) for every new control.
- [ ] Frontend tests cover the Enter / Shift+Enter behaviour and the copy action.

## Files

- `frontend/components/locus-workspace/Composer.tsx`
- `frontend/components/locus-workspace/ThreadSidebar.tsx`
- `frontend/components/locus-workspace/ConversationHeader.tsx`
- `frontend/components/locus-workspace/Messages.tsx`
- `frontend/components/locus-workspace/SourcesPanel.tsx`
- `frontend/app/workspace/page.tsx`

## Out of scope

- Read-only share links and their backend, unless the Open question picks (b).
- File upload and drop-a-brief behaviour. The `▤` button is a separate stub.
- Building the memo, highlight or cite-all features. This issue only removes the buttons.
- Changes to the agent graph or API contract.

## Sequence

Five independent slices. Suggested order, smallest and most visible bug first:

1. Multi-line input. It is a bug: the UI promises a newline it can't deliver.
2. Copy buttons.
3. Collapsible sidebar.
4. Remove dead buttons. Tiny. Do the header `Export` removal together with Share so the slot isn't empty twice.
5. Share. Last, because it needs the Open question settled.

