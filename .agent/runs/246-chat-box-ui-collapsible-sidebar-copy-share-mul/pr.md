# PR: #246 Chat box UI (collapsible sidebar, copy, share, multi-line input)

Refs #246

**This PR is not ready to merge. None of the planned code is in it.** The test pass found that phases 1–5 never reached the disk. The `pipeline: implement-phase-N` commits don't contain the planned changes. This description covers what was planned, what was checked, and what has to happen next.

I couldn't read the docs skill at `/Users/aishahsofea/Developer/ai-standards/skills/docs/SKILL.md` because read access was denied. I wrote this from `CLAUDE.md` and the run files instead.

## Problem

Issue #246 asks for a better chat box. The workspace has these gaps today:

- The thread sidebar can't be hidden.
- Messages have no working copy control.
- Share is a disabled "Coming soon" button.
- The composer is a single-line `<input>`.
- Several disabled buttons do nothing.

`git grep -n "Coming soon" frontend/` still returns 7 hits:

- `ConversationHeader.tsx:12,13,14` (Highlights, Memo, Export)
- `Messages.tsx:301,302,303` (Save as memo, Highlight passage, Cite all)
- `SourcesPanel.tsx:52` (Filter)

## Scope

The plan in `.agent/runs/246-chat-box-ui-collapsible-sidebar-copy-share-mul/plan.md` has five phases, one commit each:

1. **Multi-line composer.** Shift+Enter inserts a newline and Enter sends. The box grows to about 6 lines, then scrolls. IME composition Enter doesn't send.
2. **Copy on every message.** A new `CopyButton` copies `message.content` exactly, which is Markdown for a response. It falls back to `execCommand` when `navigator.clipboard` is missing, and shows "Copy failed" when both paths fail.
3. **Remove dead buttons** except Export. Delete `SourcesPanel.tsx` if nothing else uses it.
4. **Collapsible sidebar.** A header toggle hides the thread list at 768px and wider. The state is stored under `locus.sidebar-collapsed.v1`. The receipt-pane clamp takes the sidebar width as a parameter, so the pane can use the freed 256px.
5. **Share as clipboard Markdown.** Each response gets a "Share" button. The header Export button becomes "Share thread" and copies the whole session. `citationMarker` moves into `citationRefs.ts` so the share formatter can use it.

## Acceptance criteria

Status comes from `test-report.md`.

| Criterion | Status |
|---|---|
| Sidebar toggle, state survives reload, mobile unchanged | Not implemented (phase 4) |
| Copy on every message | Not implemented (phase 2) |
| Share one response and the whole session | Not implemented (phase 5) |
| Shift+Enter newline, Enter sends, blank can't send, disabled while loading | Not implemented (phase 1) |
| Textarea grows to the cap, then scrolls | Not implemented (phase 1) |
| No "Coming soon" button left | Fails: 7 hits |
| New controls are keyboard reachable and have `aria-label` | Nothing to check |
| Tests for Enter/Shift+Enter and copy | No tests exist |

## Files

Planned, none written yet:

- `frontend/components/locus-workspace/`: `Composer.tsx`, `CopyButton.tsx` (new), `Messages.tsx`, `ConversationHeader.tsx`, `ThreadSidebar.tsx`, `ReceiptPaneResizer.tsx`, `citationRefs.ts`, `shareFormat.ts` (new), plus matching tests.
- `frontend/app/workspace/page.tsx` and `frontend/app/globals.css`.
- `SourcesPanel.tsx` to be deleted.

## What was and wasn't tested

Only the `git grep` above ran.

- `npm test`, `npm run lint` and `npx tsc --noEmit` did not run. Node 22 setup through nvm was denied.
- There is no green baseline. The suite was never run.
- Browser checks did not run: 1440px, 900px and 375px widths, sidebar persistence on reload, IME, and the share payloads in a Markdown viewer.
- Phase 5 stopped when the `Edit` on `citationRefs.ts` was refused.

## Out of scope

- Read-only share links. Share only copies Markdown to the clipboard.
- A share menu. There are two separate buttons instead.
- Any change to the agent graph, the API, env vars or the project structure. `README.md`, `CONTRIBUTING.md` and `CONTEXT.md` need no update, and no ADR guarantee changes.

## Sequence

1. Grant write access to `frontend/`, git command approval, and read access to `/Users/aishahsofea/Developer/ai-standards/`.
2. Set up Node 22.15.0 with nvm. Run the three checks to get a green baseline before changing anything.
3. Re-run phases 1–5 in order. Phase 3 comes before phase 5 so no stub buttons remain. Phase 5 moves `citationMarker` first.
4. Re-run the test pass.

## Needs the user before merge

Nothing below has been done. Filing or posting publishes content, so each needs approval.

1. Confirm that share copies Markdown to the clipboard. Approve filing `Read-only share links (placeholder, needs access-rule decision)` in the house structure.
2. Confirm the copy criterion: the Markdown source, not the rendered text.
3. Confirm deleting all of `SourcesPanel.tsx`. If something else uses it, only the Filter button goes.
4. Approve a comment on #246 that corrects two claims in the issue. `grep clipboard` does find something (`SourcesPanel.tsx:34-39`). The hint is at `Composer.tsx:47`, not `:51`. The comment also lists the scope changes above.

## Risks

- jsdom only simulates `isComposing`, so real IME behaviour needs a manual check or an "unverified" note.
- On touch keyboards Enter sends and a newline can't be typed. That matches today. The `⇧⏎ NEWLINE` hint is hidden below `sm`.
- A collapsed sidebar shows open for one frame on reload. The receipt pane width has the same flash.
- If `globals.css` places columns by explicit `grid-column` numbers, each collapsed variant must shift them. Check this with a receipt open.
- `navigator.clipboard` needs HTTPS. Production runs on Vercel over HTTPS.

The `langsmith`, Gmail and Google Calendar MCP servers need authorizing, through the claude.ai connector settings or `/mcp` in an interactive session. None were needed here.

🤖 Generated with [Claude Code](https://claude.com/claude-code)