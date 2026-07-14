# AI Generation System

AI generation flow:

idea
→ spec draft
→ validation
→ scaffold
→ codegen
→ review
→ install

No AI-generated code may directly deploy.

All providers implement:

generateSpec()
generateCode()
reviewCode()

Spec Studio provider selection is catalog-driven. The backend exposes each provider's available model IDs through `/api/ai/providers`, including richer `model_options` metadata when available:

- model label
- intelligence or reasoning effort choices
- speed/latency level
- catalog source (`provider_api` when discovered live, `fallback` when using maintained defaults)

Providers should discover live model availability from the provider API when local credentials are configured, then fall back to documented defaults so Spec Studio remains usable offline.

## Execution backends

Each generation job records `generation_mode`: `"live"` | `"cli"` | `"offline"`.

- `live` — HTTP API call using a configured API key.
- `cli` — run through a local agent CLI (Claude Code or Codex CLI) using the operator's subscription login. Real AI, not a fallback.
- `offline` — deterministic template fallback, no AI. Spec Studio flags this clearly to the reviewer.

Resolution order: api key → CLI → offline. Override with `GREMLINBOARD_AI_BACKEND=auto|api|cli|offline`.

CLI binaries are auto-detected on `PATH` (`claude`, `codex`) and can be overridden with `GREMLINBOARD_CLAUDE_CLI` / `GREMLINBOARD_CODEX_CLI`. CLI mode needs no API key — it rides on the operator's existing Claude Code / Codex CLI login.
