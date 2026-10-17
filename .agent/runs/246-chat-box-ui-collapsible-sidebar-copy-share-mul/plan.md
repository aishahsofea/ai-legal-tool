# Plan: #246 Chat box UI (collapsible sidebar, copy, share, multi-line input, dead buttons)

This was a non-interactive run. Permission to read the skill file at `/Users/aishahsofea/Developer/ai-standards/skills/plan/SKILL.md` was denied, so this plan follows the structure of `analysis.md` Stage 2 and the decisions D1–D14 in `decisions.md`. No code was written. Nobody has approved anything in this plan. The four items under "Needs the user" must be confirmed before merge.

I checked the code facts in `decisions.md` against the current source with CodeGraph. They hold, with one addition: `citationMarker` is a private function in `Messages.tsx:18-20`, so the share formatter can't import it as things stand. Phase 5 moves it into `citationRefs.ts` first (step 5.1).

---

## Ground rules for every phase

- **Branch:** `agent/246-chat-box-ui-collapsible-sidebar-copy-share-mul`. There is one commit per phase and one PR for the whole issue. The PR references #246 (D13).
- **Before Phase 1:** set up nvm and Node 22 in the Bash-tool shell (memory `project_frontend_node_test_setup`). Then run `npm test`, `npm run lint` and `npx tsc --noEmit` in `frontend/` to get a green baseline. The analysis run couldn't run the suite at all. If the baseline is red, stop and record which tests fail before changing anything.
- **After each phase:** run `npm test`, `npm run lint` and `npx tsc --noEmit` again.
- **Comments:** one line each, and only to explain why (`.agent/standards/AGENTS.md`, CLAUDE.md). Put no narrative in the code. Reasoning goes in the PR.
- **Cost:** no model API calls, and every check finishes in a few minutes. There is nothing to report under the long-or-paid-runs rule (D14).
- **Docs:** no change to the agent graph, the API, env vars or the project structure. `README.md`, `CONTRIBUTING.md` and `CONTEXT.md` stay as they are. No ADR guarantee changes (D14).

---

## Phase 1: Multi-line composer (D10)

**Goal:** Shift+Enter inserts a newline and Enter sends. The box grows up to about 6 lines, then scrolls.

**Files:** `frontend/components/locus-workspace/Composer.tsx`, `frontend/components/locus-workspace/Composer.test.tsx`

**Steps**
1. Replace the `<input>` at `Composer.tsx:24-30` with `<textarea rows={1}>`. Keep the same `value`, `onChange`, `placeholder`, `disabled` and classes, and add `resize-none overflow-y-auto` plus a `max-h` of about 6 lines (`max-h-36` at `leading-6`).
2. Add a `useRef<HTMLTextAreaElement>` and a `useLayoutEffect` keyed on `input`. It sets `style.height = "auto"`, then `style.height = ${scrollHeight}px`. It is keyed on the value rather than on `onChange` so the `?q=` prefill (`page.tsx:74-82`) also resizes the box.
3. Add an `onKeyDown` handler:
   - If the key is not Enter, or Shift is held, return and let the browser act. Shift+Enter inserts a newline.
   - If `e.nativeEvent.isComposing || e.keyCode === 229`, return. That Enter confirms an IME candidate.
   - Otherwise call `preventDefault()`. Then, if `input.trim()` is non-empty and `!isLoading`, call `e.currentTarget.form?.requestSubmit()`.
4. Alignment: give the `ASK ›` span, the Upload button and both `PrimaryButton`s `self-end` and a fixed height of one textarea row (`h-12`, matching `min-h-12`) in place of `h-full`. They then stay pinned to the bottom as the box grows.
5. Hint at `Composer.tsx:47`: hide `⇧⏎ NEWLINE` below `sm`, because touch keyboards have no Shift key. Leave `ESC STOP · EDIT` as it is.

**Tests (`Composer.test.tsx`)**
- The existing test (find by placeholder, click Send) still passes unchanged.
- Shift+Enter: the value gains `\n` and `onSubmit` is not called. In jsdom a `fireEvent.keyDown` doesn't insert text, so use `userEvent.type(el, "a{Shift>}{Enter}{/Shift}b")` in a controlled harness and assert the value is `"a\nb"`.
- Enter with text calls `onSubmit` once.
- Enter on `"   "` doesn't call `onSubmit`.
- Enter with `isComposing: true` doesn't call `onSubmit`. jsdom can only simulate the flag; see Risks.
- The textarea is disabled while `isLoading`.

**Verify:** the three commands above. Then run `npm run dev` and check at about 1440px and about 375px wide: the box grows to the cap and then scrolls, and the buttons don't stretch.

---

