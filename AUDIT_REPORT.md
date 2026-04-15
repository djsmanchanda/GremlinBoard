# GremlinBoard Platform Integrity Audit

Date: 2026-04-14

## Scope

- Architecture integrity against AGENTS and skills contracts.
- Repository and worktree integrity.
- End-to-end validation coverage via automated tests and build checks.

## Validation Executed

- Backend tests: `python -m pytest apps/api/tests -q` -> 13 passed.
- Frontend typecheck: `npm run typecheck` -> passed.
- Frontend lint: `npm run lint` -> passed.
- Frontend production build: `npm run build` -> passed.
- Worktree check: single worktree on `main`.

## Architecture Integrity Findings

### 1. Registry-first design

Status: Pass

Evidence:
- Board widget creation validates registry and schema before persist/start.
- Plugin install/update/rollback routes route through plugin manager service.
- Runtime constructs widget services from manifest service target via registry.

### 2. Widget bypass of registry/plugin/runtime abstractions

Status: Mostly pass

Evidence:
- Widget instance lifecycle operations are routed through runtime manager.
- Plugin enabled check gates board add/start.

Concern:
- Frontend renderer map is static and build-time bound, which blocks true dynamic plugin renderer loading for newly installed/generated widgets.

### 3. Direct AI deploy bypass

Status: Pass for AI pipeline

Evidence:
- Generation jobs remain install-blocked until explicit approval.
- Install endpoint enforces approved status before plugin installation.

### 4. Provider abstraction

Status: Pass

Evidence:
- AI provider adapters implement shared interface and provider selection/fallback chain.
- External data providers follow shared base provider abstraction with retries/cache/fallback hooks.

### 5. Runtime lifecycle encapsulation

Status: Pass

Evidence:
- Runtime manager owns start/stop/restart/refresh, retry/backoff, stale cleanup, and heartbeat timeout handling.

## Repo/Worktree Integrity Findings

### Worktrees

- Single worktree remains; no active additional worktrees detected.

### Generated or misplaced files

- Issue found and fixed: tracked generated file `apps/web/tsconfig.tsbuildinfo`.
- Local generated caches found (`.next`, `__pycache__`, pytest cache); cleaned from working tree where present.

### Duplicate or stale definitions

Potentially stale/overlapping skills (kept intact for safety):
- `.skills/ui-layout-enforcer/SKILL.md` vs `.skills/grid-layout-enforcer/SKILL.md`
- `.skills/runtime-debugger/SKILL.md` vs `.skills/runtime-hardener/SKILL.md` + `.skills/runtime-orchestrator/SKILL.md`

## End-to-End Platform Validation Matrix

1. Widget creation/install/remove
- Widget creation/removal path validated by architecture inspection.
- Install/update/rollback validated in generation and plugin tests.
- Gap: no explicit API integration test that creates then removes a widget instance in one test flow.

2. AI generation pipeline
- Validated by `test_generation_pipeline_runs_review_gated_install_flow` and regeneration test.

3. Plugin rollback/versioning
- Version snapshot behavior validated by plugin repository and generation pipeline install/regeneration flow.
- Gap: no dedicated service-level rollback integration test asserting runtime restart side effects.

4. Runtime restart/failure handling
- Runtime manager implements retry/backoff and heartbeat timeout paths.
- Gap: no explicit automated test that forces service failure and asserts restart policy transitions.

5. Provider fallback behavior
- Validated by provider base tests for cache/fallback/degraded behavior.

## Code Smells

- Static frontend renderer registry limits dynamic plugin renderer extensibility.
- AI providers are deterministic placeholder adapters (healthy for architecture, but not production integrations yet).

## Technical Debt

- Missing integration tests for runtime failure/restart and board-level widget create/remove lifecycle.
- Skill set overlap could cause ambiguity in agent invocation behavior.

## Cleanup Recommendations

1. Replace static frontend renderer map with plugin/manifest-driven renderer loading contract for generated widgets.
2. Add integration tests for:
   - board widget create -> start -> remove lifecycle,
   - runtime failure -> retry/backoff -> terminal error,
   - plugin rollback triggering runtime restart path.
3. Consolidate overlapping skill files or document precedence rules.
4. Keep generated artifacts out of source control (already fixed for tsbuildinfo).

## Auto-Fixes Applied

- Removed tracked generated artifact: `apps/web/tsconfig.tsbuildinfo`.
- Cleaned local generated caches and Python bytecode directories from workspace.
