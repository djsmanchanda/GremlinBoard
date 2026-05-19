# GremlinBoard Architecture

## Overview

GremlinBoard is a monitoring-station surface for live widgets backed by disposable microservices. The board is optimized for steady watch duty first, with editing and generation flows staged behind explicit controls.

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

## Testing Strategy

- Backend: pytest coverage for registry, runtime integration, providers, platform foundations, plugins, and generation pipeline.
- Frontend: typecheck, lint, and production build.
- Browser smoke: Playwright should validate core routes and workflows when its smoke harness is present.

## Future Expansion

- multi-board workspaces
- manifest-driven dynamic renderer loading
- shared widget packs
- widget marketplace
- richer alert filtering and acknowledgement
- desktop shell only when packaging is needed