## Phase 2: Copy on every message (D2, D4, D5)

**Goal:** every user message and every response has a labelled copy control. It copies `message.content` exactly, which is Markdown for a response.

**Files:** new `frontend/components/locus-workspace/CopyButton.tsx`, new `CopyButton.test.tsx`, `Messages.tsx`, `Messages.test.tsx`, and `index.ts` only if a caller outside the folder needs the new exports.

**Steps**
1. Write `copyText(text: string): Promise<boolean>` in `CopyButton.tsx`:
   - Call `navigator.clipboard?.writeText(text)` inside try/catch and return `true` if it succeeds.
   - Fallback: create a hidden off-screen `<textarea>`, select it, call `document.execCommand("copy")`, then remove the element. Return what `execCommand` returns, or `false` if it throws.
   - Unlike `SourcesPanel.tsx:34-39`, never leave the promise without a catch.
2. Write `CopyButton({ getText, label, idleText = "Copy", children? })` in the same file:
   - Use the `OutlineButton` from `@/components/chamber`, with `aria-label={label}`.
   - Its state is `idle | copied | failed`. Show "Copied" or "Copy failed" for 1600ms, then go back to idle.
   - Clear the timer on unmount.
   - Use `aria-live="polite"` on the text span so screen readers announce the change.
   - `getText` is a function so that Share in Phase 5 can reuse the button with a different payload.
3. `UserMessage` (`Messages.tsx:309-320`): add `<CopyButton label="Copy message" getText={() => message.content} />` to the `YOU · …` row.
4. `AssistantMessage` action row (`Messages.tsx:300-304`): add `<CopyButton label="Copy response" … />` next to the three stubs for now. Phase 3 removes the stubs. Render the button only when `message.content` is non-empty, so it is hidden on the streaming tail before text arrives.

**Tests**
- `CopyButton.test.tsx`:
  - Mock `navigator.clipboard.writeText`, then assert it was called with exactly the text and that "Copied" appears.
  - With `navigator.clipboard` undefined, stub `document.execCommand` and assert it was called with `"copy"`.
  - When both paths fail, "Copy failed" appears.
- `Messages.test.tsx`:
  - Clicking "Copy response" puts exactly `message.content` on the clipboard, including the Markdown syntax and no sources text.
  - "Copy message" on `UserMessage` does the same.
  - There is no copy button when `content` is `""`.

---

## Phase 3: Remove dead buttons, except Export (D6, D11)

**Goal:** no disabled "Coming soon" control is left except the header `Export`, which Phase 5 replaces.

**Files:** `Messages.tsx`, `ConversationHeader.tsx`, `SourcesPanel.tsx` (deleted), `frontend/app/globals.css`

**Steps**
1. **Do this first.** Search the repo for `SourcesPanel` (e.g. `git grep -n SourcesPanel`, which avoids the blocked repo-wide grep).
   - If the only hit is the file itself, delete `SourcesPanel.tsx`.
   - If something else references it, delete only the Filter button (`SourcesPanel.tsx:50-56`) and note the fallback in the PR (D6).
2. `Messages.tsx:301-303`: delete the three stub buttons. The action row now holds only Copy. Drop `OutlineButton` from the import at `Messages.tsx:3` if it is unused (`Mono` stays). `CopyButton` brings its own import.
3. `ConversationHeader.tsx:12-13`: delete `Highlights` and `Memo`. Drop `OutlineButton` from the import at `:1`.
4. `globals.css`: delete the `.conversation-header-secondary-action` rules (around `:146-148` and inside `:214-235`). Keep the `.conversation-header-export*` rules.

**Verify**
- The three commands.
- `git grep -n "Coming soon" frontend/` matches only the header `Export`.
- `git grep -n SourcesPanel` returns nothing, or only the file if the step 1 fallback was taken.

---

## Phase 4: Collapsible sidebar (D7, D8, D9)

**Goal:** a header toggle hides and shows the thread list at ≥768px, and the state survives a reload. The mobile strip layout (`max-md`) doesn't change.

**Files:** `ReceiptPaneResizer.tsx`, `ReceiptPaneResizer.test.tsx`, `frontend/app/workspace/page.tsx`, `globals.css`, `ConversationHeader.tsx`, new `ConversationHeader.test.tsx`, `ThreadSidebar.tsx`

