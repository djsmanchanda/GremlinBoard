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
- Performance baseline: hidden tabs should stop realtime/polling work, simple reads should avoid CORS preflights, and backend loops should use conservative cadences unless the operator asks for immediate refresh
- Local process model: normal use should be tray-managed utility mode, while active development can run as a second managed stack on separate ports

## Active Documentation Notes

- Board density is persisted through the board controls with `wall monitor`, `half display`, and `operator desk` presets.
- Stats are a toggleable rail on widgets, not a separate always-on board overlay.
- Source settings behave as a selected-widget inspector in Edit mode.
- Runtime warnings and widget/provider failures are the alert priority layer.
- Playwright smoke tests cover `960x1080`, `1280x720`, `1920x1080`, and `2560x1440`.
- The control-panel runtime should be able to run without dev reloaders, access-log spam, one-second backend loops, or always-open hidden-tab streams.
- Windows launchers provide one-button stable/dev starts, system-tray visibility, and a max-two managed instance policy.
- Stable launcher ports are web/API `7555`/`2555`; dev ports are `7556`/`2556`. Startup must fail fast if those ports are already held by unmanaged processes.

## Lightweight Roadmap

- Make the tray status-aware: show API/web liveness, last startup error, and direct links to launcher logs.
- Add an operator-presence idle mode that pauses non-critical widget refresh when no board or System Panel client is connected.
- Add a backend suspend/resume API so the tray can put the runtime into low-power mode without fully stopping services.
- Move expensive provider calls behind per-widget TTL caches and provider backoff budgets.
- Split heavy frontend routes so board startup does not load Spec Studio or full observability code.
- Keep the normal launcher on production web assets; reserve Next dev, reload watchers, source maps, and verbose logs for the dev launcher.
- Add a compact process health probe in the tray menu so API/web failures are visible without opening the browser.

## Validation Steps

1. Validate widget manifests against the strict registry rules.
2. Run backend tests: `python -m pytest apps/api/tests -q`.
3. Run frontend typecheck: `npm run typecheck`.
4. Run frontend lint: `npm run lint`.
5. Run frontend build: `npm run build`.
6. Run Playwright smoke tests when the smoke harness is present.
7. Sanity check the local runtime by starting the API and web app, opening the board, toggling View/Edit, opening the command box, selecting a widget, and checking System Panel health.
8. For performance-sensitive runtime changes, also run:
   - `python -m pytest apps/api/tests/test_platform_foundations.py -p no:langsmith`
   - `python -m pytest apps/api/tests/test_runtime_integration.py -p no:langsmith`
   - `node node_modules/typescript/bin/tsc -p apps/web/tsconfig.json --noEmit`

## Risks

- Dynamic widget renderer loading is still constrained by frontend renderer support.
- Local setup depends on working Python/pip, `uvicorn`, Node, and npm.
- Data-backed widgets need credentials or fallback behavior for provider failures.
- Existing local SQLite state can contain old widget configs or timestamps; runtime comparisons must normalize persisted datetimes and docs should distinguish existing data from new defaults.
