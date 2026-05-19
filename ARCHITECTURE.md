# GremlinBoard Architecture

## Overview

GremlinBoard is a monitoring-station surface for live widgets backed by disposable microservices. The board is optimized for steady watch duty first, with editing and generation flows staged behind explicit controls.

The system should feel like a local utility/control panel: quiet when idle, explicit when acting, and conservative with CPU, GPU, network, and disk writes. Development reloaders are useful during implementation, but the normal local runtime should avoid watcher-heavy processes, unnecessary polling, and decorative animation cost.

## Layers

### 1. Board Layer

Handles:
- strict responsive grid packing from 4 to 8 columns
- View/Edit board mode
- widget selection
- edit-only drag, resize, start/stop, refresh, remove, and settings controls
- persistent layout ordering and tile sizes
- command box widget add flow
- alert-first runtime warning display
- websocket lifecycle tied to tab visibility so hidden boards do not hold realtime subscriptions open
- reduced animation and GPU-heavy styling by default

### 2. Widget Layer

Handles:
- renderer loading from registered manifests
- compact data display inside fixed tile sizes
- lifecycle and freshness presentation
- selected-widget source settings
- provider state display
- widget-level runtime issue summaries

### 3. Runtime Layer

Handles:
- widget service lifecycle
- scheduled refresh and live update directives
- websocket board snapshots
- runtime health monitoring
- restart/backoff policy
- metrics, logs, and observability snapshots
- cleanup on widget removal
- bounded event delivery queues
- snapshot publication only when websocket subscribers exist
- monitor-loop guardrails so one bad record cannot kill runtime health monitoring

### 4. System Layer

Handles:
- local user/session context
- provider credential setup
- runtime settings such as monitor cadence and retention limits
- appearance settings such as density, grid overlay, and reduced motion
- observability overview, widget health, metrics, and event timeline

### 5. Spec Layer

Handles:
- natural language to widget spec
- widget manifests
- scaffold preview
- code generation requests
- review-gated install
- rollback for generated widget versions

## Widget Lifecycle

`created -> installing -> running -> paused -> expired -> removed`

`error` can occur at any stage and should surface through the alert priority layer.

## Communication

Preferred communication patterns:
- websocket for board snapshots and registry update notices
- REST for board actions, system settings, credentials, specs, plugins, and observability
- background tasks for scheduled widget services and generation jobs
- local persistence for board state, settings, credentials, runtime logs, metrics, plugins, and generation records

Performance rules:
- GET requests should remain simple requests where possible; do not add JSON content headers to bodyless reads.
- Hidden browser tabs should pause polling and close board streams until visible again.
- Runtime snapshots should not be serialized just to publish to zero subscribers.
- Metrics retention trimming should work on bounded windows instead of scanning thousands of rows every monitor tick.
- Session activity should be throttled to coarse intervals instead of written on every request.

## Data Model

Core entities:
- Board
- WidgetInstance
- WidgetManifest
- WidgetPlugin and WidgetPluginVersion
- Microservice runner state
- RuntimeMetric
- RuntimeLog
- SystemSettings
- ApiCredential
- GenerationJob

## Runtime Strategy

- Keep widget services small and disposable.
- Let the backend own lifecycle, scheduling, persistence, and alertable health.
- Let the frontend render the latest state and make operator actions explicit.
- Keep normal monitoring in locked View mode; use Edit mode for layout and configuration changes.
- Prefer slower default refresh intervals with explicit manual refresh over always-live polling.
- Countdown-style visual ticks belong in the renderer when they do not require fresh backend data.
- Treat `uvicorn --reload` and Next dev mode as development-only tools, not the steady-state control-panel runtime.

## Testing Strategy

- Backend: pytest coverage for registry, runtime integration, providers, platform foundations, plugins, and generation pipeline.
- Frontend: typecheck, lint, and production build.
- Browser smoke: Playwright should validate core routes and workflows when its smoke harness is present.
- Performance-sensitive changes should at least run platform foundation tests, runtime integration tests, TypeScript typecheck, and production web build.

## Future Expansion

- multi-board workspaces
- manifest-driven dynamic renderer loading
- shared widget packs
- widget marketplace
- richer alert filtering and acknowledgement
- desktop shell only when packaging is needed
