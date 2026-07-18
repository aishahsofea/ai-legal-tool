# Autoresearch: Locus cream interface redesign

## Objective
Redesign the complete frontend as a quiet, premium legal-research product. Use a light cream and ivory visual system with near-black text and a restrained oxblood accent. Human chat messages must be unmistakable right-aligned bubbles. Layout sizing, spacing, typography, radii, and icon dimensions must use even pixel values. Keep the visual density compact and require WCAG AA contrast for every theme text pairing.

## Loop
This is a goal-based loop: make one coherent implementation pass, run `./autoresearch.sh`, inspect the measured debt and build checks, then repeat until the stop condition is met.

## Stop condition
- `visual_debt=0`
- `odd_pixel_values=0`
- `legacy_bronze_refs=0`
- `human_bubble_debt=0`
- `scale_debt=0`
- `contrast_debt=0`
- `lint_exit=0`
- `build_exit=0`

## Metrics
- **Primary**: `visual_debt` (unitless, lower is better) — deterministic design-system and component-shape debt.
- **Secondary**: `odd_pixel_values`, `legacy_bronze_refs`, `human_bubble_debt`, `scale_debt`, `contrast_debt`, `lint_exit`, and `build_exit`.

## Even-number rule
All explicit pixel values used for layout sizing, spacing, typography, radii, and icons must be even integers. Crisp `1px` borders, rules, focus rings, and SVG strokes are explicit optical exceptions. Percentages, unitless line heights, font weights, opacity, animation timings, and data values are outside the rule.

## Accessibility rule
Normal text/background token pairs must meet a contrast ratio of at least 4.5:1. Primary controls must keep at least a 40px visible height, while compact controls must remain at least 32px; both exceed WCAG 2.2's 24px minimum target size.

## Files in scope
- `frontend/app/globals.css`, `frontend/app/layout.tsx`
- `frontend/app/page.tsx`, `frontend/app/workspace/page.tsx`
- `frontend/app/evals/EvalDashboard.tsx`
- `frontend/components/**/*.tsx`

## Constraints
- Preserve all existing routes, chat/thread behavior, streaming, cancellation, citations, and eval behavior.
- Do not change the backend, agent graph, API contract, env vars, or legal-answer behavior.
- Do not hide citations or remove source access.
- Do not add dependencies.
- Do not special-case the evaluator; improve the actual interface.

## Verification
`./autoresearch.sh` prints the metrics and runs the frontend linter and production build. `./autoresearch.checks.sh` enforces the full stop condition.
