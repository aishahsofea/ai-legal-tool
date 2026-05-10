#!/usr/bin/env bash
set -euo pipefail

node <<'NODE'
const fs = require('fs');
const files = {
  page: 'frontend/app/page.tsx',
  css: 'frontend/app/globals.css',
  messages: 'frontend/components/locus-workspace/Messages.tsx',
  composer: 'frontend/components/locus-workspace/Composer.tsx',
  header: 'frontend/components/locus-workspace/ConversationHeader.tsx',
  index: 'frontend/components/locus-workspace/index.ts',
};
const text = Object.fromEntries(Object.entries(files).map(([k,p]) => [k, fs.existsSync(p) ? fs.readFileSync(p,'utf8') : '']));
const all = Object.values(text).join('\n');
let debt = 0;
const notes = [];
function add(cond, points, note) { if (cond) { debt += points; notes.push(note); } }
// Core layout/source guardrails retained from prior experiments.
add(/<SourcesPanel\b/.test(text.page), 35, 'right_sources_panel_rendered');
add(/SourcesPanel/.test(text.index), 8, 'sources_panel_exported_as_workspace_region');
add(/grid-template-columns:\s*220px\s+minmax\(0,\s*1fr\)\s+300px/.test(text.css), 22, 'desktop_grid_reserves_right_column');
add(/lg:px-20/.test(text.page), 8, 'large_fixed_padding_can_crowd_medium_widths');
add(!/message\.citations/.test(text.messages), 20, 'assistant_message_does_not_render_own_sources_inline');
add(!/InlineSourceSummary/.test(text.messages), 18, 'no_compact_source_summary_before_answer');
add(!/SOURCE_MAP_VISIBLE_LIMIT/.test(text.messages), 14, 'source_map_has_no_visible_limit_constant');
add(/id="source-map"/.test(text.messages), 22, 'static_source_map_id_collides_across_answers');
add(/href="#source-map"/.test(text.messages), 18, 'static_back_to_source_map_link_collides_across_answers');
add(!/sourceRefId\([^)]*messageId/.test(text.messages), 16, 'source_ref_ids_not_scoped_by_message');
// Small-width action/chrome responsiveness.
add(/<OutlineButton disabled title="Coming soon">Save as memo<\/OutlineButton>/.test(text.messages), 10, 'message_actions_use_full_labels_on_small_widths');
add(!/aria-label="Save as memo"/.test(text.messages), 8, 'message_actions_lack_accessible_compact_labels');
add(!/hidden sm:inline/.test(text.messages), 10, 'message_actions_do_not_collapse_labels_until_small_breakpoint');
add(!/aria-label="Message actions"/.test(text.messages), 6, 'message_action_group_lacks_accessible_label');
add(/<OutlineButton disabled title="Coming soon">Highlights<\/OutlineButton>/.test(text.header), 8, 'header_actions_use_full_labels_on_small_widths');
add(!/hidden sm:flex/.test(text.header), 10, 'header_action_group_not_hidden_or_collapsed_on_small_widths');
add(!/sm:inline/.test(text.header), 6, 'header_actions_lack_small_breakpoint_label_handling');
add(/lg:px-20/.test(text.composer), 8, 'composer_padding_jumps_to_large_value_on_laptops');
add(!/md:px-8/.test(text.composer), 4, 'composer_lacks_medium_width_padding_step');
add(!/max-sm:grid-cols/.test(text.composer), 10, 'composer_grid_lacks_small_screen_column_adjustment');
const sourcePanelRefs = (all.match(/SourcesPanel/g) || []).length;
const inlineCitationRefs = (text.messages.match(/citation/g) || []).length;
const sourceAnchorRefs = (text.messages.match(/source-ref-/g) || []).length;
const compactActionRefs = (all.match(/hidden sm:inline|hidden sm:flex|max-sm:grid-cols/g) || []).length;
console.log(`METRIC layout_debt=${debt}`);
console.log(`METRIC source_panel_refs=${sourcePanelRefs}`);
console.log(`METRIC inline_citation_refs=${inlineCitationRefs}`);
console.log(`METRIC source_anchor_refs=${sourceAnchorRefs}`);
console.log(`METRIC compact_action_refs=${compactActionRefs}`);
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
