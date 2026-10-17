# Analysis: #246 Chat box UI (collapsible sidebar, copy, share, multi-line input, dead buttons)

This was a non-interactive run, so the Stage 1 findings and the Stage 2 plan are both below. Neither gate has been approved. No code was written.

Two Bash checks were blocked by permissions: a repo-wide grep and running the vitest suite. The research used `Read` and CodeGraph instead. Every claim below comes from source I read, except where it says otherwise.

---

## Stage 1: Findings

### Problem

The issue asks for five separate changes to the chat workspace:
1. A toggle that collapses the thread sidebar, remembered across reloads.
2. A copy button on every message.
3. Share for a single response and for the whole session. The mechanism is still undecided.
4. Shift+Enter inserts a newline. This means replacing the single-line `<input>` with a `<textarea>` that grows with its content.
5. Removing seven disabled "Coming soon" buttons.

### Current state

**Composer**
- `frontend/components/locus-workspace/Composer.tsx:24-30` renders an `<input>` with no `onKeyDown`. Enter submits only because a form with one input submits on Enter by default.
- The hint at `Composer.tsx:47` says `⇧⏎ NEWLINE`. That is false today. The issue cites line 51, but the line is 47.
- The form is a grid: `grid-cols-[auto_minmax(0,1fr)_auto_auto]` (`Composer.tsx:20`). The buttons use `h-full`, so they stretch with the row. A taller textarea will make the Upload and Send buttons taller too, so the alignment needs a decision.
- An existing test, `Composer.test.tsx:7-32`, uses `getByPlaceholderText` and clicks Send. It should still pass after the swap.
- `QueryPrefill` sets the input from `?q=` (`app/workspace/page.tsx:74-82`). Any auto-grow code must therefore resize when the value changes, not only inside `onChange`.

**Sidebar**
- `ThreadSidebar.tsx:23` is an `<aside>` with no collapse state.
- The grid columns live in CSS, not in Tailwind classes:
  - `globals.css:156`: `.chamber-grid-app { grid-template-columns: 256px minmax(0, 1fr); }` at ≥768px.
  - `globals.css:161`: `.receipt-open.chamber-grid-app { grid-template-columns: 256px minmax(420px, 1fr) 8px var(--receipt-pane-width) }` at ≥1200px.
- The sidebar width also appears in JS. `ReceiptPaneResizer.tsx:5` sets `WORKSPACE_SIDEBAR_WIDTH = 256`, and `maxReceiptPaneWidth` subtracts it (`:16`, `:26`). With the sidebar collapsed, the receipt pane's maximum width would still be 256px too small unless the clamp knows the sidebar's current width.
- There is already a pattern for saving UI state: `RECEIPT_WIDTH_STORAGE_KEY = "locus.receipt-pane-width.v1"`, read in a mount effect (`page.tsx:45`, `:138-148`). It has no try/catch. The issue asks for one on the new key. That matters for Safari private mode and storage that is turned off.
- Below 768px (the `max-md` styles), the sidebar becomes a horizontal strip at most 168px tall (`ThreadSidebar.tsx:23,31`). The issue says to leave that unchanged.

**Copy**
- The issue says `grep -i clipboard` finds nothing. **That is wrong.** `SourcesPanel.tsx:34-39` has `copyCitation`. It calls `navigator.clipboard.writeText` with no fallback, shows a "Copied" state, and resets it with a 1600ms `setTimeout`. That is the closest existing idiom to follow.
- `UserMessage` renders `message.content` as plain text (`Messages.tsx:309-319`).
- `AssistantMessage` renders `message.content` as **markdown** through `ReactMarkdown` plus `rehypeCitationLinks` (`Messages.tsx:282-294`). The source map, the sources list, commentary and the reasoning trace are separate siblings. So "copy the answer only" equals `message.content`. But `message.content` is markdown source, not the rendered text. See Open questions.

**Share and the header**
- `ConversationHeader.tsx:12-17` has `Highlights` and `Memo` (`OutlineButton`) and `Export` (`PrimaryButton`). All three are disabled. The component takes only `title`.
- Container-query CSS depends on those buttons. `globals.css:146-148` and `:214-235` hide `.conversation-header-secondary-action` and `.conversation-header-export-label` when the pane is under 700px wide. Under 420px they hide the whole actions group. If a sidebar toggle goes in the header, it must sit outside `.conversation-header-actions`, or it disappears on narrow panes.

