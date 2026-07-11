# GremlinBoard Overhaul Plan

Last updated: 2026-07-08
Status: proposed, pre-implementation
Role model: this document is the orchestration reference. The orchestrator (Claude) dispatches work packets to Sonnet 5 and Codex GPT-5.5 subagents, reviews real diffs, and runs the validation gates itself before committing.

## Diagnosis (what the audit found)

Three parallel deep audits (generation backend, Spec Studio frontend, board UI) converged on five root problems:

1. **There is no actual AI in the "AI generation" pipeline.** Both providers (`apps/api/gremlinboard_api/ai/providers.py`) are deterministic placeholder shells. `draft_spec` is regex keyword matching; `prepare_codegen` builds a prompt string that is never sent anywhere; `review_package` always returns `issues: []`. All widget code comes from hardcoded string templates in `services/scaffold_generator.py` — every generated widget is the same card with `sample_1..sample_N` literals. `renderer_type` (chart/table/list) is accepted by the spec and feedback flow but ignored by the template. The only real network calls are model-catalog GETs.

2. **Generated renderers cannot load in production.** `apps/web/components/board/renderers.tsx:78-80` uses a webpack template-literal `import()` over `widgets/*/renderer`. The context is frozen at build time; a renderer installed after `next build` (the standalone launcher path) falls back to "Renderer unavailable". Generation only appears to work under `next dev`. This is the hard architectural blocker for the whole product story.

3. **Spec Studio is two workflows glued onto one page.** ~14 bordered panels, an easy path and an advanced path with duplicated provider/model/effort selects, a decorative 6-stage tracker plus a 4-step hero explainer plus "Step 2/3/4" panel labels (three competing mental models), hidden side effects (size tile rewrites the feedback box; easy-gen mutates the submitted idea), a 1.2s polling loop, and a "preview" that never renders the widget — only JSON dumps.

4. **Widget chrome is card-inside-card, systemically.** `widget-card.tsx` frames content twice (outer card `:112` + inner renderer panel `:214`); built-in renderers add their own bordered sub-panels, reaching 3-5 concentric borders (worst: agent_overview). Small tiles lose most of their area to chrome (lifecycle dot, category eyebrow, bordered size chip, title, optional 4-pill stats rail, source callout). Controls are triplicated (card icons, inspector footer, settings panel); alert state appears in four places.

5. **The design system is disconnected.** `:root` CSS tokens and the ember/steel themes don't drive board colors — components hardcode hex (`#0a0d11`, `#05070a`, ...) and ad-hoc `white/[0.0x]` opacities. Radius is chaos: `rounded-none` board vs `rounded-[14..24px]` panels vs `rounded-full` chips, often inside one component. `.glass-panel*`/`.text-gradient` are neutered but still referenced. System Panel and board don't feel like one product.

Secondary findings: in-memory generation queue loses jobs on restart; import validation is a shallow denylist (blocks `os`/`subprocess` but not `httpx`/`eval`) while generated backends run in-process with full app privileges; feedback categories are cosmetic (mutation is independent keyword scans); all widget services are in-process async Python with zero out-of-process or Rust support; the MCP-shaped control plane exists (`/api/control/mcp/*`) but is HTTP-only, not a real MCP server.

## Strategy

The single most important architectural decision: **generated widgets should target a declarative renderer contract, not free-form TSX.**

- It kills the production rebuild problem: a universal renderer (built once, shipped with the app) renders any widget from a JSON "view blueprint" — no webpack context, no rebuild, installs work in standalone mode.
- It makes generated widgets look good by construction: blueprints compose vetted, design-system-native primitives (stat, list, table, sparkline, progress, timer, badge-row, key-value grid), so the LLM cannot produce off-system styling, nested card junk, or broken Tailwind.
- It shrinks the LLM task: the model designs data + layout, not React internals — smaller prompts, fewer failure modes, cheaper review.
- It shrinks the security surface: no generated JS executes in the board at all. Only the generated Python backend needs sandboxing attention.

