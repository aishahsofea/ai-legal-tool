# Phase 1 summary: multi-line composer (#246)

**Status: blocked. No code was changed.**

## What happened
- Permission to read `/Users/aishahsofea/Developer/ai-standards/skills/implement-phase/SKILL.md` was denied. I followed `plan.md` Phase 1 directly.
- I read `plan.md`, `Composer.tsx`, `Composer.test.tsx` and `.agent/standards/AGENTS.md`.
- All seven `Edit` calls on `frontend/components/locus-workspace/Composer.tsx` were denied for lack of write permission.
- I did not try to get around the denial by writing through Bash. The working tree is still clean on branch `agent/246-chat-box-ui-collapsible-sidebar-copy-share-mul`.
- I did not run the baseline `npm test`, `npm run lint` or `npx tsc --noEmit`. The plan says to run them with Node 22 set up through nvm before Phase 1. Nothing changed, so there is nothing to check.
- I did not run any tests or `npm run dev`.

## Planned changes (not applied)
These follow `plan.md` Phase 1.

**`Composer.tsx`**
- Replace the `<input>` with `<textarea rows={1}>`. Classes: `min-h-12 max-h-42 resize-none overflow-y-auto px-3 py-3 leading-6`. `max-h-42` is 168px. With 24px of padding that leaves six 24px lines. The plan's `max-h-36` would leave only five.
- Add a `useRef` and a `useLayoutEffect` keyed on `input`. It sets `style.height` to `auto`, then to `scrollHeight`. Keying on the value means the `?q=` prefill also resizes the box.
- Add `onKeyDown`, with these rules:
  - Do nothing if the key is not Enter, or Shift is held.
  - Do nothing if `isComposing` is true or `keyCode` is 229 (an IME candidate confirmation).
  - Otherwise call `preventDefault()`. If `input.trim()` is non-empty and `!isLoading`, call `form.requestSubmit()`.
- Give the `ASK ›` span, the Upload button and both `PrimaryButton`s `h-12 self-end` in place of `h-full`, so they stay at the bottom as the box grows.
- Wrap `⇧⏎ NEWLINE` in `max-sm:hidden`.
- Add a one-line `why` comment on the `useLayoutEffect` (the prefill) and on the 229 check (the IME).

**`Composer.test.tsx`** (using `userEvent` in a controlled harness)
- Shift+Enter gives the value `"a\nb"` and `onSubmit` is not called.
- Enter with text calls `onSubmit` once.
- Enter on `"   "` does not call `onSubmit`.
- Enter with `isComposing: true` does not call `onSubmit`.
- The textarea is disabled while `isLoading`.

## To unblock
Grant write access to `frontend/` and read access to `/Users/aishahsofea/Developer/ai-standards/`. Then re-run Phase 1.

## Other notes
- `frontend/AGENTS.md` says the repo's Next.js has breaking changes. Phase 1 uses only plain React, so I did not read `node_modules/next/dist/docs/`.
- The `langsmith`, Gmail and Google Calendar MCP servers need authorizing, through the claude.ai connector settings or `/mcp` in an interactive session. None of them were needed for this phase.