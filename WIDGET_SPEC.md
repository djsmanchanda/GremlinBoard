# Widget Spec Format

Every widget begins as a spec.

## Required Fields

- id
- name
- category
- description
- min_size
- preferred_size
- refresh_policy
- source_type
- permissions
- output_schema
- renderer_type
- lifecycle_policy

## Example

```yaml
id: sports_ipl_live
name: IPL Live Score
category: sports
description: Live match widget for IPL scores and match state
min_size: 2x2
preferred_size: 4x2
refresh_policy:
  mode: live
  interval_seconds: 20
source_type: api
permissions:
  - network
output_schema:
  primary: score
  secondary: overs
  status: match_state
renderer_type: card
lifecycle_policy:
  expire_on: match_end
```

## Rules

- Specs must be machine-readable.
- Specs must be validated before scaffolding.
- Specs must not contain arbitrary executable code.
- Specs must map cleanly to one widget runtime and one renderer.
- Widget renderers should be data-first and avoid repeating board chrome such as title, freshness, uptime, mode, or restart count.
- Widgets must support only approved sizes: `1x1`, `1x2`, `2x2`, `4x2`, `2x4`, and `4x4`.
- Widget descriptions should fit the live control-surface language: compact, observable, and useful at high board density.

## Board Interaction Language

- The board scales from 4 to 8 columns as resolution increases.
- Widgets move from the top interaction band, excluding resize corners.
- Widgets resize from the bottom-right corner only.
- Resize feedback is shown with dashed outlines for allowed sizes; the nearest size is highlighted while dragging.
- Runtime stats are exposed through the board-level Stats overlay, not permanent widget body content.