Free-form TSX remains for built-in/hand-authored widgets, and later as an "advanced" escape hatch (install-time esbuild transpile into a sandboxed iframe) if blueprints prove too limiting. Do not build the escape hatch first.

Second decision: **make generation real and conversational.** One flow: describe → agent drafts spec + blueprint + backend (real LLM calls, streamed) → live preview rendered with sample data by the actual universal renderer → refine in free-form chat (spec-diff based, not four keyword buckets) → review (real LLM review + static checks) → install. One screen, one path.

Third decision: **widget services become a contract, not a base class.** Keep `BaseWidgetService` for in-process Python, add a `ProcessWidgetService` adapter that speaks JSON-RPC over stdio to any child process. Rust (or anything else) implements `start/stop/health/get_state/refresh` as JSON-RPC methods. Manifest gains `service.kind: "python" | "process"` and, for process, an executable target managed per-widget. This is how Rust microservices arrive without touching the runtime manager's semantics.

Fourth decision: **the MCP surface becomes a real MCP server** exposed by the API (streamable HTTP), reusing `ControlPlaneService` actions plus new `widgets.generate` / `widgets.preview` / `jobs.status` tools, so OpenClaw (or any MCP client) can spawn widgets on demand through the same staged, review-gated pipeline.

## Phases

Ordering rationale: Phase 1 (design system) is independent and derisks everything visual. Phase 2 (blueprint renderer) must land before Phase 3 (real AI) because the prompts target the blueprint contract. Phase 4 (Studio rebuild) consumes 2+3. Phases 5 (process runtime) and 6 (MCP) are independent of 3/4 and can run in parallel lanes.

---

### Phase 1 — Design system and chrome slim-down

Goal: one visual system, half the chrome, no functional changes to grid mechanics.

Packets:

**P1.1 Token foundation** (`apps/web/app/globals.css`, new `apps/web/lib/design-tokens.ts` if needed)
- Wire the board to `:root` tokens: replace hardcoded hex backgrounds/borders in board components with `var(--...)`-backed Tailwind theme values (Tailwind v4 `@theme`).
- Define scales: surface levels (bg / surface / surface-raised / surface-inset), border (one default + one strong), radius (a 3-step scale — pick sharp-with-small-radius, e.g. 0 / 6px / 10px — applied everywhere), status colors (critical/alert/completed/accent).
- Delete dead vocabulary: `.glass-panel*`, `.premium-ring`, `.accent-border`, `.text-gradient` and their usages.
- Make ember/steel themes actually restyle the board; keep dark-only for now.

**P1.2 Widget chrome rework** (`components/board/widget-card.tsx`)
- Remove the inner renderer frame (`:214`) — content sits directly in the card with one padding. One border per widget, total.
- Header collapses to: lifecycle dot + title (+ alert callout when present). Category eyebrow and size chip appear only in Edit mode or on hover.
- Stats rail becomes a single-line text row (no bordered pills) under the Stats toggle; Source callout folds into the same row.
- Keep the alert band, drag band, and resize handle as-is (product contract).

**P1.3 Renderer de-carding pass** (`widgets/*/renderer.tsx` for the six built-ins)
- Remove per-item borders where a divider or spacing suffices; normalize to the token scale; kill sports' duplicate internal header; remove agent_overview's `min-h-[520px]` and its counter-box grid in favor of inline stats.
- Target: max two bordered surfaces visible in any tile (card + at most one functional inset like a composer).

**P1.4 Board shell and toolbar** (`board-shell.tsx`, `board-grid.tsx`)
- Remove the decorative header badges and the 3-up SummaryCard row; the board starts at the toolbar.
- Merge the alert summary strip into the toolbar badge (one alert surface outside cards).
- De-duplicate controls: card icon cluster stays in Edit mode; inspector keeps settings but drops the duplicate Refresh/Pause/Remove footer.
- Normalize System Panel radii/tokens to the same scale (mechanical pass, no layout redesign yet).

Gate: `npm run typecheck && npm run lint && npm run build`, Playwright smoke at all four viewports, manual View/Edit/drag/resize sanity. No grid geometry changes allowed.

---

### Phase 2 — Blueprint renderer runtime (unblocks production installs)

