# GremlinControl

GremlinControl is the local typed control plane for GremlinBoard operators, CLI users, and agents. It is a structured wrapper over the existing board, runtime, generation, job, and agent services.

It is not shell automation. It does not execute arbitrary commands, write directly to the database from clients, or bypass widget registry and generation review rules.

## Surfaces

- HTTP: `/api/control/actions/{action_id}`
- MCP-shaped tool catalog: `/api/control/mcp/tools`
- MCP-shaped tool call: `/api/control/mcp/call`
- CLI: `gb ...`

All surfaces use the same backend `ControlPlaneService` action registry.

## Actions

Initial actions:

- `widgets.list`
- `widgets.add`
- `widgets.remove`
- `widgets.restart`
- `widgets.pause`
- `widgets.resume`
- `widgets.resize`
- `widgets.configure`
- `board.snapshot`
- `runtime.status`
- `runtime.suspend`
- `runtime.resume`
- `jobs.list`
- `agents.list`

Widget actions use existing `RuntimeManager`, widget registry, plugin manager, config validation, and board repository paths. Job and agent reads use the current generation pipeline and agent registry.

## Approval Gates

Destructive actions return `approval_required` instead of executing. The first destructive action in this slice is `widgets.remove`.

Approval flow:

1. Call `/api/control/actions/widgets.remove`.
2. Receive a pending approval id.
3. Call `/api/control/approvals/{approval_id}/approve` or `/api/control/approvals/{approval_id}/reject`.
4. Approved actions execute through the same typed handler.

Approvals are process-local control requests. Domain state remains the source of truth.

## Events And Audit

Every action publishes typed `operator.control.*` runtime events with `correlation_id` and optional `causation_id`.

Completed actions and approval decisions are timeline events, so observability persists them in runtime logs. Devtools also shows them in the recent event stream.

## CLI Quickstart

```powershell
gb runtime status
gb widgets list
gb widgets add control_widget --size 2x2 --config-json "{\"provider\":\"local\"}"
gb widgets resize widget-1 4x2
gb widgets pause widget-1
gb widgets resume widget-1
gb widgets remove widget-1
gb approvals list
gb approvals approve approval-123 --note "operator approved"
gb jobs list
gb agents list
gb board snapshot
gb devtools
gb kill
gb_dev kill
gb kill --all
```

Kill scope follows the selected CLI mode:

- `gb kill` stops tray-managed stable instances only.
- `gb_dev kill` stops tray-managed dev instances only.
- `gb kill --all` or `gb_dev kill --all` stops every tray-managed stable and dev instance.

The global form uses the same `-StopAll` launcher path as `Stop-GremlinBoard.bat`. Mode-scoped kills preserve launcher records for the other mode.

Human-readable output uses operator-focused sections and tables. Use `--json` for scripts and agent integrations:

```powershell
gb --json runtime status
gb --json widgets list
gb --json agents list --status running
```

JSON mode prints the API response unchanged as machine-readable JSON.

## Migration Notes

`gb` is the preferred operator command. The longer `gremlinboard` entrypoint remains available.

When stable and development stacks are both open, use `gb` for the stable API and `gb_dev` for the development API:

```powershell
gb runtime status
gb_dev runtime status
gb_dev widgets list
```

`gb_dev` defaults to dev API port `2556`. Both short commands still accept `--mode stable` or `--mode dev` as an explicit override.

Use `-v` or `--version` to show both the GremlinBoard application version and the installed CLI version:

```text
GremlinBoard version: 0.1.0
gb CLI version: 0.1.0
```

The previous typed namespace remains fully supported:

```powershell
gremlinboard control runtime status
gremlinboard control widgets list
gremlinboard control approvals list
```

Earlier compatibility commands such as `gremlinboard status`, `gremlinboard runtime status`, `gremlinboard widgets refresh widget-1`, `gremlinboard start`, and `gremlinboard stop` also remain available.
