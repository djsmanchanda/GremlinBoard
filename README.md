# GremlinBoard

GremlinBoard is a monitoring-station board for registered live widgets. It keeps day-to-day operation in a locked View mode, exposes Edit mode only when the surface needs tuning, and routes every widget through the manifest registry and disposable runtime services.

## Stack

- Frontend: Next.js App Router, TypeScript, React, Tailwind, Zustand
- Backend: FastAPI, Pydantic, async SQLAlchemy, SQLite for local persistence
- Runtime: strict widget registry with lightweight Python services and websocket board updates

## Current Product

- Fixed widget sizes only: `1x1`, `1x2`, `2x2`, `4x2`, `2x4`, `4x4`
- Responsive board packing from 4 to 8 columns
- Persistent board layout, widget state, runtime settings, appearance settings, credentials, and generated-widget metadata
- View/Edit board modes: View locks the monitoring surface; Edit enables drag, resize, widget controls, and source settings
- Board density presets: `wall monitor`, `half display`, and `operator desk`, persisted in the board controls
- Side inspector: selected-widget controls and source settings stay outside the tile so tile geometry does not shift
- Alert priority layer: runtime warnings, widget errors, provider failures, and timeline levels are surfaced before lower-priority metrics
- System Panel for provider setup, credentials, runtime cadence, density, grid overlay, reduced motion, observability, and widget health
- Spec Studio for staged AI widget creation: spec draft, validation, scaffold, codegen, review, install

## Performance Posture

GremlinBoard is intended to behave like a local control panel, not a heavy dashboard tab. The current runtime and UI are tuned around a lightweight background footprint:

- Use production-style local starts for day-to-day operation. `scripts/start-api.*` and `npm run start:api` run Uvicorn without reload watchers or access-log spam.
- Reserve `npm run dev:api` and `npm run dev:web` for active development. Dev reloaders and Next dev compilation are expected to use more CPU.
- API GET requests avoid unnecessary JSON content headers so simple reads do not trigger extra CORS preflights.
- Session rows are touched at most every 300 seconds instead of on every request.
- Runtime snapshots are only serialized and published when websocket subscribers exist.
- Event queues are bounded so disconnected or slow UI clients cannot create unbounded backend memory pressure.
- System Panel observability polling follows the configured monitor cadence and pauses while the tab is hidden.
- Countdown widgets render second-by-second locally in the browser, while backend refresh runs on a slower interval.
- Sports widgets default to a slower polling cadence with manual refresh available when operators need fresh data immediately.
- Reduced motion is the default appearance posture, with `prefers-reduced-motion` also respected.
- Root `*.log` files are ignored and existing dev logs were removed from Git tracking.

## Repository Layout

- `apps/web`: Next.js monitoring board, System Panel, and Spec Studio
- `apps/api`: FastAPI backend, registry APIs, runtime manager, settings, observability, and AI generation pipeline
- `widgets`: registry-backed widget packs
- `schemas`: shared machine-readable widget schemas
- `scripts`: small local start helpers

## Prerequisites

- Node.js 20+
- npm that can run workspace commands
- Python 3.12+
- `pip` available through `python -m pip`

## Quickstart

```bash
npm install
python -m pip install -e apps/api
npm run dev:api
```

In another terminal:

```bash
npm run dev:web
```

Open `http://localhost:3000`. The frontend expects the API at `http://127.0.0.1:8000/api` by default. Copy `.env.example` to `.env` if you need to override ports, origins, database path, or local user defaults.

For a lighter local utility run after building the web app:

```bash
npm run build
npm run start:api
```

Then run the web production server in another terminal:

```bash
npm run start:web
```

## Daily Development

```bash
npm run typecheck
npm run lint
npm run build
python -m pytest apps/api/tests -q
```

Focused performance/runtime checks used for the latest optimization pass:

```bash
python -m pytest apps/api/tests/test_platform_foundations.py -p no:langsmith
python -m pytest apps/api/tests/test_runtime_integration.py -p no:langsmith
node node_modules/typescript/bin/tsc -p apps/web/tsconfig.json --noEmit
```

The `-p no:langsmith` flag may be needed on machines where an unrelated global pytest plugin interferes with local Pydantic imports.

The web app includes Playwright smoke coverage for monitoring-station viewports:

```bash
npm run test:e2e:smoke
```

The smoke suite starts the web dev server, mocks the board API, and checks `960x1080`, `1280x720`, `1920x1080`, and `2560x1440` for board load, View/Edit mode, density controls, alert priority, and the side inspector.

## Setup Troubleshooting

### `pip` is missing

Use the interpreter-owned entry point first:

```bash
python -m ensurepip --upgrade
python -m pip --version
python -m pip install -e apps/api
```

If `ensurepip` is unavailable, install or repair Python 3.12+ with pip enabled, then reopen the terminal so PATH is refreshed.

### `uvicorn` is missing

Install the API package from the repo root. `uvicorn[standard]` is declared in `apps/api/pyproject.toml`.

```bash
python -m pip install -e apps/api
python -m uvicorn --app-dir apps/api gremlinboard_api.main:app --reload --host 127.0.0.1 --port 8000
```

You can also run `npm run dev:api` after the install step.

### Global `npm` is broken

Avoid relying on global package installs. Use the project workspace scripts from the repo root after repairing the Node/npm installation:

```bash
node --version
npm --version
npm install
npm --workspace apps/web run dev
```

If `npm` itself fails before it can run, reinstall Node.js 20+ or switch to a known-good Node install, then rerun `npm install`.

## Architecture Notes

- Widgets never bypass the registry.
- Services are loaded from manifests and run as disposable async runners.
- The board persists instance order and size; the UI packs those widgets onto a strict responsive grid with 4 to 8 columns.
- View mode is the default monitoring posture. Edit mode enables drag from the top interaction band, bottom-right resize handles, widget controls, and the side inspector.
- Resize previews use dashed outlines for every allowed size that fits the current column count, with the nearest target highlighted while resizing.
- Freshness, uptime, mode, and restart count stay compact in widget chrome and can be expanded with the persistent Stats toggle.
- Runtime warnings and widget/provider failures form the alert layer and should be easier to notice than normal metrics.
- Background runtime work should scale with active operators and configured cadence, not with idle tabs or stale subscribers.
