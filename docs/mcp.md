# GremlinBoard MCP

GremlinBoard exposes a local Streamable HTTP MCP endpoint at `http://127.0.0.1:2555/mcp/`. It is mounted inside the API process and is intended for local operator clients such as OpenClaw.

## Authentication

MCP is disabled until the existing System credentials store contains a credential with provider `mcp`. Its secret value is the bearer token for every MCP request. Configure it through the normal system credentials UI or API; do not put the token in an MCP client configuration checked into source control.

```powershell
Invoke-RestMethod -Method Put http://127.0.0.1:2555/api/system/credentials `
  -ContentType application/json `
  -Body '{"provider":"mcp","label":"local MCP token","value":"replace-with-a-secret"}'
```

Clients must send `Authorization: Bearer <token>`. Missing or invalid credentials receive `401`; an endpoint without an `mcp` credential receives `503`.

## Tools

The `gremlinboard_*` tools mirror `/api/control/mcp/tools` and call the same `ControlPlaneService` actions. Destructive control actions return an approval object; use `approvals.approve` with its id to execute the pending action.

Generation tools are deliberately separate and retain the existing pipeline gates:

- `widgets.generate`: creates an idea-based generation job.
- `jobs.status`: reads a generation job.
- `generation.preview`: returns the job and its test-box payload.
- `generation.approve`: approves only a completed job with no critical review or dry-run blockers.
- `generation.install`: installs only a review-approved job.

No MCP tool directly writes widget packages, skips review, or bypasses the widget registry.

## OpenClaw Connection

Configure an HTTP MCP server using the endpoint and bearer token held in your secret manager:

```json
{
  "mcpServers": {
    "gremlinboard": {
      "url": "http://127.0.0.1:2555/mcp/",
      "headers": {
        "Authorization": "Bearer ${GREMLINBOARD_MCP_TOKEN}"
      }
    }
  }
}
```

Run `scripts/smoke-mcp.ps1` from the repository root to start an isolated local API, verify discovery and review-gated installation, then remove its temporary database and widgets directory.