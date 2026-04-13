---
name: ai-tooling-orchestrator
description: Use when wiring Codex or Claude Code CLI into GremlinBoard.
---

Handle AI-driven widget creation through a safe pipeline.

Steps:
1. draft spec
2. validate
3. scaffold
4. generate code
5. review
6. install

Rules:
- no direct deploy from raw model output
- keep provider adapters abstract
- support multiple AI backends
- keep generated artifacts versioned
