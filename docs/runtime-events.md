# Runtime Events

GremlinBoard runtime events are the local event language shared by the widget runtime, board websocket, generation pipeline, plugin system, observability, CLI, and future agent runtime.

The event system is intentionally small and local-first. It is not a distributed message broker, and it must not introduce Redis, Kafka, or remote-worker assumptions into the default runtime.

## Envelope

Every runtime event uses a typed envelope:

```json
{
  "id": "2d690af470d54d5a8b43b4c6cfd32c7d",
  "sequence": 42,
  "schema_version": 1,
  "type": "widget.started",
  "category": "widget",
  "level": "info",
  "message": "widget service started",
  "source": {
    "component": "runtime_manager",
    "board_id": "default",
    "widget_instance_id": "01J...",
    "widget_id": "news"
  },
  "correlation_id": "request-123",
  "causation_id": "01J...",
  "visibility": "both",
  "persistence": "ephemeral",
  "replayable": true,
  "payload": {},
  "created_at": "2026-05-20T12:00:00Z"
}
```

Compatibility rule: `type` and `payload` remain top-level fields for existing websocket clients. New fields are additive.

## Categories

Allowed categories are:

- `board`: board snapshots, future board patches, stream reconciliation.
- `widget`: widget lifecycle, refresh, health, error, and state events.
- `runtime`: runtime startup, monitor, recovery, cadence, and power-state events.
- `provider`: provider health, stale fallback, backoff, circuit-breaker, and request-budget events.
- `job`: future durable job queue lifecycle events.
- `generation`: spec, scaffold, codegen, review, install, and rollback events.
- `plugin`: registry sync, plugin install, update, rollback, enable, disable, and uninstall events.
- `operator`: CLI, tray, and board operator intent events.
- `system`: platform errors, stream resets, auth/session, settings, and process-level events.
- `agent`: AgentSession, AgentTask, SubAgent, review, and generation-backed orchestration events.

The first segment of `type` must match the category, except legacy `registry.*` events map to `plugin`.

## Persistence Classes

Events choose persistence explicitly:

- `ephemeral`: websocket invalidation, snapshots, registry notices, progress ticks, and queue/status broadcasts. These may be dropped under websocket backpressure.
- `timeline`: operator-auditable facts such as runtime failures, generation failures, plugin rollbacks, provider degradation, and agent review requests.
- `state`: events that describe a committed state change. The domain table remains the source of truth; the event is an indexable signal after commit.

The bus does not write to the database. Observability subscribes to typed events and persists only `timeline` and `state` events. Runtime logs that are already written through `RuntimeManager.log()` are broadcast as `ephemeral` envelopes to avoid duplicate persistence loops.

## Visibility

Events choose transport visibility explicitly:

- `internal`: backend subscribers only.
- `websocket`: board stream clients only.
- `both`: internal subscribers and websocket clients.

Websocket delivery is bounded and lossy for ephemeral events. Internal timeline persistence must not depend on a lossy websocket queue.

## Replay And Reconnect

The event bus assigns a monotonic in-memory `sequence` to each event.

Replay is bounded:

- recent replayable events are kept in a small memory ring.
- websocket clients may reconnect with `last_seq`.
- if `last_seq` is replayable, the server replays newer events.
- if `last_seq` is missing, invalid, or too old, the server sends a fresh `board.snapshot`.
- `board.snapshot` is always the authoritative state base.

Queue overflow for websocket subscribers emits `stream.reset`. The websocket route handles `stream.reset` by sending a fresh `board.snapshot`, then continues live delivery.

## Queue And Backpressure Rules

- Each subscriber has its own bounded queue.
- A slow subscriber cannot block publishers or other subscribers.
- Websocket queues drop/coalesce ephemeral events and reset the stream when overflow occurs.
- Internal subscribers drop the oldest queued item under pressure, and runtime status exposes dropped and queued counts.
- Critical persistence should use direct domain writes or timeline/state events handled by an internal observability sink.

## Event Examples

### `widget.started`

```json
{
  "type": "widget.started",
  "category": "widget",
  "level": "info",
  "source": {"component": "runtime_manager", "widget_instance_id": "w1", "widget_id": "sports"},
  "persistence": "ephemeral",
  "payload": {"version": "1.0.0"}
}
```

### `widget.failed`

```json
{
  "type": "widget.failed",
  "category": "widget",
  "level": "error",
  "source": {"component": "runtime_manager", "widget_instance_id": "w1", "widget_id": "sports"},
  "persistence": "timeline",
  "payload": {"error": "refresh timed out", "consecutive_failures": 3}
}
```

### `runtime.idle_entered`

```json
{
  "type": "runtime.idle_entered",
  "category": "runtime",
  "level": "info",
  "source": {"component": "presence_manager"},
  "persistence": "timeline",
  "payload": {"reason": "no operator presence"}
}
```

### `generation.completed`

```json
{
  "type": "generation.completed",
  "category": "generation",
  "level": "info",
  "source": {"component": "generation_pipeline", "job_id": "job1"},
  "persistence": "timeline",
  "payload": {"widget_id": "agent_overview", "review_required": true}
}
```

### `provider.backoff_started`

```json
{
  "type": "provider.backoff_started",
  "category": "provider",
  "level": "warning",
  "source": {"component": "provider_runtime", "provider_id": "newsapi"},
  "persistence": "timeline",
  "payload": {"backoff_seconds": 60, "consecutive_failures": 4}
}
```

### `agent.waiting_for_review`

```json
{
  "type": "agent.waiting_for_review",
  "category": "agent",
  "level": "warning",
  "source": {"component": "agent_registry", "agent_id": "generation:job1", "job_id": "job1"},
  "persistence": "timeline",
  "payload": {
    "session_id": "local-generation",
    "status": "waiting_for_review",
    "linked_jobs": ["job1"],
    "linked_widgets": ["agent_overview"],
    "review_required": true
  }
}
```

### `agent.progress_updated`

```json
{
  "type": "agent.progress_updated",
  "category": "agent",
  "level": "info",
  "source": {"component": "agent_registry", "agent_id": "generation:job1", "job_id": "job1"},
  "persistence": "ephemeral",
  "payload": {
    "session_id": "local-generation",
    "status": "running",
    "progress": 70,
    "metadata": {"current_step": "codegen"}
  }
}
```

## Current Backend Strategy

The current backend keeps full `board.snapshot` fanout as the compatibility path. Future `board.patch` events can be introduced after frontend support lands. Until then, backend changes should publish typed envelopes but continue to keep board state reconstructable from the REST board endpoint and full snapshots.