**Dead buttons**
- `Messages.tsx:300-304`: an action row with three disabled buttons. After they go, `OutlineButton` is unused in `Messages.tsx:3`. `Mono` is still used.
- `ConversationHeader.tsx:12-14`: three disabled buttons.
- `SourcesPanel.tsx:50-56`: the Filter button. **But nothing renders `SourcesPanel` at all.** The barrel `components/locus-workspace/index.ts` does not export it. `page.tsx` does not import it. CodeGraph lists no callers. The whole component is dead code, not just the Filter button.

**Tests**
- Vitest and Testing Library are in use (`Composer.test.tsx`, `Messages.test.tsx`).
- Neither test file references the stub buttons, so removing them breaks no test.
- The vitest run was blocked in this session, so I could not confirm that the suite passes now. A memory note says `npm test` needs nvm/Node 22 set up in Bash-tool shells.

**Docs**
- No change touches the agent graph, the API, env vars or the top-level structure. The CLAUDE.md doc-sync rule does not apply.
- No ADR guarantee is affected.

### Proposed changes

| # | Change | Where |
|---|---|---|
| 1 | Replace `<input>` with `<textarea rows={1}>`. In `onKeyDown`: Enter without Shift, and not composing, calls `preventDefault()` then `form.requestSubmit()`. "Not composing" means `!e.nativeEvent.isComposing && e.keyCode !== 229`. Shift+Enter keeps the default newline. Auto-grow by setting `height = min(scrollHeight, ~6 lines)` in a layout effect keyed on `input`. Use `overflow-y-auto` once the cap is hit. Pin the buttons to the bottom (`self-end`) or keep `h-full`; this is a visual call. | `Composer.tsx`, `Composer.test.tsx` |
| 2 | Add a small `copyText(text)` helper. Use `navigator.clipboard.writeText` and return a status when it fails or is unavailable; optionally fall back to a hidden textarea plus `execCommand("copy")`. Add a `CopyButton` that shows "Copied" for about 1.6s, matching `SourcesPanel`, and has an `aria-label`. Wire it into `UserMessage` and into the `AssistantMessage` action row. | new `copyText`/`CopyButton` (e.g. in `locus-workspace/`), `Messages.tsx`, `Messages.test.tsx` |
| 3 | Add a `sidebarCollapsed` state in `WorkspaceInner`, hydrated from `locus.sidebar-collapsed.v1` with try/catch. Add a `sidebar-collapsed` class on `.chamber-grid-app`, plus CSS rules at ≥768px and ≥1200px that drop the 256px column. Hide the `<aside>` at ≥md when collapsed. Make `maxReceiptPaneWidth`, `clampReceiptPaneWidth` and `defaultReceiptPaneWidth` take a sidebar width (default 256) and pass 0 when collapsed. Put a toggle (`aria-expanded`, `aria-controls`) in `ConversationHeader`, left of the title, so it stays reachable when the sidebar is hidden. | `page.tsx`, `globals.css`, `ThreadSidebar.tsx` (id), `ConversationHeader.tsx`, `ReceiptPaneResizer.tsx` |
| 4 | Delete the stubs: three in `Messages.tsx`, plus `Highlights` and `Memo` in the header. For `SourcesPanel`, delete the whole file rather than one button (see Open questions). Drop the `OutlineButton` imports that end up unused. Drop the dead `.conversation-header-secondary-action` CSS. | `Messages.tsx`, `ConversationHeader.tsx`, `SourcesPanel.tsx`, `globals.css` |
| 5 | Share via option (a), the clipboard. Write pure formatters:<br>• `formatResponseForShare(message)`: the answer markdown plus a "Sources" list of `[n] Act {act_number} {act_title} § {section/path}, {pdf_url}`.<br>• `formatSessionForShare(title, messages)`: the title, then each turn as `**You:**` / `**Locus:**` with per-response sources.<br>Replace the header `Export` with an enabled `Share thread`, keeping the `conversation-header-export*` classes so the responsive icon still works. Add `Share` to the response action row. | new `shareFormat.ts` + test, `ConversationHeader.tsx`, `Messages.tsx`, `page.tsx` (pass `messages`) |

### Effort

**M overall.** Each of the five slices is S, but there are five.
- The Composer and the dead-button removal are about an hour each.
- The sidebar is the largest. It touches CSS in two breakpoints and changes the receipt-pane clamp signature.
- Share is small once option (a) is chosen. Option (b) would be L and is out of scope.

