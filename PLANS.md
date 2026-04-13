# Execution Planning Document

## Goal

Build the GremlinBoard MVP as a modular widget board with:
- a strict fixed-size tile grid
- a spec-first widget contract
- a Python widget runtime with lifecycle and scheduling
- persistent board/widget state
- a maintainable Next.js + FastAPI architecture

## Subtasks

1. Define shared schemas, contracts, and repository structure.
2. Build the FastAPI backend:
   - registry loader
   - persistence
   - runtime lifecycle manager
   - scheduler
   - websocket updates
   - widget/spec APIs
3. Add built-in widgets:
   - countdown
   - news
   - sports
   - trending
   - pinboard
4. Build the Next.js board UI:
   - live board shell
   - drag/drop reordering
   - fixed-size resizing only
   - command palette
   - widget rendering
   - spec studio
5. Validate the implementation:
   - python compile/sanity
   - TypeScript lint/type/build when dependencies are available

## Files Impacted

- Root workspace/config files
- `apps/web/**`
- `apps/api/**`
- `widgets/**`
- `schemas/**`
- `README.md`

## Risks

- Greenfield build across frontend and backend in one pass
- Dependency installation may require network approval
- Live third-party content providers need graceful fallback behavior without API credentials
- Grid constraints must remain strict even as widget capabilities vary

## Validation Steps

1. Validate widget manifests against the strict registry rules.
2. Compile Python modules.
3. Run frontend lint/typecheck/build after dependency install.
4. Sanity check websocket/runtime flow with seeded widgets.
