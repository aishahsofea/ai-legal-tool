#!/usr/bin/env bash
set -euo pipefail

node <<'NODE'
const fs = require('fs');
const files = {
  page: 'frontend/app/page.tsx',
  css: 'frontend/app/globals.css',
  sidebar: 'frontend/components/locus-workspace/ThreadSidebar.tsx',
  messages: 'frontend/components/locus-workspace/Messages.tsx',
  composer: 'frontend/components/locus-workspace/Composer.tsx',
  index: 'frontend/components/locus-workspace/index.ts',
};
const text = Object.fromEntries(Object.entries(files).map(([k,p]) => [k, fs.existsSync(p) ? fs.readFileSync(p,'utf8') : '']));
const all = Object.values(text).join('\n');
let debt = 0;
const notes = [];
function add(cond, points, note) { if (cond) { debt += points; notes.push(note); } }
// Guardrails retained.
add(/<SourcesPanel\b/.test(text.page), 35, 'right_sources_panel_rendered');
add(/SourcesPanel/.test(text.index), 8, 'sources_panel_exported_as_workspace_region');
add(/grid-template-columns:\s*220px\s+minmax\(0,\s*1fr\)\s+300px/.test(text.css), 22, 'desktop_grid_reserves_right_column');
add(/\.chamber-max-content \{ max-width: (72ch|66ch); \}/.test(text.css), 30, 'content_re_capped_leaving_right_empty_space');
add(!/InlineSourceSummary/.test(text.messages), 18, 'no_compact_source_summary_before_answer');
add(/id="source-map"/.test(text.messages), 22, 'static_source_map_id_collides_across_answers');
// User feedback: thread rail should collapse at a breakpoint.
add(!/chamber-grid-app-collapsed/.test(text.css), 20, 'no_collapsed_sidebar_grid_breakpoint');
add(!/@media \(min-width: 768px\)/.test(text.css), 10, 'no_medium_breakpoint_for_thread_rail');
add(!/@media \(min-width: 1280px\)/.test(text.css), 10, 'no_large_breakpoint_for_expanded_thread_rail');
add(!/grid-template-columns:\s*56px\s+minmax\(0,\s*1fr\)/.test(text.css), 18, 'no_icon_rail_collapsed_width');
add(!/xl:/.test(text.sidebar), 12, 'sidebar_lacks_large_breakpoint_expanded_labels');
add(!/md:/.test(text.sidebar), 8, 'sidebar_lacks_medium_breakpoint_behavior');
add(!/aria-label="Threads"/.test(text.sidebar), 6, 'sidebar_lacks_navigation_label');
add(!/title="New thread"/.test(text.sidebar), 6, 'collapsed_new_thread_lacks_tooltip');
add(!/hidden xl:block|hidden xl:flex/.test(text.sidebar), 14, 'sidebar_text_not_hidden_until_expanded_breakpoint');
add(!/w-14/.test(text.sidebar), 10, 'sidebar_has_no_collapsed_width_class');
add(!/overflow-hidden/.test(text.sidebar), 6, 'collapsed_sidebar_may_leak_text');
const sourcePanelRefs = (all.match(/SourcesPanel/g) || []).length;
const sidebarBreakpointRefs = (text.sidebar.match(/md:|xl:|w-14|hidden xl:/g) || []).length + (text.css.match(/768px|1280px|56px/g) || []).length;
const fullWidthRefs = (all.match(/chamber-full-(content|input)|max-width: none/g) || []).length;
console.log(`METRIC layout_debt=${debt}`);
console.log(`METRIC source_panel_refs=${sourcePanelRefs}`);
console.log(`METRIC sidebar_breakpoint_refs=${sidebarBreakpointRefs}`);
console.log(`METRIC full_width_refs=${fullWidthRefs}`);
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