### Risk

- **Receipt pane clamp.** If the clamp is not given the sidebar width, a collapsed sidebar leaves the receipt pane capped 256px narrower than the space it has. Nothing breaks, but it is a quiet bug. `clampReceiptPaneWidth` has callers in `page.tsx:101,142` and in the resizer.
- **Hydration flash.** The sidebar state is read after mount, like the receipt width. A user who collapsed it sees it open for one frame on reload. That is the same tradeoff `page.tsx` already accepts.
- **Textarea in the grid.** Auto-grow changes the composer row height. If the buttons keep `h-full`, they grow to 6 lines tall. Check this visually on desktop and below the `sm` breakpoint (the 48px column).
- **IME.** Without the `isComposing` / `keyCode 229` guard, Enter that confirms a CJK or Malay IME candidate sends the message. jsdom cannot really test this. The unit test can only simulate the flag.
- **Mobile Enter.** On touch keyboards Enter will now send, as it does today. There is no Shift key, so a newline cannot be typed on mobile. The `⇧⏎` hint is meaningless there; consider hiding it below `sm`.
- **Clipboard.** `navigator.clipboard` exists only in secure contexts (HTTPS or localhost) and may reject without a user gesture. Production runs on Vercel over HTTPS, so the fallback matters mainly for odd browsers. `SourcesPanel`'s current pattern awaits with no catch, which would be an unhandled rejection. Don't copy that part.
- **Legal-data sharing.** Option (a) puts thread content on the user's clipboard. No new exposure: the user can already select and copy the text. Option (b) is the one that needs access rules, as the issue says.
- **Test gaps.** No tests cover `ConversationHeader`, `ThreadSidebar` or the workspace grid. The acceptance criteria require tests only for Enter/Shift+Enter and copy. I'd add a formatter unit test for share and a header test for the toggle's `aria-expanded`.

### Open questions

1. **Share mechanism.** This is the issue's own open question. I recommend (a), the clipboard as Markdown, and filing (b) as `"Read-only share links (placeholder, needs access-rule decision)"`. Optionally use `navigator.share` when it exists (mobile), falling back to the clipboard. The plan below assumes (a).
2. **"Exactly the visible message text" vs markdown.** `message.content` for a response is markdown (`**bold**`, lists, maybe tables). There are two choices:
   - copy the markdown source, which pastes well into docs and chat apps;
   - copy the rendered `innerText`, which is literally what is visible but loses structure.
   
   I recommend the markdown source. The acceptance criterion would then read "exactly the message text as sent (markdown)".
3. **`SourcesPanel`.** The whole file is unreferenced. Should it be deleted, or only its Filter button? I recommend deleting the file. That is within the issue's intent ("they suggest features that don't exist") and leaves no dead component. The issue lists only the button, so this widens scope slightly.
4. **Where the sidebar toggle goes.** In `ConversationHeader`, left of `THREAD /` (my recommendation), so it can reopen the sidebar while hidden. The other option is a rail inside the sidebar plus a separate reopen control.
5. **The issue's evidence is off in two places.** The clipboard grep claim is wrong (`SourcesPanel.tsx:36`), and the hint is at `Composer.tsx:47`, not `:51`. Worth correcting in the issue so the record is accurate.

---

## Stage 2: Phased plan

This assumes the recommendations above: share option (a), copy markdown source, delete `SourcesPanel`, toggle in the header. The order follows the issue's `## Sequence`.

### Phase 1: Multi-line composer
- **Goal:** Shift+Enter inserts a newline, Enter sends, and the box grows up to about 6 lines then scrolls.
- **Files:** `Composer.tsx`, `Composer.test.tsx`
- **Changes:**
  - Swap `<input>` for `<textarea rows={1}>`, with `resize-none`, a `max-h` of about 6 lines, and `overflow-y-auto`.
  - Add `onKeyDown`: Enter without Shift and not composing calls `preventDefault()`. If `input.trim()` and not loading, it calls `e.currentTarget.form?.requestSubmit()`.
  - Add a layout effect on `input` that resets `height` to `auto`, then sets it to `scrollHeight`.
  - Align the buttons so they don't stretch.
- **Verify:**
  - `npm test -- Composer`. New cases: Shift+Enter adds `\n` and does not submit; Enter submits; Enter on whitespace does not submit; Enter while `isComposing` does not submit; the textarea is disabled while loading.
  - Manual check in `npm run dev` at desktop and mobile widths.

