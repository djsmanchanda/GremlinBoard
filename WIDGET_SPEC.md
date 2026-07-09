# Widget Spec Format

Every widget begins as a spec and must become a manifest before it can be installed.

## Required Spec Fields

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

## Manifest Requirements

Every installed widget manifest must define:
- id
- version
- name
- category
- description
- min_size
- preferred_size
- allowed_sizes
- refresh_policy
- lifecycle_policy
- runtime_policy
- permissions
- renderer
- service
- config_schema

## Process Widget Services

A widget may run as an out-of-process service when its manifest uses:

```json
{
  "service": {
    "kind": "process",
    "command": ["bin/widget.exe"]
  }
}
```

Rules:

- `service.command` is argv, not a shell string.
- The command must be non-empty.
- Path-like executables must resolve inside the widget package directory.
- Do not use `..`, absolute host paths outside the package, or shared global binaries.
- The runtime starts the process with the widget package as its working directory.
- Stdout is protocol-only. Human diagnostics must go to stderr.
- Process widgets still need a registered manifest, config schema, renderer, refresh policy, lifecycle policy, and runtime policy.

Process services speak newline-delimited JSON-RPC 2.0 over stdio:

| Method | Params | Expected result |
| --- | --- | --- |
| `start` | `{ "instance_id": "...", "config": {...} }` | JSON value; state object preferred |
| `stop` | `{}` | JSON value, then graceful process exit |
| `health` | `{}` | Health object |
| `get_state` | `{}` | State object |
| `refresh` | `{ "force": true }` | State object |
| `set_config` | `{ "config": {...} }` | JSON value |

Unknown methods must return JSON-RPC error code `-32601`.

## Example

```yaml
id: sports_ipl_live
name: IPL Live Score
category: sports
description: Dense live sports monitor for IPL scores and match state
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
- Widgets must support only approved sizes: `1x1`, `1x2`, `2x2`, `4x2`, `2x4`, and `4x4`.
- `min_size` and `preferred_size` must be included in `allowed_sizes`.
- Widget renderers should be data-first and avoid repeating board controls.
- Widget descriptions should fit the monitoring-station language: compact, observable, and useful at high board density.
- Generated widgets cannot install directly from raw AI output; they must pass review-gated staging.

## Board Interaction Language

- The board scales from 4 to 8 columns as available width increases.
- View mode is locked for monitoring.
- Edit mode enables selection, controls, source settings, top-band dragging, and bottom-right resizing.
- Widgets move from the top interaction band, excluding the resize corners.
- Widgets resize from the bottom-right corner only.
- Resize feedback is shown with dashed outlines for allowed sizes that fit the current board width; the nearest size is highlighted while dragging.
- Freshness, uptime, refresh mode, and restart count stay hidden by default and expand through the board Stats toggle.
- Widget alerts use three visible categories: red `critical` when the widget is not working properly, yellow `alert` for non-fatal issues, and green `completed` only when widget logic explicitly publishes `state.complete = true`.
