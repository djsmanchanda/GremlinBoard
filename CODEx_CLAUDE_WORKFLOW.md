# AI Build Workflow

GremlinBoard uses AI in a controlled pipeline.

## Pipeline

idea -> spec -> validation -> scaffold -> codegen -> review -> install

## Rules

- AI may propose code, but cannot directly deploy.
- Every generated widget must match the manifest schema.
- Every generated service must pass validation.
- Every installation must be reversible.

## Tooling

- Codex: code generation and refactors
- Claude Code CLI: alternative generation and cleanup
- Spec Widget: user-facing entry point for new widgets

## Required Output

When generating a widget, AI must produce:
- manifest
- backend service
- renderer
- config schema
- test skeleton
- install notes
