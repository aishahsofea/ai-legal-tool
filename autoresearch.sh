#!/usr/bin/env bash
set -euo pipefail

node <<'NODE'
const fs = require('fs');
const files = {
  page: 'frontend/app/page.tsx',
  css: 'frontend/app/globals.css',
  messages: 'frontend/components/locus-workspace/Messages.tsx',
  index: 'frontend/components/locus-workspace/index.ts',
};
const text = Object.fromEntries(Object.entries(files).map(([k,p]) => [k, fs.existsSync(p) ? fs.readFileSync(p,'utf8') : '']));
const all = Object.values(text).join('\n');
let debt = 0;
const notes = [];
function add(cond, points, note) { if (cond) { debt += points; notes.push(note); } }
add(/<SourcesPanel\b/.test(text.page), 35, 'right_sources_panel_rendered');
add(/SourcesPanel/.test(text.index), 8, 'sources_panel_exported_as_workspace_region');
add(/grid-template-columns:\s*220px\s+minmax\(0,\s*1fr\)\s+300px/.test(text.css), 22, 'desktop_grid_reserves_right_column');
add(/lg:px-20/.test(text.page), 8, 'large_fixed_padding_can_crowd_medium_widths');
add(!/message\.citations/.test(text.messages), 20, 'assistant_message_does_not_render_own_sources_inline');
add(!/(Sources used|Sources|References|Citations)/i.test(text.messages), 12, 'no_inline_sources_heading_in_message');
add(!/(pdf_url|Open full act|Copy citation)/.test(text.messages), 12, 'inline_sources_lack_source_actions');
add(/activeSourceIndex|setActiveSourceIndex|activeSource/.test(text.page), 8, 'page_tracks_sidebar_source_selection_state');
add(!/chamber-grid-app \{ grid-template-columns: 220px minmax\(0, 1fr\); \}/.test(text.css), 6, 'desktop_grid_not_simplified_to_nav_and_content');
const sourcePanelRefs = (all.match(/SourcesPanel/g) || []).length;
const inlineCitationRefs = (text.messages.match(/citation/g) || []).length;
console.log(`METRIC layout_debt=${debt}`);
console.log(`METRIC source_panel_refs=${sourcePanelRefs}`);
console.log(`METRIC inline_citation_refs=${inlineCitationRefs}`);
console.log(`ASI notes=${notes.join(',')}`);
NODE

set +e
(cd frontend && npm run lint >/tmp/autoresearch-lint.out 2>&1)
lint_exit=$?
(cd frontend && npm run build >/tmp/autoresearch-build.out 2>&1)
build_exit=$?
set -e
printf 'METRIC lint_exit=%s\n' "$lint_exit"
printf 'METRIC build_exit=%s\n' "$build_exit"
if [[ "$lint_exit" != "0" ]]; then tail -20 /tmp/autoresearch-lint.out >&2; fi
if [[ "$build_exit" != "0" ]]; then tail -30 /tmp/autoresearch-build.out >&2; fi
exit 0
