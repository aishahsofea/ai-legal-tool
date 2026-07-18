#!/usr/bin/env bash
set -euo pipefail

output="$(./autoresearch.sh)"
printf '%s\n' "$output"

for metric in \
  'visual_debt=0' \
  'odd_pixel_values=0' \
  'legacy_bronze_refs=0' \
  'human_bubble_debt=0' \
  'scale_debt=0' \
  'contrast_debt=0' \
  'lint_exit=0' \
  'build_exit=0'
do
  if ! grep -q "METRIC ${metric}" <<<"$output"; then
    printf 'Stop condition failed: %s\n' "$metric" >&2
    exit 1
  fi
done
