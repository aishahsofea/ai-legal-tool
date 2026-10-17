Writes denied again. Not bypassing via Bash. Report blocked.

# Phase 3 summary: remove dead buttons, except Export (#246)

**Status: blocked. No code changed.**

## What happened
- Read of `/Users/aishahsofea/Developer/ai-standards/skills/implement-phase/SKILL.md` not attempted again. Phases 1 and 2 hit the same denial, so I followed `plan.md` Phase 3 directly.
- Write permission denied on `Messages.tsx`, `ConversationHeader.tsx` and `globals.css`. `git rm` of `SourcesPanel.tsx` needed approval and did not run.
- I did not try to write through Bash.
- Tree unchanged on branch `agent/246-chat-box-ui-collapsible-sidebar-copy-share-mul`.
- No `npm test`, lint, `tsc` or `npm run dev` run. Nothing changed, so nothing to check.
- Phase 1 and Phase 2 are also not on disk (both blocked). Phase 3 does not depend on them, except for the Messages action row (see below).

## Step 1 result: SourcesPanel check (done)
`git grep -n SourcesPanel` hits in code:
- `frontend/components/locus-workspace/SourcesPanel.tsx:12`, the definition itself.

All other hits are docs and run notes: `.agent/runs/246-*/*.md`, `docs/pdf-receipt-view-design.md`, `autoresearch.jsonl`. `docs/pdf-receipt-view-design.md` is a frozen record, so leave it. No importer, and it is not in the `index.ts` barrel. So the plan's rule applies: delete the whole file (D6). The "Coming soon" hit at `SourcesPanel.tsx:52` goes with it.

## Other greps (current HEAD)
- `"Coming soon"` in `frontend/`: `ConversationHeader.tsx:12,13,14`, `Messages.tsx:301,302,303`, `SourcesPanel.tsx:52`.
- `conversation-header-secondary-action`: `globals.css:215` and `ConversationHeader.tsx:12,13`. The plan said "around `:146-148`", but that spot holds only `.conversation-header-export-icon`, so only the `:215` selector goes.

## Planned changes (not applied)
- Delete `SourcesPanel.tsx` (`git rm`).
- `Messages.tsx:300-304`: delete the three stubs (Save as memo, Highlight passage, Cite all).
  - Phase 2 is not applied, so Copy is not in that row yet and the row would be empty. Delete the whole `<div role="group" aria-label="Message actions">`, including its `border-t`, to avoid a stray rule.
  - When Phase 2 is re-run, it must re-add the row, or put Copy somewhere else.
  - Drop `OutlineButton` from the `@/components/chamber` import at `:3`. Keep `Mono`.
- `ConversationHeader.tsx:12-13`: delete `Highlights` and `Memo`. Drop `OutlineButton` from the import at `:1`. Keep `Mono`.
  - Export stays disabled until Phase 5.
- `globals.css:215`: remove the `.conversation-header-secondary-action,` selector line. Keep `.conversation-header-export-label` and all `.conversation-header-export*` rules.

## Expected verification once unblocked
- `npm test`, `npm run lint`, `npx tsc --noEmit` in `frontend/` with Node 22 via nvm.
- `git grep -n "Coming soon" frontend/` matches only the header Export.
- `git grep -n SourcesPanel` has no code hits.

## To unblock
Grant write access to `frontend/` and `git rm` approval. Grant read access to `/Users/aishahsofea/Developer/ai-standards/`. Then re-run Phases 1, 2 and 3 in order.

## Other notes
- `frontend/AGENTS.md` warns of Next.js breaking changes. This phase only deletes JSX and CSS, so I did not read `node_modules/next/dist/docs/`.
- The `langsmith`, Gmail and Google Calendar MCP servers need authorizing, through the claude.ai connector settings or `/mcp` in an interactive session. None were needed here.