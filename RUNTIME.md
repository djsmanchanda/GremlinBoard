# Runtime Management Rules

All widget microservices run under `RuntimeManager`.

## Responsibilities

RuntimeManager owns:
- service start, stop, restart, and refresh
- scheduled refresh loops and live-update directives
- health monitoring
- heartbeat and stale-service checks
- restart backoff and terminal error state
- websocket event delivery
- metrics and runtime log emission
- cleanup when a widget is removed

## Failure Policy

- Each widget manifest may define runtime policy values such as timeouts, max retries, retry backoff, and stale-after seconds.
- Failed refresh/start/stop calls are recorded as runtime logs.
- A widget enters `error` after the retry policy is exhausted.
- Widget and provider failures are part of the alert priority layer and should surface before routine metrics.

## Service Contract

Every service must support:
- `start()`
- `stop()`
- `health()`
- `get_state()`

Every service should report or allow the runtime to derive:
- uptime
- health
- last heartbeat
- status message
- last error
- restart count
- consecutive failures

## Operator Surfaces

- Board widgets show compact lifecycle, freshness, mode, and issue state.
- The board Stats toggle expands freshness, uptime, mode, and restart count without making that rail permanent chrome.
- The System Panel shows aggregate runtime health, widget/service health, latest metrics, and timeline events.
- Runtime cadence, metric retention, and log view limits persist in system settings.