Goal: a widget can be installed and render in the standalone production build with zero rebuild.

**P2.1 Blueprint schema** (`schemas/`, `apps/api/gremlinboard_api/schemas/`)
- JSON Schema + Pydantic model for `view.blueprint.json`: a small tree of layout nodes (stack/row/grid/scroll) and primitive nodes (stat, text, badge, list, table, key-value, progress, sparkline/mini-chart, timer, empty-state), each binding to paths in the service's `get_state()` output, with per-size-tier variants (`1x1` vs `4x2` layouts) and simple conditionals (show-if, thresholds → status colors).
- Versioned (`blueprint_version`), strictly validated at install time.

**P2.2 Universal renderer** (`apps/web/components/board/blueprint-renderer.tsx` + primitive components)
- One component, shipped with the app, renders any valid blueprint against `widget.state`. Primitives are design-system-native (Phase 1 tokens), density/tier-aware, with graceful fallbacks for missing data paths.
- `renderers.tsx`: manifests with `renderer.kind: "blueprint"` route to it; `renderer.kind: "module"` keeps the existing dynamic import for built-ins. Registry/loader validates the new manifest shape.

**P2.3 Pipeline + registry integration** (`scaffold_generator.py`, `plugin_manager.py`, `registry/loader.py`)
- Generated packages become: `manifest.json`, `config.schema.json`, `backend.py`, `view.blueprint.json` (no more generated `renderer.tsx`). Install validates blueprint against schema. Board delivers blueprint to the client via the snapshot/manifest payload.
- Migration: existing template scaffolder emits an equivalent default blueprint so the pipeline keeps working before Phase 3 lands.

Gate: install a generated widget against a **production** build (`npm run build && start`) and see it render; backend pytest; registry validation; smoke tests.

---

### Phase 3 — Real AI generation

Goal: real model calls end to end, producing genuinely functional widgets (real data fetching in `backend.py`, real blueprint design), with real review.

**P3.1 Provider inference layer** (`apps/api/gremlinboard_api/ai/`)
- Implement actual Anthropic Messages API and OpenAI Responses API clients (httpx, async, streaming) behind the existing `AIProvider` interface; keyed from the existing secrets store; per-stage model selection honoring reasoning-effort options. Deterministic shell mode remains as explicit offline fallback (`mode: "offline"` surfaced in UI, never silently).
- Structured outputs: spec and blueprint via tool-use/JSON-schema-constrained calls; backend code as a fenced artifact; retries with validation-error feedback loops (send schema violations back to the model, max 2 repair rounds).

