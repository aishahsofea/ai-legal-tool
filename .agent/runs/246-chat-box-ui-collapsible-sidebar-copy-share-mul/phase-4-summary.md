Phase 4 blocked: no code changed.

# Phase 4 summary: collapsible sidebar (#246)

**Status: blocked. No code changed.**

## What happened
- I read `plan.md`, the Phase 3 summary, `.agent/standards/AGENTS.md`, and the target files: `ReceiptPaneResizer.tsx`, its test, `page.tsx`, `ConversationHeader.tsx`, `ThreadSidebar.tsx` and `globals.css:120-270`.
- Read of `/Users/aishahsofea/Developer/ai-standards/skills/implement-phase/SKILL.md` was denied. I followed `plan.md` Phase 4 directly.
- Write permission was denied on `ReceiptPaneResizer.tsx` and `ReceiptPaneResizer.test.tsx`, so step 1 never landed.
- `git status` and shell chaining also needed approval.
- I did not try to write through Bash.
- No `npm test`, lint, `tsc` or `npm run dev` ran. Nothing changed, so there was nothing to check.
- Phases 1, 2 and 3 are also not on disk (all blocked on the same writes). Phase 4 does not depend on them, with one exception: `ConversationHeader.tsx` still has the Highlights, Memo and Export buttons from before Phase 3.

## Planned changes (not applied)
Checked against current source. The plan holds, with one correction to the CSS step noted below.

1. **Clamp parameter (D9), own commit.**
   - `ReceiptPaneResizer.tsx:15-28`: add `sidebarWidth = WORKSPACE_SIDEBAR_WIDTH` as the last parameter of `maxReceiptPaneWidth`, `clampReceiptPaneWidth` and `defaultReceiptPaneWidth`. Use it in place of the constant and pass it through the inner calls.
   - Add a `sidebarWidth?: number` prop to `ReceiptPaneResizer`. Pass it to `maxReceiptPaneWidth` (`:43`), `clampReceiptPaneWidth` (`:46`) and `defaultReceiptPaneWidth` (`:95`).
   - Test in `ReceiptPaneResizer.test.tsx`: `maxReceiptPaneWidth(1200, 0) - maxReceiptPaneWidth(1200)` equals 256. 1200px is chosen because the 800 cap doesn't hide the difference there (1200 − 256 − 8 − 420 = 516, versus 772 with no sidebar). Also assert `clampReceiptPaneWidth(900, 1200, 0)` equals `maxReceiptPaneWidth(1200, 0)`. The existing 1280 and 1920 expectations stay unchanged because the default is identical.
2. **State (D8), `page.tsx`.**
   - Add `SIDEBAR_COLLAPSED_STORAGE_KEY = "locus.sidebar-collapsed.v1"` after `:45`.
   - Add `sidebarCollapsed` state. Hydrate it in a mount effect inside try/catch, setting `true` only when the stored value is `"1"`. Copy the `eslint-disable-next-line react-hooks/set-state-in-effect` comment from `:141`.
   - Add `toggleSidebar`. It flips the state and writes `"1"` or `"0"` inside try/catch, and a failure is silent.
   - Compute `sidebarWidth = sidebarCollapsed ? 0 : WORKSPACE_SIDEBAR_WIDTH`. Pass it to both `clampReceiptPaneWidth` calls (`:101`, `:142`) and to `<ReceiptPaneResizer>` (`:231`).
   - The storage-hydration clamp at `:142` uses the expanded width. That is safe because the state default is expanded, and the render-time clamp at `:101` re-clamps once the collapsed state hydrates.
3. **Grid class.** `page.tsx:166`: add `sidebar-collapsed` to the `chamber-grid-app` className.
4. **CSS, `globals.css`.** The plan's "move `grid-column` left" is concrete here. At ≥1200px with a receipt open, main is column 2 (`:164-167`), the resizer is column 3 (`:169-171`) and the receipt layer is column 4 (`:193-199`). Collapsed they become 1, 2 and 3.
   - Inside `@media (min-width: 768px)`: `.sidebar-collapsed.chamber-grid-app { grid-template-columns: minmax(0, 1fr); }` and `.sidebar-collapsed .thread-sidebar { display: none; }`.
   - Inside `@media (min-width: 1200px)`: `.sidebar-collapsed.receipt-open.chamber-grid-app { grid-template-columns: minmax(420px, 1fr) 8px var(--receipt-pane-width, 640px); }`, plus the three overrides moving `.workspace-main`, `.workspace-receipt-resizer` and `.citation-receipt-layer` one column left.
   - These rules go after the existing ones so source order wins at equal specificity. No `max-md` rule is touched.
5. **Sidebar id, `ThreadSidebar.tsx:23`.** Add `id="thread-sidebar"` and the `thread-sidebar` class to `<aside>`.
6. **Toggle, `ConversationHeader.tsx`.** Add props `sidebarCollapsed` and `onToggleSidebar`. Add a native `<button type="button">` before `THREAD /`, inside the left `div` and outside `.conversation-header-actions`, with `aria-expanded={!sidebarCollapsed}`, `aria-controls="thread-sidebar"`, `aria-label` set to `Hide thread list` or `Show thread list`, and `max-md:hidden`. Wire it from `page.tsx:180`.
   - The toggle must not sit inside `.conversation-header-actions`. The `@container workspace (width < 420px)` rule at `globals.css:231-235` hides that group.
7. **New `ConversationHeader.test.tsx`.** Clicking the toggle calls `onToggleSidebar`. Re-render with `sidebarCollapsed` flipped and assert `aria-expanded` and `aria-label` change.

## Verification still owed
- `npm test`, `npm run lint`, `npx tsc --noEmit` in `frontend/` with Node 22 via nvm.
- Manual check from the plan at ≥1200px, at 900px and below 768px: reload persistence, receipt resizer using the freed 256px, and the toggle hidden on mobile.

## To unblock
Grant write access to `frontend/`, approval for git commands, and read access to `/Users/aishahsofea/Developer/ai-standards/`. Then re-run Phases 1 to 4 in order.

## Other notes
- `frontend/AGENTS.md` warns of Next.js breaking changes. This phase touches no Next.js APIs, so I did not read `node_modules/next/dist/docs/`.
- The `langsmith`, Gmail and Google Calendar MCP servers need authorizing, through the claude.ai connector settings or `/mcp` in an interactive session. None were needed here.