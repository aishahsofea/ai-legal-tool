#!/usr/bin/env bash
set -euo pipefail

node <<'NODE'
const fs = require('fs');
const path = require('path');

const roots = ['frontend/app', 'frontend/components'];
const files = [];
function collect(root) {
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const target = path.join(root, entry.name);
    if (entry.isDirectory()) collect(target);
    else if (/\.(css|tsx|ts)$/.test(entry.name)) files.push(target);
  }
}
for (const root of roots) collect(root);

const texts = Object.fromEntries(files.map((file) => [file, fs.readFileSync(file, 'utf8')]));
const all = Object.values(texts).join('\n');
const css = texts['frontend/app/globals.css'] ?? '';
const landing = texts['frontend/app/page.tsx'] ?? '';
const workspace = texts['frontend/app/workspace/page.tsx'] ?? '';
const messages = texts['frontend/components/locus-workspace/Messages.tsx'] ?? '';
const evalDashboard = texts['frontend/app/evals/EvalDashboard.tsx'] ?? '';
const primaryButton = texts['frontend/components/PrimaryButton.tsx'] ?? '';
const composer = texts['frontend/components/locus-workspace/Composer.tsx'] ?? '';
const requestAccessMarkup = landing.match(/<Link[\s\S]*?Request access[\s\S]*?<\/Link>/)?.[0] ?? '';

const oddPixelFindings = [];
for (const [file, source] of Object.entries(texts)) {
  source.split('\n').forEach((line, index) => {
    for (const match of line.matchAll(/(-?\d+(?:\.\d+)?)px\b/g)) {
      const value = Number(match[1]);
      const absolute = Math.abs(value);
      const isInteger = Number.isInteger(value);
      const isEven = isInteger && absolute % 2 === 0;
      const isHairline = absolute === 1 && /(border|rule|ring|stroke|shadow|outline|decoration)/i.test(line);
      if (!isEven && !isHairline) oddPixelFindings.push(`${file}:${index + 1}:${match[0]}`);
    }
  });
}

const legacyBronzeRefs = (all.match(/bronze/gi) || []).length;
let visualDebt = 0;
let humanBubbleDebt = 0;
let scaleDebt = 0;
let contrastDebt = 0;
const notes = [];
function add(condition, points, note) {
  if (!condition) return;
  visualDebt += points;
  notes.push(note);
}
function bubble(condition, points, note) {
  if (!condition) return;
  humanBubbleDebt += points;
  visualDebt += points;
  notes.push(note);
}
function scale(condition, points, note) {
  if (!condition) return;
  scaleDebt += points;
  visualDebt += points;
  notes.push(note);
}
function contrast(condition, points, note) {
  if (!condition) return;
  contrastDebt += points;
  visualDebt += points;
  notes.push(note);
}

function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map((value) => parseInt(value, 16) / 255);
  const linear = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}