**P3.2 Prompt system** (`apps/api/gremlinboard_api/ai/prompts.py` → proper prompt pack)
Replace the three one-line templates with real system prompts, one per stage:
- **Spec prompt**: full widget contract (sizes, refresh/lifecycle/runtime policy semantics, permissions), the board's monitoring-station language, category guidance, and instructions to ask the data-availability question first (what API/source will feed this widget) so specs stop defaulting to `custom`/`sample`.
- **Backend prompt**: `BaseWidgetService` contract with a worked example (the news widget), efficiency rules from RUNTIME.md (cache TTLs, conservative intervals, no 1s loops, graceful degradation, stale fallback), allowed-import allowlist, config-schema conventions, and the rule that `get_state()` output must exactly match the blueprint's data bindings.
- **Blueprint prompt**: the primitive catalog with visual guidance (density-first, no decorative filler, per-tier layouts, threshold coloring), 2-3 few-shot examples of excellent blueprints (a stat widget, a list widget, a chart widget).
- **Review prompt**: actual rubric — contract compliance, data-binding mismatches, unsafe patterns, refresh-policy sanity — returning structured issues with severity; pipeline blocks approval on `critical` issues instead of always returning empty.
- Prompts live as versioned files, unit-tested for rendering, and logged into job artifacts (already the artifact shape — now they're real).

**P3.3 Pipeline upgrades** (`services/generation_pipeline.py`)
- Persist queued inputs (new table or extend generation_jobs) so restarts resume instead of failing jobs.
- Replace the four keyword feedback buckets with spec-diff refinement: feedback text + current spec + current blueprint go to the model, which returns a patched spec/blueprint; the diff is stored and shown. Categories become tags derived from the diff, not routers.
- Stage-level progress events published on the event bus (`generation` category) for streaming UI.
- Static gate additions: allowlist-based import validation for generated backends (replace denylist: permit a curated stdlib subset + `httpx` + repo runtime modules), AST checks for `eval`/`exec`/dunder tricks, blueprint schema validation, and a dry-run `get_state()` execution in a restricted subprocess with timeout before review.

Gate: end-to-end generation with a live key produces an installable widget that fetches real data (e.g., "a widget showing current Hacker News top 5") and renders correctly at two sizes; pytest including new pipeline tests; offline mode still passes CI without keys.

---

### Phase 4 — Spec Studio rebuild

Goal: one guided flow, one screen, live preview, streaming. Target: idea → installed widget in 3 interactions.

**P4.1 New studio layout** (`apps/web/components/studio/`)
- Split the 1,684-line component. Two-pane layout: left = conversation/controls (idea input, provider+model as one compact popover, chat-style refinement thread, review verdict, Approve/Install), right = **live preview** rendering the actual blueprint via the Phase 2 universal renderer against sample state, with size-tier switcher (render it at 2x2 / 4x2 / ...), plus collapsible tabs for spec/manifest/backend code/diff.
- Delete: the duplicate advanced generation path (raw spec editing becomes an "edit spec JSON" affordance inside the same flow), the 6-card workflow tracker and hero 4-step strip (replaced by a single slim progress line during generation), the duplicated provider selects, the standalone size card (size becomes a chip row on the idea input, no feedback-box side effects), the separate install-readiness panel (folds into review).
- Explicit gating copy: when Approve/Install is disabled, say exactly why.

**P4.2 Streaming job status** (`lib/api.ts`, studio, `apps/api` routes)
- Replace 1.2s polling with the existing websocket event stream (`generation` events from P3.3) or SSE from the job endpoint; show per-stage progress and streamed review findings.
- Lazy-load the studio route (`next/dynamic`) so board startup cost is unaffected.

Gate: typecheck/lint/build, new Playwright smoke for the happy path (idea → preview → approve → install against offline provider), manual UX pass.

---

### Phase 5 — Polyglot microservices (Rust)

Goal: a widget service can be an out-of-process binary; first-class Rust template.

**P5.1 Process service adapter** (`apps/api/gremlinboard_api/runtime/`)
- `ProcessWidgetService(BaseWidgetService)`: spawns the child (per manifest `service.command` under the widget dir), speaks newline-delimited JSON-RPC over stdio (`start/stop/health/get_state/refresh/set_config`), enforces timeouts, restarts via existing backoff policy, kills the process tree on cleanup and API shutdown.
- Manifest schema: `service.kind: "python" | "process"`; registry validates process manifests (no arbitrary paths — executable must live inside the widget package dir). Runtime logs capture child stderr.

**P5.2 Rust widget kit** (`widgets/_kits/rust/` or a new `kits/` dir)
- A small Rust crate template implementing the JSON-RPC contract (serde + tokio, one file of protocol glue), plus one real example widget (e.g., a system-stats widget: CPU/mem — a genuinely useful case for Rust) with manifest, blueprint, config schema, and a build script that drops the binary into the widget package.
- Docs: `WIDGET_SPEC.md` + `RUNTIME.md` updates for the process contract.
- Note: AI generation of Rust widgets is explicitly out of scope for this phase (needs a toolchain + compile step in the pipeline); generated widgets stay Python. Revisit after Phase 3 stabilizes.

Gate: runtime integration tests covering process lifecycle, crash/restart, stale-heartbeat cleanup, and shutdown leaving no orphan processes (Windows-verified); example widget runs on the board.

---

### Phase 6 — Real MCP server (OpenClaw integration)

Goal: any MCP client can operate the board and request widget generation through the staged pipeline.

**P6.1 MCP server** (`apps/api/gremlinboard_api/services/` + route)
- Mount a streamable-HTTP MCP endpoint (official `mcp` Python SDK) on the FastAPI app, translating tools 1:1 from `ControlPlaneService` (the catalog already exists at `/api/control/mcp/tools`), preserving approval gates: destructive tools return the approval id and an `approvals.approve` tool completes them.
- New tools: `widgets.generate` (idea → job id), `jobs.status`, `generation.preview` (returns the test-box payload), `generation.approve`/`install` (gated the same as the UI). Generation stays review-gated — MCP clients cannot bypass staging; optionally a system setting allows auto-approve for trusted clients, default off.
- Local-only binding + token auth from the existing credentials store.

**P6.2 OpenClaw wiring + docs**
- Connection doc and a smoke script proving: OpenClaw asks for "a countdown to Friday 6pm" → widget appears on the board after approval.

Gate: MCP contract tests (tool list, call, approval round-trip), control-plane pytest suite, manual OpenClaw session.

---

## Orchestration plan

Lane assignment (subagents; orchestrator reviews diffs and runs all gates itself):

| Packet | Agent | Why |
|---|---|---|
| P1.1–P1.4 | Sonnet 5 (one packet at a time; P1.2/P1.3 can parallelize after P1.1) | Design-sensitive frontend; benefits from taste + the grid product contract |
| P2.1, P2.3 | Codex GPT-5.5 | Schema/pipeline plumbing, well-specified |
| P2.2 | Sonnet 5 | The universal renderer is the new visual heart |
| P3.1, P3.3 | Codex GPT-5.5 | Async API clients + pipeline mechanics |
| P3.2 | Orchestrator + Sonnet 5 | Prompt quality is the product; iterate with real runs |
| P4.1 | Sonnet 5 | Large UX rebuild |
| P4.2 | Codex GPT-5.5 | Transport plumbing |
| P5.1–P5.2 | Codex GPT-5.5 | Systems/protocol work |
| P6.1–P6.2 | Codex GPT-5.5, Sonnet 5 review | Contract translation over existing service |

Rules of engagement (per repo owner's Codex discipline):
- Every packet ships with ALLOWED/FORBIDDEN files, exact spec, acceptance checklist; agents return `git status --short` + per-file summary; **no agent commits**.
- Never trust relayed summaries; review the working-tree diff. Codex validation claims are re-verified locally (its sandbox can't spawn vite/node/pytest reliably on Windows).
- Poll Codex jobs via `codex-companion.mjs status --json` at ≥2-minute intervals; if a job looks frozen, check `git status` — work often completes while the job record hangs.
- Orchestrator runs the full gate before each commit: `npm run typecheck && npm run lint && npm run build`, backend pytest (`-p no:langsmith`, Python 3.12 micromamba env), registry validation, Playwright smoke for board-touching phases.
- One phase per branch/commit series; board grid geometry (drag/resize/packing/sizes) is frozen — any packet touching `board-grid.tsx` must not alter interaction semantics.

Suggested sequence: **P1 → P2 → P3 → P4**, with **P5** startable in parallel any time after P1, and **P6** any time after P3.3 (needs `widgets.generate` semantics settled). P2 is the critical path — nothing about "agents create widgets for users" is real until installed widgets render in production.

## Risks

- **Blueprint expressiveness**: some widget ideas won't fit the primitive set. Mitigation: design primitives from the six built-ins (they must be re-expressible), keep the TSX escape hatch as a documented later option, and let the spec prompt say "not expressible as a blueprint" honestly instead of producing junk.
- **In-process generated Python remains the biggest trust hole** even with an allowlist. The subprocess dry-run gate (P3.3) helps; true isolation would mean running generated backends via the P5 process adapter — note this as the follow-on hardening once both exist.
- **Provider cost/latency**: generation becomes real money; keep per-job token accounting in artifacts and surface it in the studio.
- **Windows-specific process management** (P5): job objects / process-tree kill need explicit testing; the launcher already has patterns to borrow.
- **Scope creep in P1**: the visual pass must not become a redesign of grid mechanics; the smoke suite at four viewports is the tripwire.
