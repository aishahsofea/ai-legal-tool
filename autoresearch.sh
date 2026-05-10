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
add(!/InlineSourceSummary/.test(text.messages), 18, 'no_compact_source_summary_before_answer');
add(!/source-ref-/.test(text.messages), 12, 'sources_do_not_have_stable_reference_anchors');
add(!/aria-label="Sources cited before this answer"/.test(text.messages), 8, 'pre_answer_sources_not_accessible');
add(!/href={`#source-ref-/.test(text.messages), 8, 'summary_markers_do_not_link_to_source_details');
add(/<CitationCard citation=/.test(text.messages), 14, 'source_detail_rows_duplicate_citation_card_content');
add(/Open full act ↗[\s\S]*Open full act ↗/.test(text.messages), 8, 'source_actions_repeated_in_multiple_nested_elements');
add(!/aria-label={`Open source/.test(text.messages), 6, 'source_open_link_lacks_specific_accessible_label');
add(!/Back to source map/.test(text.messages), 6, 'source_detail_rows_do_not_link_back_to_summary');
add(!/SOURCE_MAP_VISIBLE_LIMIT/.test(text.messages), 14, 'source_map_has_no_visible_limit_constant');
add(!/visibleSources/.test(text.messages) || !/remainingSources/.test(text.messages), 18, 'source_map_does_not_split_visible_and_overflow_sources');
add(!/<details/.test(text.messages), 12, 'overflow_sources_not_collapsible');
add(!/remainingSources\.length/.test(text.messages), 8, 'overflow_count_not_shown');
// Multi-answer thread correctness: anchors must be scoped per assistant message, not static document ids.
add(/id="source-map"/.test(text.messages), 22, 'static_source_map_id_collides_across_answers');
add(/href="#source-map"/.test(text.messages), 18, 'static_back_to_source_map_link_collides_across_answers');
add(!/messageId/.test(text.messages), 18, 'source_components_do_not_accept_message_id_scope');
add(!/sourceMapId/.test(text.messages), 12, 'source_map_id_not_derived_from_message_scope');
add(!/sourceRefId\([^)]*messageId/.test(text.messages), 16, 'source_ref_ids_not_scoped_by_message');
const sourcePanelRefs = (all.match(/SourcesPanel/g) || []).length;
const inlineCitationRefs = (text.messages.match(/citation/g) || []).length;
const sourceAnchorRefs = (text.messages.match(/source-ref-/g) || []).length;
const citationCardInMessages = (text.messages.match(/CitationCard/g) || []).length;
const collapsibleRefs = (text.messages.match(/<details/g) || []).length;
const staticSourceMapRefs = (text.messages.match(/source-map/g) || []).length;
console.log(`METRIC layout_debt=${debt}`);
console.log(`METRIC source_panel_refs=${sourcePanelRefs}`);
console.log(`METRIC inline_citation_refs=${inlineCitationRefs}`);
console.log(`METRIC source_anchor_refs=${sourceAnchorRefs}`);
console.log(`METRIC citation_card_in_messages=${citationCardInMessages}`);
console.log(`METRIC collapsible_source_refs=${collapsibleRefs}`);
console.log(`METRIC static_source_map_refs=${staticSourceMapRefs}`);
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