**Steps, in this order**
1. **Clamp parameter (D9), its own commit.** In `ReceiptPaneResizer.tsx:15-28`, add `sidebarWidth = WORKSPACE_SIDEBAR_WIDTH` as the last parameter of `maxReceiptPaneWidth`, `clampReceiptPaneWidth` and `defaultReceiptPaneWidth`. Use it in place of the constant at `:16` and `:26`. Pass it through the inner calls at `:21`, `:27`, `:43`, `:46` and `:95`. Add a `sidebarWidth?: number` prop to `ReceiptPaneResizer`. With the default, behaviour is identical. Test: `maxReceiptPaneWidth(1440, 0)` is 256 more than `maxReceiptPaneWidth(1440)`, up to the 800 cap. Pick a viewport where the cap doesn't hide the difference, e.g. 1200.
2. **State (D8).** In `WorkspaceInner` (`page.tsx:90`):
   - Add `SIDEBAR_COLLAPSED_STORAGE_KEY = "locus.sidebar-collapsed.v1"` next to `RECEIPT_WIDTH_STORAGE_KEY` (`:45`).
   - Add `const [sidebarCollapsed, setSidebarCollapsed] = useState(false)`.
   - In a mount effect, read the key inside try/catch. Set `true` only when the value is `"1"`. Copy the eslint-disable comment pattern from `:141`.
   - Make `toggleSidebar` flip the state and write `"1"` or `"0"` inside try/catch. A failure is silent and means "expanded."
   - Compute `const sidebarWidth = sidebarCollapsed ? 0 : WORKSPACE_SIDEBAR_WIDTH`. Pass it to `clampReceiptPaneWidth` at `:101` and `:142`, and to `<ReceiptPaneResizer>` at `:231`.
3. **Grid class.** Add `sidebarCollapsed ? "sidebar-collapsed" : ""` to the `chamber-grid-app` className at `:166`.
4. **CSS (D8).** Read `globals.css:150-240` first. It holds the grid template and any `grid-column` placement for main, the resizer and the receipt layer.
   - At ≥768px: `.sidebar-collapsed.chamber-grid-app { grid-template-columns: minmax(0, 1fr); }` and `.sidebar-collapsed .thread-sidebar { display: none; }`.
   - At ≥1200px: `.sidebar-collapsed.receipt-open.chamber-grid-app { grid-template-columns: minmax(420px, 1fr) 8px var(--receipt-pane-width); }`. Move any explicit `grid-column` values one column left.
   - Leave every `max-md` rule alone.
5. **Sidebar id.** In `ThreadSidebar.tsx:23`, add `id="thread-sidebar"` and a `thread-sidebar` class to the `<aside>` (the class is the CSS hook from step 4).
6. **Toggle (D7).** `ConversationHeader` gains the props `sidebarCollapsed: boolean` and `onToggleSidebar: () => void`. Add a button before `THREAD /`, inside the left `div` and outside `.conversation-header-actions`:
   - `aria-expanded={!sidebarCollapsed}` and `aria-controls="thread-sidebar"`.
   - `aria-label` is `Hide thread list` or `Show thread list`.
   - `max-md:hidden`, and keyboard-focusable (it is a native `<button>`).
   - Wire it from `page.tsx:180`.

**Tests**
- The clamp test from step 1.
- `ConversationHeader.test.tsx`: clicking the toggle calls `onToggleSidebar`. Re-render with `sidebarCollapsed` flipped, and assert `aria-expanded` and `aria-label` change.

**Manual check:** run `npm run dev` at ≥1200px.
- Collapse the sidebar, reload, and confirm it is still collapsed.
- With the sidebar collapsed, open a receipt. Drag the resizer and press `End`, and confirm the pane can use the freed 256px.
- At 900px, confirm the toggle works with no receipt open.
- Below 768px, confirm the strip layout looks as it did and the toggle is hidden.

---

## Phase 5: Share as clipboard Markdown (D1, D3, D4, D11)

**Goal:** a single response can be shared, and so can the whole session. Both copy Markdown to the clipboard. After this phase no "Coming soon" text is left.

**Files:** `citationRefs.ts`, `Messages.tsx`, new `frontend/components/locus-workspace/shareFormat.ts`, new `shareFormat.test.ts`, `ConversationHeader.tsx`, `ConversationHeader.test.tsx`, `page.tsx`

**Steps**
1. Move `citationMarker` from `Messages.tsx:16-20`, with its one-line ADR 0018 comment, into `citationRefs.ts` and export it. Import it back into `Messages.tsx`. Nothing else changes; this keeps a single label rule (D3).
2. `shareFormat.ts`:
   - `formatResponseForShare(message: Message): string` returns `message.content`.
     - If there are citations, add a blank line, then `Sources`, then one line per citation: `[n] Act {act_number} {formatSourceTitle(act_title)}, § {citationMarker(c)}: {pdf_url}`.
     - Drop the `: {pdf_url}` part when `pdf_url` is missing.
     - With no citations, there is no `Sources` heading.
   - `formatSessionForShare(title: string, messages: Message[]): string` returns `# {title}`, then one block per turn, separated by blank lines.
     - User turns are `**You:**` plus the content.
     - Response turns are `**Locus:**` plus `formatResponseForShare(m)`.
     - Skip responses whose `content` is empty, such as a streaming tail.
