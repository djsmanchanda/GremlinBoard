# GremlinBoard Architecture

## Overview

GremlinBoard is a board of live tiles backed by microservices.

## Layers

### 1. Board Layer
Handles:
- layout
- drag/drop
- snapping
- resizing
- persistence
- selection
- board-level shortcuts

### 2. Widget Layer
Handles:
- rendering
- config
- state display
- source binding
- lifecycle presentation

### 3. Runtime Layer
Handles:
- widget process lifecycle
- scheduling
- refresh loops
- event delivery
- cleanup
- health monitoring

### 4. Spec Layer
Handles:
- natural language to widget spec
- widget manifests
- code generation requests
- AI tooling integration

## Widget Lifecycle

created -> installing -> running -> paused -> expired -> removed

error can occur at any stage.

## Communication

Preferred communication patterns:
- websocket for live updates
- server-sent events where appropriate
- background tasks for scheduled jobs
- local persistence for board state

## Data Model

Core entities:
- Board
- WidgetInstance
- WidgetManifest
- Microservice
- WidgetEvent
- WidgetState
- GenerationJob

## Runtime Strategy

- Keep widget services small.
- Keep the board UI fast.
- Let the backend own scheduling and persistence.
- Let the frontend render only the latest state.

## Future Expansion

- multi-board workspaces
- shared widget packs
- widget marketplace
- self-healing widgets
- agent-driven widget improvements
