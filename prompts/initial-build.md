# GremlinBoard Initial Build Prompt

Build GremlinBoard from scratch as a modular widget dashboard platform.

Core Requirements:

- Fixed tile grid system supporting:
  1x1
  1x2
  2x2
  4x2
  2x4
  4x4

- Drag/drop snapping grid layout.
- Persistent widget positioning/state.
- Modular widget registry.
- Background microservice runtime manager.
- Python microservice support.
- Widget lifecycle:
  created / running / paused / expired / removed / error.

Widgets supported initially:
- Timer widget
- News widget
- Sports widget
- Reddit/HackerNews trending widget
- Personal notes/pinboard widget

Architecture Requirements:
- Frontend: Next.js + Tailwind + shadcn.
- Backend runtime: FastAPI/Python.
- State/Websocket updates.
- SQLite/Postgres persistence abstraction.
- Redis optional cache/event bus.

Development Rules:
- Build scalable architecture.
- Strong TypeScript typing.
- Modular folder structure.
- Avoid hardcoding widget logic.
- All widgets must use registry + manifest system.
- All widgets must declare min/preferred tile sizes.

Output production-ready code only.
Ensure app runs immediately after install.