function contrastRatio(first, second) {
  const light = Math.max(luminance(first), luminance(second));
  const dark = Math.min(luminance(first), luminance(second));
  return (light + 0.05) / (dark + 0.05);
}
const tokens = Object.fromEntries([...css.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((match) => [match[1], match[2]]));
const contrastPairs = [
  ['text', 'canvas'],
  ['text', 'surface'],
  ['text-muted', 'canvas'],
  ['text-muted', 'surface'],
  ['text-subtle', 'canvas'],
  ['text-subtle', 'surface'],
  ['accent', 'canvas'],
  ['accent', 'surface'],
  ['surface', 'accent'],
  ['danger', 'danger-soft'],
  ['success', 'success-soft'],
];
const contrastFailures = contrastPairs.filter(([foreground, background]) => {
  return !tokens[foreground] || !tokens[background] || contrastRatio(tokens[foreground], tokens[background]) < 4.5;
});

add(!/--canvas:\s*#f6f1e7/i.test(css), 20, 'cream_canvas_token_missing');
add(!/--surface:\s*#fffdf8/i.test(css), 12, 'ivory_surface_token_missing');
add(!/--accent:\s*#6e2f3a/i.test(css), 12, 'oxblood_accent_token_missing');
add(/#0c0e11|#14171c|#c2a878|#8d7a55/i.test(all), 30, 'legacy_dark_or_gold_palette_present');
add(legacyBronzeRefs > 0, Math.min(30, legacyBronzeRefs), 'legacy_bronze_naming_present');
add(oddPixelFindings.length > 0, Math.min(40, oddPixelFindings.length * 2), 'odd_explicit_pixel_values_present');
add(!/chamber-full-content[\s\S]*max-width:\s*760px/.test(css), 10, 'calm_reading_width_missing');
add(/xl:columns-2/.test(messages), 12, 'assistant_answer_uses_newspaper_columns');
add(!/bg-\(--canvas\)/.test(workspace), 6, 'workspace_not_using_canvas_token');
add(!/bg-\(--surface\)/.test(landing), 6, 'landing_lacks_ivory_surfaces');
add(!/palette[\s\S]*accent:\s*"#6e2f3a"/i.test(evalDashboard), 6, 'eval_palette_not_aligned');

bubble(!/justify-end/.test(messages), 18, 'human_message_not_right_aligned');
bubble(!/bg-\(--accent-soft\)/.test(messages), 18, 'human_message_has_no_distinct_fill');
bubble(!/rounded-xl/.test(messages), 8, 'human_message_has_no_bubble_radius');
bubble(!/max-w-\[640px\]/.test(messages), 6, 'human_message_width_not_bounded');
bubble(/border-l\s+border-\(--accent\)/.test(messages), 10, 'legacy_human_message_left_rule_present');

scale(!/h-\[64px\]/.test(landing), 6, 'landing_navigation_too_tall');
scale(!/clamp\(40px,6vw,72px\)/.test(landing), 10, 'landing_hero_type_too_large');
scale(!/py-16\s+lg:py-20/.test(landing), 8, 'landing_sections_too_spacious');
scale(/text-5xl/.test(landing), 8, 'landing_section_heading_too_large');
scale(!/grid-template-columns:\s*256px/.test(css), 8, 'workspace_rail_too_wide');
scale(!/max-width:\s*760px/.test(css), 8, 'workspace_reading_surface_too_wide');
scale(!/min-h-12/.test(composer), 6, 'composer_too_tall');
scale(!/space-y-3\s+text-sm\s+leading-6/.test(messages), 8, 'assistant_body_type_too_large');
scale(!/text-sm[^\n]*leading-6/.test(messages.slice(messages.indexOf('export function UserMessage'))), 6, 'human_bubble_type_too_large');
scale(!/min-h-10/.test(primaryButton), 4, 'primary_button_target_too_small');
scale(!/max-w-\[1440px\]/.test(evalDashboard), 6, 'eval_dashboard_too_wide');
scale(!/min-h-\[96px\]/.test(evalDashboard), 6, 'eval_matrix_cells_too_tall');

contrast(contrastFailures.length > 0, contrastFailures.length * 12, `token_contrast_failure:${contrastFailures.map((pair) => pair.join('_on_')).join('|')}`);
contrast(/\na\s*\{[^}]*color:\s*inherit/s.test(css), 20, 'global_anchor_color_overrides_button_contrast');
contrast(!/text-\(--surface\)/.test(requestAccessMarkup), 8, 'request_access_missing_contrast_text');

console.log(`METRIC visual_debt=${visualDebt}`);
console.log(`METRIC odd_pixel_values=${oddPixelFindings.length}`);
console.log(`METRIC legacy_bronze_refs=${legacyBronzeRefs}`);
console.log(`METRIC human_bubble_debt=${humanBubbleDebt}`);
console.log(`METRIC scale_debt=${scaleDebt}`);
console.log(`METRIC contrast_debt=${contrastDebt}`);
console.log(`ASI notes=${notes.join(',')}`);
if (oddPixelFindings.length) console.log(`ASI odd_pixels=${oddPixelFindings.slice(0, 24).join(',')}`);
NODE

if [[ "${UI_ONLY:-0}" == "1" ]]; then
  exit 0
fi

set +e
(cd frontend && npm run lint >/tmp/locus-redesign-lint.out 2>&1)
lint_exit=$?
redesign_node_bin="${NEXT_NODE_BIN:-node}"
(cd frontend && "$redesign_node_bin" node_modules/next/dist/bin/next build >/tmp/locus-redesign-build.out 2>&1)
build_exit=$?
set -e
printf 'METRIC lint_exit=%s\n' "$lint_exit"
printf 'METRIC build_exit=%s\n' "$build_exit"
if [[ "$lint_exit" != "0" ]]; then tail -40 /tmp/locus-redesign-lint.out >&2; fi
if [[ "$build_exit" != "0" ]]; then tail -60 /tmp/locus-redesign-build.out >&2; fi
exit 0
