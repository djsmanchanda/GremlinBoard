# Execution Planning Document

## Goal

Maintain GremlinBoard as a monitoring-station product with:
- a strict fixed-size tile grid
- locked View mode for live monitoring
- explicit Edit mode for layout and widget configuration
- persistent board mode-adjacent settings such as density, grid overlay, and reduced motion
- a spec-first widget contract
- a Python widget runtime with lifecycle, scheduling, health monitoring, and observability
- a maintainable Next.js + FastAPI architecture

## Current Surface

- Board UI: live board, command box, View/Edit mode, selected-widget settings, stats toggle, strict drag/resize behavior
- System Panel: provider setup, credentials, runtime settings, density presets, observability overview, widget health, metrics, event timeline
- Spec Studio: idea/spec validation, scaffold preview, generation jobs, feedback refinement, review-gated install
- Runtime: registry-backed services, websocket snapshots, restart/backoff, stale-service monitoring, local persistence

## Active Documentation Notes

- Board density is persisted through the board controls with `wall monitor`, `half display`, and `operator desk` presets.
- Stats are a toggleable rail on widgets, not a separate always-on board overlay.
- Source settings behave as a selected-widget inspector in Edit mode.
- Runtime warnings and widget/provider failures are the alert priority layer.
- Playwright smoke tests are expected as the browser-level gate, but this snapshot does not include a committed smoke harness or package script.

## Validation Steps

1. Validate widget manifests against the strict registry rules.
2. Run backend tests: `python -m pytest apps/api/tests -q`.
3. Run frontend typecheck: `npm run typecheck`.
4. Run frontend lint: `npm run lint`.
5. Run frontend build: `npm run build`.
6. Run Playwright smoke tests when the smoke harness is present.
7. Sanity check the local runtime by starting the API and web app, opening the board, toggling View/Edit, opening the command box, selecting a widget, and checking System Panel health.

## Risks

- Browser smoke coverage can drift because the Playwright harness is not currently committed.
- Dynamic widget renderer loading is still constrained by frontend renderer support.
- Local setup depends on working Python/pip, `uvicorn`, Node, and npm.
- Data-backed widgets need credentials or fallback behavior for provider failures.
