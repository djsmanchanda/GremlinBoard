# GremlinBoard Roadmap

## Phase 1 - Board Foundation

- Strict responsive grid
- Fixed tile sizes only
- Registry-backed core widgets
- Persistent layout
- Command box add flow
- View/Edit board mode

Status: implemented for the local monitoring board.

## Phase 2 - Monitoring Station UX

- Locked View mode for watch duty
- Edit-only drag, resize, widget controls, and selected-widget settings
- Board density presets
- Stats toggle for freshness, uptime, mode, and restart count
- Three-category widget alert layer: red `critical`, yellow `alert`, and explicit green `completed`

Status: active product shape.

## Phase 3 - Runtime and Observability

- Python microservice runner
- Health checks
- Restart, stop, refresh, and remove actions
- Metrics and runtime logs
- Event delivery channel
- System Panel observability overview

Status: implemented locally; continue hardening failure/restart tests.

## Phase 4 - Provider and Settings Setup

- Provider credential setup
- AI provider defaults and fallback chain
- Runtime cadence settings
- Appearance settings including density, grid overlay, and reduced motion

Status: implemented through System Panel.

## Phase 5 - Spec Studio and AI Tooling

- Natural language input
- Structured widget spec generation
- Validation layer
- Scaffold preview
- Review-gated install
- Generated widget rollback

Status: implemented as a staged flow; production provider integrations can deepen over time.

## Phase 6 - Testing and Packaging

- Keep backend pytest coverage current
- Keep frontend typecheck, lint, and build green
- Add/maintain Playwright smoke tests for board, System Panel, and Spec Studio
- Consider Tauri packaging only when desktop distribution is needed
