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

RuntimeManager also protects the app's background footprint:
- monitor cadence is clamped to a control-panel-friendly lower bound
- snapshot serialization is skipped when there are no websocket subscribers
- subscriber queues are bounded and drop the oldest pending event under backpressure
- monitor-loop exceptions are logged without terminating the monitor task
- timezone-naive persisted datetimes are normalized before expiry or stale comparisons

## Failure Policy

- Each widget manifest may define runtime policy values such as timeouts, max retries, retry backoff, and stale-after seconds.
- Failed refresh/start/stop calls are recorded as runtime logs.
- A widget enters `error` after the retry policy is exhausted.
- Widget status uses three visible categories: red `critical` for broken behavior, yellow `alert` for non-fatal issues, and green `completed` only for explicitly reported successful task completion.
- Services that need a completion badge should publish `state.complete = true`. Ordinary healthy widgets remain unbadged.

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

## Process Services

Process services are adapter-managed widget services.

Rules:

- The manifest declares `service.kind: "process"` and `service.command` as argv.
- The registry accepts only in-package process executables.
- The runtime spawns the process with the widget package as `cwd`.
- Communication is newline-delimited JSON-RPC 2.0 over stdin/stdout.
- Supported methods are `start`, `stop`, `health`, `get_state`, `refresh`, and `set_config`.
- Calls are serialized per process.
- `start_timeout_seconds` bounds spawn and `start`.
- `refresh_timeout_seconds` bounds `health`, `get_state`, `refresh`, and `set_config`.
- Stop uses a short bounded stop call, then runtime cleanup terminates the process if it is still alive.
- Child stderr is captured into runtime logs.
- Child stdout must contain only JSON-RPC response lines.
- A malformed response, timeout, EOF, or process exit is a runtime failure.
- A stopped, removed, crashed, or shutdown widget must not leave an orphan process.

## Operator Surfaces

- Board widgets show compact lifecycle, freshness, mode, and issue state.
- The board Stats toggle expands freshness, uptime, mode, and restart count without making that rail permanent chrome.
- The System Panel shows aggregate runtime health, widget/service health, latest metrics, and timeline events.
- Runtime cadence, metric retention, and log view limits persist in system settings.
- GremlinControl exposes typed local control actions for CLI and agent users: inspect, add, remove, restart, pause, resume, resize, configure widgets, inspect board/runtime/job/agent state, and suspend/resume runtime.
- Destructive GremlinControl actions require approval before execution and emit auditable operator events.

## Efficiency Rules

- Do not create one-second backend refresh loops for widgets that only need visual countdown or local display ticks.
- Prefer renderer-local ticking for countdowns and similarly deterministic UI-only state.
- Data-backed widgets should use cache TTLs and conservative default intervals; manual refresh is the escape hatch for immediate operator action.
- Observability polling should pause while the System Panel tab is hidden.
- Runtime metrics retention should trim bounded windows, not scan the whole historical table during every cadence.
- Avoid committing generated development logs. `*.log` is ignored at the repo root.

## Local Run Modes

- Development mode: `npm run dev:api` and `npm run dev:web`. Use this while changing code; CPU cost from reloaders and compilers is expected.
- Utility mode: `npm run start:api` plus `npm run build && npm run start:web`. Use this when evaluating the app as a lightweight local control panel.
- API start helpers in `scripts/start-api.ps1` and `scripts/start-api.sh` run without reload and without access logs.
- Windows tray utility mode: `Start-GremlinBoard.bat` starts the production API/web pair and keeps a tray icon for open/stop actions.
- Windows tray autostart: `Install-GremlinBoard-Autostart.bat` installs a current-user Startup shortcut for the stable tray launcher. It starts after Windows sign-in, not as a pre-login service.
- Windows tray port allocation: stable web/API use `7555`/`2555`; dev web/API use `7556`/`2556`.
- Windows tray dev mode: `Start-GremlinBoard-Dev.bat` starts the reload-enabled API/web pair on ports `7556`/`2556`.
- The launcher checks selected ports before starting. If a port is already used by a process the launcher does not manage, startup fails instead of silently binding to the wrong stack.
- Managed launcher state is stored in `instances.json` under the platform user-data directory's `launcher/` subfolder (`%LOCALAPPDATA%\GremlinBoard\launcher` by default on Windows, or `GREMLINBOARD_DATA_DIR\launcher` when that env var is set); it is runtime state, not source. The launcher cleans stale entries and allows at most two managed stacks so repeated starts do not silently stack background CPU work. On first run, a legacy `data\launcher\instances.json` in the repo is copied once into the new location.
- Use `Stop-GremlinBoard.bat` or the tray menu's `Stop Services and Exit` action to close managed child processes.

## Lightweight Utility Direction

The control-panel posture should continue moving toward:

- production web serving for normal use, with Next dev mode only for code changes
- no reload watchers in utility mode
- bounded logs, metrics, websocket queues, and event history
- refresh only while there is an operator or an explicit background need
- widget-level cache TTLs and manual refresh over aggressive polling
- route-level lazy loading for System Panel and Spec Studio surfaces
- renderer-local timers for visual-only state
- a visible process owner, currently the Windows tray launcher, so background services are easy to find and stop
- tray-visible health state, including API/web liveness and last startup error, without opening the browser