3. Response action row: add a `CopyButton` with `label="Share response"`, `idleText="Share"` and `getText={() => formatResponseForShare(message)}`. It uses the same rule as Copy: hidden while `content` is empty.
4. Header: replace the disabled `Export` (`ConversationHeader.tsx:14-17`) with an enabled `Share thread` button.
   - It keeps the `conversation-header-export*` classes, the `↗` icon and `PrimaryButton size="compact"`.
   - It has `aria-label="Share thread"`.
   - It calls `copyText(formatSessionForShare(title, messages))` and shows "Copied" or "Copy failed" for 1600ms. Either reuse `CopyButton` with a `PrimaryButton`-styled variant, or add an `as` prop. Pick whichever keeps `CopyButton` smaller.
   - It is disabled when `messages.length === 0`, and enabled otherwise.
   - New prop: `messages: Message[]`. Pass it from `page.tsx:180`.

**Tests**
- `shareFormat.test.ts`:
  - A normal citation produces the exact line.
  - A Schedule citation with `section_number: ""` and `path: "sched.2/art.1"` shows `§ sched.2/art.1`.
  - A response with no citations has no `Sources` text.
  - A two-turn session gives the exact Markdown string.
  - An empty streaming tail is skipped.
- `Messages.test.tsx`: "Share response" puts `formatResponseForShare(message)` on the clipboard.
- `ConversationHeader.test.tsx`:
  - "Share thread" is disabled when there are no messages.
  - With messages, a click writes `formatSessionForShare(title, messages)`.

**Verify**
- The three commands.
- `git grep -n "Coming soon" frontend/` returns nothing.
- `npm run dev`: paste both payloads into a Markdown viewer and check them.

---

## Acceptance criteria, mapped

| Criterion (issue #246) | Where it is met |
|---|---|
| The sidebar toggle hides and shows the list, the state survives reload, and mobile is unchanged | Phase 4 |
| Every message has copy. The clipboard holds the message text as sent (Markdown for responses; D2 rewords this) | Phase 2 |
| A single response and the whole session can be shared | Phase 5 |
| Shift+Enter is a newline and Enter sends. Blank input can't send. The box is disabled while loading | Phase 1 |
| The textarea grows to the cap, then scrolls | Phase 1 |
| No "Coming soon" button is left | Phases 3 and 5 |
| Every new control is keyboard reachable and has an `aria-label` | Phases 2, 4 and 5 (all native `<button>`s) |
| Tests cover Enter/Shift+Enter and copy | Phases 1 and 2 |

After Phase 5: run the full `npm test`, `npm run lint` and `npx tsc --noEmit` once more. Then do one pass through the table above in the browser.

---

## Risks

- **IME.** jsdom only simulates `isComposing`. Real CJK or Malay IME behaviour is checked by hand in the browser, or noted in the PR as unverified.
- **Mobile Enter.** On touch keyboards Enter sends and a newline can't be typed. That matches today's behaviour. The hint is hidden there (D10).
- **Hydration flash.** A collapsed sidebar shows open for one frame on reload. The receipt pane width already has the same flash, and this cost is accepted (D8).
- **CSS grid placement.** If `globals.css` places columns by explicit `grid-column` numbers, every collapsed variant has to move them. The Phase 4 manual check with a receipt open is what catches a mistake here.
- **Clipboard.** `navigator.clipboard` needs a secure context. Production runs on Vercel over HTTPS. The `execCommand` fallback covers the rest, and "Copy failed" is shown when both paths fail.
- **Scope beyond the issue.** These must be listed in the PR:
  - all of `SourcesPanel` is deleted (D6);
  - two buttons instead of a menu (D4);
  - the hint is hidden below `sm` (D10);
  - the copy criterion is reworded (D2).

---

## Needs the user before merge

1. Confirm that share goes to the clipboard as Markdown (D1). Approve filing `Read-only share links (placeholder, needs access-rule decision)` in the house structure. Filing it publishes it.
2. Confirm the copy criterion: the Markdown source, not the rendered text (D2).
3. Confirm deleting all of `SourcesPanel.tsx` (D6).
4. Approve posting a comment on #246 when the PR opens (D12). It corrects two claims in the issue: `grep clipboard` does find something (`SourcesPanel.tsx:34-39`), and the hint is at `Composer.tsx:47`, not `:51`. It also lists the scope changes above.