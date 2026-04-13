# GremlinBoard

GremlinBoard is a modular widget runtime board for OpenClaw.

## Stack

- Frontend: Next.js App Router, TypeScript, Tailwind, Zustand
- Backend: FastAPI, async SQLAlchemy, Pydantic
- Runtime: strict widget registry with lightweight Python services

## MVP Scope

- Fixed grid sizes only: `1x1`, `1x2`, `2x2`, `4x2`, `2x4`, `4x4`
- Persistent board layout and widget state
- Registry-driven widget installation and rendering
- Widget lifecycle controls: `created`, `running`, `paused`, `expired`, `removed`, `error`
- Scheduled refresh runtime with websocket board updates
- Built-in widgets:
  - countdown
  - news
  - sports
  - trending
  - pinboard
- Spec-first widget staging flow at `/studio`

## Repository Layout

- `apps/web`: Next.js board UI
- `apps/api`: FastAPI backend and runtime
- `widgets`: registry-backed widget packs
- `schemas`: shared machine-readable widget schemas

## Run

### Web

```bash
npm install
npm run dev:web
```

### API

```bash
cd apps/api
python -m pip install -e .
uvicorn gremlinboard_api.main:app --reload
```

The frontend expects the API at `http://127.0.0.1:8000/api` by default.

## Architecture Notes

- Widgets never bypass the registry.
- Services are loaded from widget manifests and run as disposable async runners.
- The board persists instance order and size; the UI packs those widgets onto a strict four-column grid.
- Widget creation is staged through spec validation and scaffold preview before any install step.
