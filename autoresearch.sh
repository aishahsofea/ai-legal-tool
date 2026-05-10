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
// Guardrails from user feedback and prior wins.
add(/<SourcesPanel\b/.test(text.page), 35, 'right_sources_panel_rendered');
add(/SourcesPanel/.test(text.index), 8, 'sources_panel_exported_as_workspace_region');
add(/grid-template-columns:\s*220px\s+minmax\(0,\s*1fr\)\s+300px/.test(text.css), 22, 'desktop_grid_reserves_right_column');
add(/\.chamber-max-content \{ max-width: (72ch|66ch); \}/.test(text.css), 30, 'content_re_capped_leaving_right_empty_space');
add(/mx-auto flex w-full chamber-max-content/.test(text.page), 12, 'message_column_re_centered_as_narrow_report_column');
add(!/chamber-full-content/.test(text.css), 8, 'no_full_width_content_utility');
add(!/InlineSourceSummary/.test(text.messages), 18, 'no_compact_source_summary_before_answer');
add(/id="source-map"/.test(text.messages), 22, 'static_source_map_id_collides_across_answers');
add(!/sourceRefId\([^)]*messageId/.test(text.messages), 16, 'source_ref_ids_not_scoped_by_message');
// Wide workspace readability: use the whole width, but give long legal prose a wide-screen reading treatment.
add(!/chamber-reading-flow/.test(text.css), 16, 'no_reading_flow_utility_for_full_width_prose');
add(!/text-wrap:\s*pretty/.test(text.css), 8, 'prose_lacks_pretty_text_wrapping');
add(!/overflow-wrap:\s*anywhere/.test(text.css), 8, 'prose_lacks_defensive_long_token_wrapping');
add(!/hyphens:\s*auto/.test(text.css), 6, 'prose_lacks_hyphenation_for_long_legal_terms');
add(!/xl:columns-2/.test(text.messages), 18, 'very_wide_answer_text_does_not_use_available_width_as_columns');
add(!/xl:gap-/.test(text.messages), 6, 'wide_answer_columns_lack_gap');
add(!/chamber-reading-flow/.test(text.messages), 14, 'assistant_markdown_does_not_apply_reading_flow');
add(!/break-inside-avoid/.test(text.css) && !/break-inside-avoid/.test(text.messages), 8, 'wide_columns_do_not_avoid_breaking_key_blocks');
// Keep small-width chrome improvements.
add(!/aria-label="Message actions"/.test(text.messages), 6, 'message_action_group_lacks_accessible_label');
add(/lg:px-20/.test(text.composer), 8, 'composer_padding_jumps_to_large_value_on_laptops');
add(!/max-sm:grid-cols/.test(text.composer), 10, 'composer_grid_lacks_small_screen_column_adjustment');
const sourcePanelRefs = (all.match(/SourcesPanel/g) || []).length;
const inlineCitationRefs = (text.messages.match(/citation/g) || []).length;
const sourceAnchorRefs = (text.messages.match(/source-ref-/g) || []).length;
const fullWidthRefs = (all.match(/chamber-full-(content|input)|max-width: none/g) || []).length;
const readingFlowRefs = (all.match(/chamber-reading-flow|columns-2|text-wrap: pretty/g) || []).length;
console.log(`METRIC layout_debt=${debt}`);
console.log(`METRIC source_panel_refs=${sourcePanelRefs}`);
console.log(`METRIC inline_citation_refs=${inlineCitationRefs}`);
console.log(`METRIC source_anchor_refs=${sourceAnchorRefs}`);
console.log(`METRIC full_width_refs=${fullWidthRefs}`);
console.log(`METRIC reading_flow_refs=${readingFlowRefs}`);
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