### Phase 2: Copy on every message
- **Goal:** each user message and each response has a labelled copy control.
- **Files:** new `components/locus-workspace/CopyButton.tsx` (with the `copyText` helper), `Messages.tsx`, `Messages.test.tsx`
- **Changes:**
  - `copyText` tries `navigator.clipboard.writeText`, then the `execCommand` fallback, and returns success or failure.
  - `CopyButton` uses `aria-label="Copy message"` / `"Copy response"`, shows "Copied" for 1.6s, and shows "Copy failed" on failure.
  - Put it in the `UserMessage` header row and the `AssistantMessage` action row. Hide it on the streaming tail when `content` is empty.
- **Verify:** mock `navigator.clipboard.writeText` in tests and assert it is called with exactly `message.content`. Assert the "Copied" text appears. Assert the fallback path when `navigator.clipboard` is undefined.

### Phase 3: Remove dead buttons (except Export)
- **Goal:** no disabled "Coming soon" controls left except `Export`. `Export` is replaced in Phase 5 so the header slot isn't emptied twice.
- **Files:** `Messages.tsx`, `ConversationHeader.tsx`, `SourcesPanel.tsx` (deleted), `globals.css`
- **Changes:**
  - Delete the three response stubs. The action row now holds only Copy.
  - Delete `Highlights` and `Memo`.
  - Delete `SourcesPanel.tsx`.
  - Remove `.conversation-header-secondary-action` from the container query.
  - Drop the unused `OutlineButton` imports.
- **Verify:**
  - `npm test`; `npm run lint`; `npx tsc --noEmit`.
  - Repo grep for `Coming soon` should match only `ConversationHeader` Export.
  - Repo grep for `SourcesPanel` should return nothing.

### Phase 4: Collapsible sidebar
- **Goal:** the toggle hides and shows the sidebar on desktop and remembers the state. Mobile is unchanged.
- **Files:** `ReceiptPaneResizer.tsx`, `page.tsx`, `globals.css`, `ConversationHeader.tsx`, `ThreadSidebar.tsx`
- **Changes, in order:**
  - (a) Add a `sidebarWidth` parameter (default `WORKSPACE_SIDEBAR_WIDTH`) to the three clamp helpers and thread it through `ReceiptPaneResizer`. With the default, behaviour is the same as today.
  - (b) Add `sidebarCollapsed` state with try/catch localStorage under `locus.sidebar-collapsed.v1`, and a `sidebar-collapsed` class on the grid.
  - (c) CSS: at ≥768px, `.sidebar-collapsed.chamber-grid-app { grid-template-columns: minmax(0,1fr) }` and hide the aside. Add the matching receipt-open variant at ≥1200px with three columns, shifting `grid-column` for main, resizer and layer.
  - (d) A header toggle button with `aria-expanded`, `aria-controls="thread-sidebar"` and an `aria-label`, outside `.conversation-header-actions`, hidden below md.
- **Verify:**
  - Unit tests: the clamp helper with `sidebarWidth=0`; the header toggle flips `aria-expanded` and calls back.
  - Manual: collapse, reload, still collapsed. Open a receipt with the sidebar collapsed and confirm the resizer can use the freed width. Resize below 768px and confirm the strip layout is unchanged.

### Phase 5: Share (clipboard Markdown)
- **Goal:** a single response and the whole session can be shared.
- **Files:** new `components/locus-workspace/shareFormat.ts` + `shareFormat.test.ts`, `ConversationHeader.tsx`, `Messages.tsx`, `page.tsx`
- **Changes:**
  - Pure `formatResponseForShare` / `formatSessionForShare`. Citations are listed by act, section or path (using the `citationMarker` fallback for Schedule items, ADR 0018) and `pdf_url`.
  - The header `Export` becomes an enabled `Share thread`. Keep the `conversation-header-export*` classes and the ↗ icon, and use `copyText`. Disable it when there are no messages.
  - Add `Share` to the response action row.
  - `page.tsx` passes `messages` and `title` to the header.
- **Verify:**
  - Formatter snapshot or assert tests, including a Schedule citation with an empty `section_number`.
  - A header test asserting the clipboard payload.
  - The repo grep for `Coming soon` now returns nothing.
  - File the placeholder issue for (b).

After all phases: run the full `npm test`, `npm run lint` and `npx tsc --noEmit`, then one manual pass checking the acceptance criteria in the browser.