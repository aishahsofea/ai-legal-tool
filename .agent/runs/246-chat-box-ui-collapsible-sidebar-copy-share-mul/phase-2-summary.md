# Phase 2 summary: copy on every message (#246)

**Status: blocked. No code was changed.**

## What happened
- Write permission was denied on every file I tried, so nothing is on disk. That covers the new `CopyButton.tsx` and `CopyButton.test.tsx`, plus the edits to `Messages.tsx` and `Messages.test.tsx`. This is the same denial as in Phase 1.
- Read permission on `/Users/aishahsofea/Developer/ai-standards/skills/implement-phase/SKILL.md` was also denied. I followed `plan.md` Phase 2 directly.
- I did not try to write the files through Bash. The working tree is unchanged on branch `agent/246-chat-box-ui-collapsible-sidebar-copy-share-mul`.
- I ran no tests, lint, `tsc` or `npm run dev`. Nothing changed, so there was nothing to check.
- `git show --stat HEAD` was blocked by the Bash permission check, so I couldn't confirm what the `pipeline: implement-phase-1` commit contains. The Phase 1 summary says it changed no code, and `git status` was clean at session start.
- Phase 2 does not depend on Phase 1's Composer changes.

## Planned changes (not applied)
**New `CopyButton.tsx`**
- `copyText(text): Promise<boolean>`:
  - It tries `navigator.clipboard.writeText` inside try/catch.
  - On failure it falls back to a hidden, off-screen, readonly `<textarea>` and `document.execCommand("copy")`.
  - It removes the element in `finally`. A throw returns `false`.
  - Unlike `SourcesPanel.tsx:34-39`, no promise is left without a catch.
- `CopyButton({ getText, label, idleText = "Copy" })`:
  - It uses `OutlineButton` with `type="button"` and `aria-label={label}`.
  - State is `idle | copied | failed`, shown as "Copied" or "Copy failed" for 1600 ms inside an `aria-live="polite"` span.
  - The timer is cleared on unmount.
  - I dropped the plan's optional `children` prop. Nothing needs it, and Phase 5's header button can decide its own variant.

**`Messages.tsx`**
- Import `CopyButton`.
- `AssistantMessage` action row (near line 300): add `{message.content && <CopyButton label="Copy response" getText={() => message.content} />}` before the three stubs. Phase 3 removes the stubs.
- `UserMessage` (near line 313): make the `YOU · …` row `flex items-center gap-2`, with the label in a `<span>` and `<CopyButton label="Copy message" … />` after it. It renders only when `content` is non-empty.

**`CopyButton.test.tsx`**
- With `navigator.clipboard.writeText` mocked, it is called with exactly the text and "Copied" appears.
- With `navigator.clipboard` undefined and `document.execCommand` stubbed, `execCommand` is called with `"copy"`.
- When both paths fail, "Copy failed" appears.

**`Messages.test.tsx`**
- "Copy response" puts the verbatim Markdown `message.content` on the clipboard, with no sources text.
- "Copy message" on `UserMessage` copies the user text.
- No copy button renders for `content: ""`. To test this I'd give `renderMessage` an optional `content` parameter.
- I did not touch `index.ts`, because nothing outside the folder uses the new exports.

## To unblock
Grant write access to `frontend/components/locus-workspace/` and read access to `/Users/aishahsofea/Developer/ai-standards/`. Then re-run Phase 1 and Phase 2. After that, run `npm test`, `npm run lint` and `npx tsc --noEmit` in `frontend/` with Node 22 set up through nvm. The plan wants a green baseline before Phase 1.

## Other notes
- `frontend/AGENTS.md` says this repo's Next.js has breaking changes. Phase 2 uses only plain React and a client-component directive, so I did not read `node_modules/next/dist/docs/`.
- The `langsmith`, Gmail and Google Calendar MCP servers need authorizing, through the claude.ai connector settings or `/mcp` in an interactive session. None of them were needed for this phase.