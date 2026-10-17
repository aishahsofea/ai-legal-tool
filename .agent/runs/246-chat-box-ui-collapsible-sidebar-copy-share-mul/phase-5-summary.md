Phase 5 blocked: write denied on `citationRefs.ts`, the first file in step 5.1. Stopping, since retrying or writing through Bash would sidestep the denial.

# Phase 5 summary: share as clipboard Markdown (#246)

**Status: blocked. No code changed.**

## What happened
- I read `plan.md`, the Phase 4 summary, `.agent/standards/AGENTS.md`, `Messages.tsx`, `ConversationHeader.tsx` and `citationRefs.ts`.
- Read of `/Users/aishahsofea/Developer/ai-standards/skills/implement-phase/SKILL.md` was denied. I followed `plan.md` Phase 5 directly.
- The `Edit` on `citationRefs.ts` (step 5.1) was denied for write permission. I did not try Bash writes.
- `git log` also needed approval, so I could not inspect the history. The `pipeline: implement-phase-N` commits do not reflect the files on disk.
- No `npm test`, lint, `tsc` or `npm run dev` ran. Nothing changed, so there was nothing to check.

## State of the tree
Phases 1 to 4 are not on disk:
- `CopyButton.tsx` does not exist. Phase 2 never landed.
- `Messages.tsx` still has the three disabled stubs: Save as memo, Highlight passage and Cite all.
- `ConversationHeader.tsx` still has Highlights, Memo and a disabled Export. It has no sidebar toggle and takes only `title`.

Phase 5 steps 3 and 4 depend on `CopyButton` and `copyText` from Phase 2. They cannot be built until that lands.

## Planned changes (not applied)
Checked against current source. The plan holds.

1. **Move `citationMarker`.** Cut `Messages.tsx:16-20` and its ADR 0018 comment. Paste both into `citationRefs.ts` as an export, and import it back into `Messages.tsx:6`. The four call sites (`:28`, `:69`, `:85`, `:129`) stay unchanged.
2. **New `shareFormat.ts`.**
   - `formatResponseForShare(message)` returns `message.content`.
     - With citations it appends a blank line, `Sources`, then one line per citation: `[n] Act {act_number} {formatSourceTitle(act_title)}, § {citationMarker(c)}: {pdf_url}`.
     - The `: {pdf_url}` part is dropped when `pdf_url` is missing.
     - With no citations there is no `Sources` heading.
   - `formatSessionForShare(title, messages)` returns `# {title}` plus one block per turn: `**You:**` for user turns and `**Locus:**` for responses. It skips responses with empty `content`.
3. **Response action row, `Messages.tsx:300-304`.** Add `<CopyButton label="Share response" idleText="Share" getText={() => formatResponseForShare(message)} />`. Hide it when `content` is empty.
4. **Header.**
   - Replace the disabled Export with an enabled `Share thread` button. It keeps the `conversation-header-export*` classes, the `↗` icon and `PrimaryButton size="compact"`.
   - It calls `copyText(formatSessionForShare(title, messages))` and shows Copied or Copy failed for 1600ms. It is disabled when `messages.length === 0`.
   - `ConversationHeader` gains a `messages: Message[]` prop, passed from `page.tsx`.
5. **Tests.**
   - New `shareFormat.test.ts`: the exact citation line, the Schedule citation (`§ sched.2/art.1`), no `Sources` text without citations, a two-turn session, and an empty streaming tail skipped.
   - `Messages.test.tsx`: "Share response" writes `formatResponseForShare(message)` to the clipboard.
   - `ConversationHeader.test.tsx`: Share thread is disabled with no messages. With messages, a click writes `formatSessionForShare(title, messages)`.

## Verification still owed
- `npm test`, `npm run lint`, `npx tsc --noEmit` in `frontend/` with Node 22 via nvm.
- `git grep -n "Coming soon" frontend/` should return nothing. It cannot, until Phase 3 and this phase both land.
- Paste both share payloads into a Markdown viewer in `npm run dev`.
- Final pass through the acceptance table in the plan.

## To unblock
Grant write access to `frontend/`, approval for git commands, and read access to `/Users/aishahsofea/Developer/ai-standards/`. Then re-run Phases 1 to 5 in order.

## Other notes
- The plan's four "Needs the user" items are still open: share as clipboard Markdown, the copy criterion, deleting `SourcesPanel.tsx`, and the #246 comment. Nothing was filed or posted.
- This phase touches no Next.js APIs, so I did not read `node_modules/next/dist/docs/`.
- The `langsmith`, Gmail and Google Calendar MCP servers need authorizing, through the claude.ai connector settings or `/mcp` in an interactive session. None were needed here.