"""GremlinBoard AI prompt pack.

This module is the single source of truth for every prompt sent to a model during
staged widget generation (spec -> blueprint -> backend -> review, plus repair
rounds). Prompts are versioned (`PROMPT_PACK_VERSION`) and kept as module-level
string/dict constants so they are diffable, testable, and reusable across
providers. `apps/api/gremlinboard_api/ai/clients.py` (owned by a concurrent
packet) calls the functions below by name; do not rename or reshape the public
function signatures without updating that packet too.

Public API:
    spec_system_prompt() / spec_user_prompt(*, idea) / spec_output_schema()
    blueprint_system_prompt() / blueprint_user_prompt(*, spec)
    backend_system_prompt() / backend_user_prompt(*, spec, blueprint)
    review_system_prompt() / review_user_prompt(*, spec, package) / review_output_schema()
    repair_user_prompt(*, stage, errors)

Legacy wrappers (`render_idea_to_spec_prompt`, `render_codegen_prompt`,
`render_review_prompt`) are kept only because `ai/providers.py` still imports
them; they are thin, deprecated shims over the new prompt pack.
"""

from __future__ import annotations

import json
from typing import Any


PROMPT_PACK_VERSION = "2"

# ---------------------------------------------------------------------------
# Shared contract vocabulary
# ---------------------------------------------------------------------------

ALLOWED_SIZES: tuple[str, ...] = ("1x1", "1x2", "2x2", "4x2", "2x4", "4x4")

WIDGET_PERMISSIONS: tuple[str, ...] = (
    "network",
    "storage",
    "credentials",
    "long_running",
    "realtime_stream",
    "passive_widget",
)

REFRESH_MODES: tuple[str, ...] = ("manual", "interval", "live")

STATUS_COLORS: tuple[str, ...] = ("critical", "warn", "ok", "neutral")

MONITORING_STATION_LANGUAGE = """
GremlinBoard is a local monitoring station, not a marketing dashboard. Every widget
must read as compact, observable, and dense:
- One clear job per widget. No decorative filler, no restating the widget title inside
  the body, no invented "insights" the data does not support.
- Numbers and status first. Prose is a last resort, never the primary payload.
- Descriptions use plain, technical, monitoring-station language: what it watches, at
  what size, from what source. Example tone: "Dense live sports monitor for IPL scores
  and match state." Avoid marketing adjectives ("amazing", "powerful", "seamless").
- The board is normally in View mode: nothing about the widget's design should assume
  hover affordances or click-to-reveal as the *only* way to see the primary value.
""".strip()

SIZE_CONTRACT = f"""
Allowed tile sizes are fixed and exhaustive: {", ".join(ALLOWED_SIZES)}. Never invent a
size outside this set.
- `min_size` is the smallest size the widget still functions at (data still legible).
- `preferred_size` is the size that best expresses the widget's primary value.
- Both `min_size` and `preferred_size` MUST be members of the widget's `allowed_sizes`
  once it reaches manifest stage; at spec stage, choose them from the allowed set above
  directly (there is no `allowed_sizes` field on the spec itself).
- Prefer the smallest `preferred_size` that does not starve the data. A single number
  (uptime, countdown) wants `1x1` or `1x2`. A feed or table wants `2x2` or `4x2`. Only
  reach for `2x4`/`4x4` when the content genuinely needs the extra rows (long feeds,
  multi-metric dashboards) — do not default to the largest size out of caution.
""".strip()

REFRESH_POLICY_CONTRACT = """
`refresh_policy` has two fields: `mode` (one of "manual", "interval", "live") and
`interval_seconds` (integer, >= 0).
- `manual`: the widget only updates when the operator hits refresh. Use this for
  static/local content (pinboard-style notes, one-shot lookups) where polling would be
  wasted work. `interval_seconds` may be 0.
- `interval`: the widget polls on a cache-friendly cadence. This is the default choice
  for anything backed by an external API or feed. Pick conservative intervals — think
  in minutes, not seconds, unless the source data genuinely changes second-to-second.
  Reasonable defaults: 60-120s for something that changes often but is not truly live,
  300-600s (5-10 min) for news/RSS/trending feeds, 900s+ for slow-moving data (e.g.
  daily stats). Never propose sub-60-second polling for `interval` mode.
- `live`: reserved for genuinely live sources (an in-progress sports match, a streaming
  metric) where the operator needs near-real-time state. Even `live` should stay
  conservative — 10-30s is normally enough; do not propose 1-second loops. `live` mode
  must be paired with `source_type: "api"` (or another real, polling-capable source),
  never with static/local data.
- Whichever mode you choose, the backend implementation is expected to cache upstream
  responses and serve stale-but-labelled data over hammering the source. Manual refresh
  is always the escape hatch for "give me it right now."
""".strip()

PERMISSIONS_CONTRACT = f"""
`permissions` is a list drawn only from: {", ".join(WIDGET_PERMISSIONS)}.
- `network`: the backend makes outbound HTTP calls (any external API, RSS/Atom feed,
  scrape target). Required whenever `source_type` implies a remote source.
- `storage`: the backend persists local state across restarts beyond the in-memory
  `self.state` (e.g. a notes/pinboard widget writing to local files/DB).
- `credentials`: the backend reads a stored API key/secret via the provider registry.
- `long_running`: the backend keeps a connection or background task alive between
  refresh calls (e.g. a websocket subscription) rather than doing simple poll/response.
- `realtime_stream`: the backend pushes updates outside the normal refresh cadence.
- `passive_widget`: the widget has no external dependencies at all (pure local/derived
  state, e.g. a countdown timer). Use this instead of an empty permissions list so the
  intent is explicit.
Only request permissions the backend actually needs — this list is a security
boundary, not a wish list.
""".strip()

CATEGORY_CONTRACT = """
`category` is a short, lower-case, snake_case label describing the widget's domain
(examples already in use: "sports", "news", "trending", "notes", "agent",
"monitoring"). Reuse an existing category when the widget is clearly the same kind of
thing; otherwise introduce a new, equally specific category. Never use `category:
"custom"` or `category: "misc"` — those are not observable groupings and defeat the
board's category conventions.
""".strip()

DATA_SOURCE_CONTRACT = """
Every spec must name a CONCRETE data source, not a placeholder. Before writing the
spec, decide: what public API, RSS/Atom feed, scrape target, or purely local
computation will actually back this widget? Say so explicitly:
- `source_type` should be one of a small honest set: "api" (a real named API, e.g.
  "GitHub REST API", "Open-Meteo", "Hacker News Firebase API"), "feed" (RSS/Atom),
  "scrape" (HTML scrape of a named page — last resort, flag it), or "local" (pure
  local/derived state with no network calls, e.g. countdown timers, notes).
- The spec `description` must name the concrete source ("Polls the Hacker News
  Firebase API for the top 5 stories by score") — never "sample data", "placeholder
  API", or "TBD". If you genuinely cannot identify a real source for the idea, say so
  plainly in the spec description and choose `source_type: "local"` with a defensible
  local computation instead of inventing a fake API.
- Do not propose scraping a page that clearly requires auth, JS rendering, or violates
  robots.txt-style expectations for a local hobby tool; prefer a documented public API
  or feed.
- Refusing vague/sample data specs is mandatory: an idea like "show some cool stats" is
  not acceptable as-is — ask the user to sharpen it in the description, or make the
  most concrete, defensible interpretation and state that interpretation explicitly.
""".strip()

# ---------------------------------------------------------------------------
# 1. Spec prompts
# ---------------------------------------------------------------------------

SPEC_SYSTEM_PROMPT = f"""
You are the GremlinBoard spec drafting agent. GremlinBoard is a local-first live
monitoring board; every widget you draft a spec for is a small, dense, observable tile
on that board. Your job in this stage is to turn a one-line idea into a strict,
machine-readable widget spec — not code, not a blueprint, not a UI description.

{MONITORING_STATION_LANGUAGE}

{SIZE_CONTRACT}

{REFRESH_POLICY_CONTRACT}

{PERMISSIONS_CONTRACT}

{CATEGORY_CONTRACT}

{DATA_SOURCE_CONTRACT}

`output_schema` is a small free-form object describing the *semantic roles* the
backend's `get_state()` output will fill (not literal keys yet — that is decided at
backend stage). Keep it to 2-5 roles, e.g. {{"primary": "score", "secondary": "overs",
"status": "match_state"}}. It exists so the blueprint and backend stages inherit a
shared idea of what matters most in the data.

`renderer_type` is a coarse hint for how the data will primarily be presented at
blueprint stage: one of "card" (stat/key-value focused), "list" (a feed of items), or
"table" (rows/columns). Pick the one that matches the primary content shape.

`lifecycle_policy` is a free-form object with at least a `stateful` boolean (does the
widget carry forward state between refreshes that matters, e.g. a running clock or
tally) and an `expires` boolean (does this widget's usefulness end, e.g. a countdown to
a specific event). Include `default_ttl_seconds` only when `expires` is true.

Respond with STRICT JSON only, matching the provided output schema exactly. No prose,
no markdown fences, no trailing commentary. Every field is required. Do not add fields
that are not in the schema.
""".strip()


def spec_system_prompt() -> str:
    """System prompt for the spec-drafting stage (idea -> WidgetSpecDraft JSON)."""

    return SPEC_SYSTEM_PROMPT


SPEC_USER_PROMPT_TEMPLATE = """
Widget idea:
{idea}

Draft the widget spec for this idea now. Identify the concrete data source before
anything else, then fill in every required field. Return strict JSON only, matching
the spec output schema, with no surrounding text.
""".strip()


def spec_user_prompt(*, idea: str) -> str:
    """User prompt for the spec-drafting stage; embeds the raw idea text."""

    return SPEC_USER_PROMPT_TEMPLATE.format(idea=idea.strip())


def spec_output_schema() -> dict[str, Any]:
    """Strict JSON Schema mirroring `WidgetSpecDraft` exactly (additionalProperties: false)."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WidgetSpecDraft",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "name",
            "category",
            "description",
            "min_size",
            "preferred_size",
            "refresh_policy",
            "source_type",
            "permissions",
            "output_schema",
            "renderer_type",
            "lifecycle_policy",
        ],
        "properties": {
            "id": {
                "type": "string",
                "minLength": 1,
                "description": "snake_case widget id, unique, sanitized (letters/digits/underscore).",
            },
            "name": {"type": "string", "minLength": 1},
            "category": {"type": "string", "minLength": 1},
            "description": {
                "type": "string",
                "minLength": 1,
                "description": "Monitoring-station tone; must name the concrete data source.",
            },
            "min_size": {"type": "string", "enum": list(ALLOWED_SIZES)},
            "preferred_size": {"type": "string", "enum": list(ALLOWED_SIZES)},
            "refresh_policy": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode", "interval_seconds"],
                "properties": {
                    "mode": {"type": "string", "enum": list(REFRESH_MODES)},
                    "interval_seconds": {"type": "integer", "minimum": 0},
                },
            },
            "source_type": {
                "type": "string",
                "enum": ["api", "feed", "scrape", "local"],
            },
            "permissions": {
                "type": "array",
                "items": {"type": "string", "enum": list(WIDGET_PERMISSIONS)},
            },
            "output_schema": {
                "type": "object",
                "description": "2-5 semantic role -> field name hints for the eventual get_state() output.",
                "minProperties": 1,
                "additionalProperties": {"type": "string"},
            },
            "renderer_type": {"type": "string", "enum": ["card", "list", "table"]},
            "lifecycle_policy": {
                "type": "object",
                "additionalProperties": False,
                "required": ["stateful", "expires"],
                "properties": {
                    "stateful": {"type": "boolean"},
                    "expires": {"type": "boolean"},
                    "default_ttl_seconds": {"type": "integer", "minimum": 1},
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# 2. Blueprint prompts
# ---------------------------------------------------------------------------

PRIMITIVE_CATALOG = """
Layout nodes (each needs `type` + `children`, optional `gap`: "none"|"sm"|"md", optional
`show_if`):
- `stack`: vertical stack of children.
- `row`: horizontal row of children.
- `grid`: grid of children; also requires `columns` (2-4).
- `scroll`: a scrollable region for children that may overflow (feeds, long lists).

Primitive nodes (leaves):
- `stat`: {{type, label, value_path, unit?, emphasis?("primary"|"secondary"),
  trend_path?, status_path?, status_map?}}. The workhorse for a single number.
- `text`: {{type, variant("title"|"body"|"caption"|"mono"), value_path OR literal
  (exactly one)}}. Use sparingly — data first, not prose.
- `badge_row`: {{type, items:[{{label_path OR literal, status_path?, status_map?}}]}}.
  Compact status chips in a row.
- `list`: {{type, items_path, limit?, item:{{primary_path, secondary_path?, meta_path?,
  status_path?, status_map?}}}}. `items_path` points at an array; the item paths are
  relative to each array element. This is the feed/headline primitive.
- `table`: {{type, items_path, limit?, columns:[{{header, value_path, align?}}]}}. Use at
  wide/large tiers when rows+columns communicate better than a list.
- `key_value`: {{type, entries:[{{label, value_path}}] OR entries_path}}. Small label/value
  grid for secondary detail (host, region, config summary).
- `progress`: {{type, value_path, max_path OR max_literal (not both), label?}}. A bounded
  quantity (disk used, quota consumed).
- `sparkline`: {{type, values_path, label?}}. `values_path` points at an array of numbers
  for a compact trend line.
- `timer`: {{type, target_path, direction("down"|"up"), label_path?}}. Renderer-local
  ticking — target_path is a timestamp/duration the client ticks against, not something
  the backend needs to update every second.
- `empty_state`: {{type, message, show_if_empty_path}}. Shown when the path at
  `show_if_empty_path` resolves to an empty/falsy value; always pair a `list`/`table`
  primitive with an `empty_state` sibling so a first-run/no-data state looks intentional
  instead of blank.

`show_if` (available on every node): {{path, op("exists"|"eq"|"gt"|"lt"), value?}} — hide
a subtree when a condition on the state does not hold.

`status_map` (on `stat`, `badge_row` items, `list` items): maps a raw status string
value to one of {status_colors} for threshold coloring. Always drive status color from
data (`status_path` + `status_map`), never hardcode a color.

Bindings are dot-paths into whatever the widget's `get_state()` coroutine returns
(e.g. `metrics.cpu_percent`, `items[0].title`, `headlines`). Array indices are only
used to reach into a *specific* element (e.g. a top item); iteration over an array is
what `list`/`table`/`sparkline` do via their own `*_path`.
""".strip().format(status_colors=", ".join(STATUS_COLORS))

BLUEPRINT_SIZE_TIERS = """
A blueprint's `layouts` object maps size tiers to a single root node each:
- `compact` (maps from small tiles like 1x1/1x2): show 1-2 key numbers, nothing else.
  No lists, no tables — a `stat` (maybe two in a tight `row`) or a single `badge_row`.
- `medium` (2x2) — REQUIRED, every blueprint must define it. The default, balanced
  view: a primary stat plus one or two supporting primitives (progress, key_value,
  short list).
- `wide` (4x2): more horizontal room — good for a `row` of stats next to a `list`/
  `table`, or a wider table with more columns.
- `tall` (1x2... actually taller multi-row): good for a longer `list`/`scroll` of
  items when height is the scarce-to-abundant axis.
- `large` (4x4): the richest view — multiple sections, a `grid`, sparkline plus table
  plus key_value. Still density-first: no empty decorative space, no filler headers
  repeating the widget title.
`compact`, `wide`, `tall`, and `large` are optional — omit a tier if the design has
nothing meaningfully different to show at that size (the renderer falls back to
`medium`). Never define a tier that is just `medium` with padding added; only add a
tier when it changes what's shown.
""".strip()

BLUEPRINT_EXAMPLE_SERVICE_MONITOR: dict[str, Any] = {
    "blueprint_version": "1",
    "widget_id": "svc_uptime_monitor",
    "layouts": {
        "compact": {
            "type": "stack",
            "gap": "sm",
            "children": [
                {
                    "type": "stat",
                    "label": "CPU",
                    "value_path": "metrics.cpu_percent",
                    "unit": "%",
                    "emphasis": "primary",
                    "status_path": "status",
                    "status_map": {"ok": "ok", "warn": "warn", "critical": "critical"},
                }
            ],
        },
        "medium": {
            "type": "stack",
            "gap": "sm",
            "children": [
                {
                    "type": "row",
                    "gap": "md",
                    "children": [
                        {
                            "type": "stat",
                            "label": "CPU",
                            "value_path": "metrics.cpu_percent",
                            "unit": "%",
                            "emphasis": "primary",
                            "status_path": "status",
                            "status_map": {"ok": "ok", "warn": "warn", "critical": "critical"},
                        },
                        {
                            "type": "stat",
                            "label": "Memory",
                            "value_path": "metrics.memory_percent",
                            "unit": "%",
                            "emphasis": "secondary",
                        },
                    ],
                },
                {
                    "type": "progress",
                    "value_path": "metrics.disk_percent",
                    "max_literal": 100,
                    "label": "Disk used",
                },
            ],
        },
        "wide": {
            "type": "row",
            "gap": "md",
            "children": [
                {
                    "type": "stack",
                    "gap": "sm",
                    "children": [
                        {
                            "type": "stat",
                            "label": "CPU",
                            "value_path": "metrics.cpu_percent",
                            "unit": "%",
                            "emphasis": "primary",
                            "status_path": "status",
                            "status_map": {"ok": "ok", "warn": "warn", "critical": "critical"},
                        },
                        {
                            "type": "progress",
                            "value_path": "metrics.disk_percent",
                            "max_literal": 100,
                            "label": "Disk used",
                        },
                    ],
                },
                {
                    "type": "key_value",
                    "entries": [
                        {"label": "Host", "value_path": "details.hostname"},
                        {"label": "Region", "value_path": "details.region"},
                        {"label": "Uptime", "value_path": "details.uptime_label"},
                    ],
                },
            ],
        },
    },
}
"""Few-shot blueprint example (a): a stat + progress + key_value service monitor tile."""

BLUEPRINT_EXAMPLE_FEED_LIST: dict[str, Any] = {
    "blueprint_version": "1",
    "widget_id": "feed_top_stories",
    "layouts": {
        "compact": {
            "type": "stack",
            "gap": "sm",
            "children": [
                {"type": "text", "value_path": "items[0].title", "variant": "body"},
                {
                    "type": "empty_state",
                    "message": "No stories yet",
                    "show_if_empty_path": "items",
                },
            ],
        },
        "medium": {
            "type": "scroll",
            "children": [
                {
                    "type": "list",
                    "items_path": "items",
                    "limit": 5,
                    "item": {
                        "primary_path": "title",
                        "secondary_path": "source",
                        "meta_path": "published_at",
                        "status_path": "status",
                        "status_map": {"new": "ok", "stale": "neutral"},
                    },
                },
                {
                    "type": "empty_state",
                    "message": "No stories yet",
                    "show_if_empty_path": "items",
                },
            ],
        },
        "wide": {
            "type": "table",
            "items_path": "items",
            "limit": 8,
            "columns": [
                {"header": "Title", "value_path": "title", "align": "left"},
                {"header": "Source", "value_path": "source", "align": "left"},
                {"header": "Score", "value_path": "score", "align": "right"},
            ],
        },
    },
}
"""Few-shot blueprint example (b): a list-based feed widget (headlines/top stories)."""


BLUEPRINT_SYSTEM_PROMPT = f"""
You are the GremlinBoard blueprint design agent. Given an approved widget spec, you
design its `view.blueprint.json` — a small declarative tree that the universal board
renderer turns into UI. You do not write any UI code; you compose vetted primitives.

{MONITORING_STATION_LANGUAGE}

Blueprint schema version is always `"blueprint_version": "1"`. `widget_id` must match
the spec's `id` exactly.

## Primitive catalog

{PRIMITIVE_CATALOG}

## Size tiers

{BLUEPRINT_SIZE_TIERS}

## Visual guidance

- Density first: every primitive on screen must earn its space. No decorative dividers,
  no restating the widget title inside the body (the board chrome already shows it), no
  empty `text` nodes as spacers.
- Prefer `stat` + `status_map` threshold coloring over prose descriptions of health
  ("CPU 92%, status critical" beats "CPU usage is currently quite high").
  Always drive status color from real data via `status_path`/`status_map`, never a
  literal.
- Every `list`/`table` primitive should have an `empty_state` sibling bound to the same
  (or a summarizing) path so a no-data state is designed, not blank.
- Dot-paths must correspond to keys you expect the widget's backend `get_state()` output
  to contain — do not invent paths unrelated to the spec's `output_schema` hints.

## Few-shot example (a) — stat/progress/key_value service monitor

```json
{json.dumps(BLUEPRINT_EXAMPLE_SERVICE_MONITOR, indent=2)}
```

## Few-shot example (b) — list-based feed widget

```json
{json.dumps(BLUEPRINT_EXAMPLE_FEED_LIST, indent=2)}
```

Respond with STRICT JSON only: a single blueprint object matching this schema shape,
`blueprint_version` "1", the widget's own `widget_id`, and a `layouts` object that
defines at minimum `medium`. No markdown fences, no commentary.
""".strip()


def blueprint_system_prompt() -> str:
    """System prompt for the blueprint-design stage (spec -> view.blueprint.json)."""

    return BLUEPRINT_SYSTEM_PROMPT


BLUEPRINT_USER_PROMPT_TEMPLATE = """
Approved widget spec:
{spec_json}

Design the view blueprint for this widget now. Use `widget_id: "{widget_id}"`. Cover at
least the `medium` tier; add `compact`/`wide`/`tall`/`large` only where they earn their
keep per the size-tier guidance. Bindings must be plausible dot-paths into a
`get_state()` result consistent with this spec's `output_schema` hints:
{output_schema_json}
Return strict JSON only, matching the blueprint schema, with no surrounding text.
""".strip()


def blueprint_user_prompt(*, spec: dict[str, Any]) -> str:
    """User prompt for the blueprint-design stage; embeds the approved spec."""

    output_schema = spec.get("output_schema", {})
    return BLUEPRINT_USER_PROMPT_TEMPLATE.format(
        spec_json=json.dumps(spec, indent=2, sort_keys=True),
        widget_id=spec.get("id", ""),
        output_schema_json=json.dumps(output_schema, indent=2, sort_keys=True),
    )


# ---------------------------------------------------------------------------
# 3. Backend prompts
# ---------------------------------------------------------------------------

IMPORT_ALLOWLIST: tuple[str, ...] = (
    "json",
    "time",
    "datetime",
    "math",
    "re",
    "asyncio",
    "typing",
    "dataclasses",
    "collections",
    "urllib.parse",
    "httpx",
    "gremlinboard_api.runtime.base",
)

IMPORT_DENYLIST_EXAMPLES: tuple[str, ...] = (
    "os",
    "sys",
    "subprocess",
    "socket",
    "pathlib",
)

BACKEND_SERVICE_CONTRACT = """
Every generated backend defines exactly one class inheriting `BaseWidgetService`
(from `gremlinboard_api.runtime.base`) and implements:
- `async def start(self) -> None`: called once on widget install/boot. Typically seeds
  `self.state` by calling `await self.get_state()`.
- `async def stop(self) -> None`: release anything held open (usually a no-op for
  simple poll/response widgets).
- `async def health(self) -> dict`: return at least `{"status": ..., "expired": bool}`.
  `status` should be "running" for healthy, "degraded" for a soft failure (stale
  fallback served, upstream error but widget still usable), matching the runtime's
  three-category alert model (never invent a fourth status category).
- `async def get_state(self) -> dict`: the single source of truth for what the
  blueprint renders. Fetch/compute fresh data, call
  `self.set_refresh_directive(self.resolve_refresh_directive(...))` to report the
  chosen refresh cadence, assign the result to `self.state`, and return it.

Available on `self` (from `BaseWidgetService`): `self.instance_id`, `self.manifest`,
`self.config` (the widget's config-schema-validated dict), `self.service_context`
(carries `provider_registry` when network permissions are used),
`self.force_refresh_requested` (True during an operator-triggered manual refresh —
use it to bypass cache), and `self.resolve_refresh_directive(live=...,
default_interval_seconds=..., live_interval_seconds=...)` which folds in any
config-driven `refresh_behavior`/`refresh_interval_seconds` override and returns a
`RefreshDirective` you should both `set_refresh_directive(...)` and reflect in the
returned state's own `meta.refresh` block for the frontend Stats toggle.
""".strip()

BACKEND_WORKED_EXAMPLE = '''
Condensed worked example, distilled from `widgets/news/backend.py` (a real built-in):

```python
from __future__ import annotations

from gremlinboard_api.providers.models import ProviderRequest
from gremlinboard_api.runtime.base import BaseWidgetService


class NewsWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        meta = self.state.get("meta", {}) if isinstance(self.state, dict) else {}
        degraded = meta.get("stale", False) or meta.get("fallback", False)
        return {"status": "degraded" if degraded else "running", "expired": False}

    async def get_state(self) -> dict[str, object]:
        topic = str(self.config.get("topic", "openclaw"))
        provider_registry = getattr(self.service_context, "provider_registry", None)
        provider = provider_registry.create_news_provider("rss")
        result = await provider.fetch(
            request=ProviderRequest(
                cache_namespace=self.instance_id,
                query={"topic": topic, "limit": self.config.get("limit", 5)},
                force_refresh=self.force_refresh_requested,
                cache_ttl_seconds=300,  # cache upstream responses; do not re-fetch every call
            )
        )
        headlines = result.data.get("headlines", []) if isinstance(result.data, dict) else []

        # Conservative, cache-friendly interval; never a 1-second loop.
        directive = self.resolve_refresh_directive(
            live=False, default_interval_seconds=600, live_interval_seconds=180,
        )
        self.set_refresh_directive(directive)

        state = {
            "kind": "news",
            "topic": topic,
            "headlines": headlines,
            "meta": {
                "cached": result.to_meta().get("cached", False),
                "stale": result.to_meta().get("stale", False),
                "fallback": result.to_meta().get("fallback", False),
                "refresh": {
                    "mode": directive.mode,
                    "interval_seconds": directive.interval_seconds,
                    "reason": directive.reason,
                },
            },
        }
        self.state = state
        return state
```

Key patterns to copy: cache TTL passed explicitly to the provider/fetch call; the
refresh directive is resolved with a conservative `default_interval_seconds` and
reported back in both `set_refresh_directive` and the returned `meta.refresh` block;
`force_refresh_requested` is threaded through so manual refresh bypasses cache; a
degraded/stale upstream still returns a usable (possibly cached/fallback) `state`
instead of raising — the widget stays "degraded", not "critical", when a stale value is
servable.
'''.strip()

BACKEND_EFFICIENCY_RULES = """
Efficiency rules (from RUNTIME.md) — non-negotiable:
- Never write a one-second (or sub-60-second, for `interval` mode) backend refresh
  loop. Countdown/visual-only ticking belongs in the renderer (via the `timer`
  blueprint primitive), not the backend.
- Use cache TTLs on any network call; do not re-fetch upstream data more often than the
  chosen `refresh_policy.interval_seconds`.
- Degrade gracefully: on upstream failure, prefer serving stale cached data (marked
  `stale: true` in the returned state's `meta`) over raising or returning nothing. Only
  report `health.status = "critical"`-equivalent behavior (an exception/failed refresh)
  when there is truly no usable data.
- Network calls use `httpx` (async client), never a blocking HTTP library.
- Never busy-wait or `sleep()` inside `get_state()`/`health()`/`start()`; the runtime
  manager owns scheduling. Backends only compute/fetch once when called.
""".strip()

BACKEND_IMPORT_RULES = f"""
Import allowlist — a generated backend module may `import` ONLY from:
{", ".join(IMPORT_ALLOWLIST)}
No other imports are permitted, explicitly including (not exhaustive):
{", ".join(IMPORT_DENYLIST_EXAMPLES)}, `eval`, `exec`, and any dynamic import
mechanism (`importlib`, `__import__`). Do not import third-party HTTP/database/OS
libraries beyond `httpx`. If the widget needs a capability outside this allowlist, say
so in your response instead of importing a disallowed module.
""".strip()

BACKEND_CONFIG_SCHEMA_RULES = """
`config.schema.json` conventions: a JSON Schema object describing user-editable config
(e.g. `topic`, `limit`, `feed_urls`, `cache_ttl_seconds`, `refresh_behavior`,
`refresh_interval_seconds`). Keep it small, give every property a sane `default`, and
mirror any field the backend actually reads from `self.config`. `refresh_behavior`
(enum: "auto"|"manual"|"interval"|"live") and `refresh_interval_seconds` are
conventionally supported so the operator can override `resolve_refresh_directive`
behavior without a code change — include them when the widget is not `manual`-only.
""".strip()

BACKEND_BINDING_RULE = """
HARD RULE: the set of dot-paths the blueprint binds against MUST be exactly covered by
what `get_state()` returns. Every binding path listed below must resolve to a real key
in the returned state dict (following nested objects/array indices as written); you
must not return a state shape that leaves any of them undefined, and you must not add
speculative extra top-level keys the blueprint never reads. If a listed path cannot be
served for a data-availability reason, return the key with a null/empty value plus a
`meta` flag explaining why (e.g. `meta.fallback = true`) rather than omitting it.
""".strip()

BACKEND_SYSTEM_PROMPT = f"""
You are the GremlinBoard backend generation agent. Given an approved widget spec and
blueprint, you write the widget's `backend.py`: one `BaseWidgetService` subclass that
implements the service contract from RUNTIME.md.

## Service contract

{BACKEND_SERVICE_CONTRACT}

## Worked example

{BACKEND_WORKED_EXAMPLE}

## Efficiency rules

{BACKEND_EFFICIENCY_RULES}

## Import allowlist

{BACKEND_IMPORT_RULES}

## Config schema conventions

{BACKEND_CONFIG_SCHEMA_RULES}

## Binding coverage

{BACKEND_BINDING_RULE}

Respond with the full contents of `backend.py` as a single fenced Python code block
(```python ... ```), and nothing else outside the fence.
""".strip()


def backend_system_prompt() -> str:
    """System prompt for the backend-generation stage (spec + blueprint -> backend.py)."""

    return BACKEND_SYSTEM_PROMPT


BACKEND_USER_PROMPT_TEMPLATE = """
Approved widget spec:
{spec_json}

Approved blueprint:
{blueprint_json}

Binding paths collected from every layout tier in this blueprint (each MUST resolve
against your `get_state()` output, per the binding coverage hard rule):
{binding_paths}

Write `backend.py` for this widget now. Choose a class name in PascalCase derived from
the widget id. Return only the fenced Python code block.
""".strip()


def _collect_binding_paths_loose(node: Any, paths: set[str]) -> None:
    """Best-effort binding-path collector over a plain dict blueprint node.

    Mirrors `gremlinboard_api.schemas.blueprint.collect_binding_paths` but tolerates
    partially-formed dicts (e.g. a model-authored blueprint mid-repair) so the backend
    prompt can still list bindings even before the blueprint has been strictly
    validated.
    """

    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key.endswith("_path") and isinstance(value, str):
            paths.add(value)
        elif key == "show_if" and isinstance(value, dict) and isinstance(value.get("path"), str):
            paths.add(value["path"])
        elif key == "children" and isinstance(value, list):
            for child in value:
                _collect_binding_paths_loose(child, paths)
        elif key == "item" and isinstance(value, dict):
            _collect_binding_paths_loose(value, paths)
        elif key == "items" and isinstance(value, list):
            for child in value:
                _collect_binding_paths_loose(child, paths)
        elif key == "columns" and isinstance(value, list):
            for child in value:
                _collect_binding_paths_loose(child, paths)
        elif key == "entries" and isinstance(value, list):
            for child in value:
                _collect_binding_paths_loose(child, paths)


def _collect_blueprint_binding_paths(blueprint: dict[str, Any]) -> list[str]:
    paths: set[str] = set()
    layouts = blueprint.get("layouts", {})
    if isinstance(layouts, dict):
        for layout in layouts.values():
            _collect_binding_paths_loose(layout, paths)
    defaults = blueprint.get("defaults", {})
    if isinstance(defaults, dict):
        for layout in defaults.values():
            _collect_binding_paths_loose(layout, paths)
    return sorted(paths)


def backend_user_prompt(*, spec: dict[str, Any], blueprint: dict[str, Any]) -> str:
    """User prompt for the backend-generation stage; embeds spec, blueprint, and bindings."""

    binding_paths = _collect_blueprint_binding_paths(blueprint)
    binding_paths_text = "\n".join(f"- {path}" for path in binding_paths) or "- (none found)"
    return BACKEND_USER_PROMPT_TEMPLATE.format(
        spec_json=json.dumps(spec, indent=2, sort_keys=True),
        blueprint_json=json.dumps(blueprint, indent=2, sort_keys=True),
        binding_paths=binding_paths_text,
    )


# ---------------------------------------------------------------------------
# 4. Review prompts
# ---------------------------------------------------------------------------

REVIEW_RUBRIC = """
Review the full generated package (manifest, config schema, backend source, blueprint)
against this rubric. Every issue you raise must cite `area` as one of: "contract",
"bindings", "safety", "refresh_policy", "sizing", "other".

1. Contract compliance ("contract"): manifest has every required field from
   WIDGET_SPEC.md (id, version, name, category, description, min_size, preferred_size,
   allowed_sizes, refresh_policy, lifecycle_policy, runtime_policy, permissions,
   renderer, service, config_schema); `service` implements start/stop/health/get_state;
   `id` matches the widget directory / blueprint `widget_id`.
2. Binding-path / get_state mismatches ("bindings"): every dot-path the blueprint binds
   against (across all layout tiers) must be servable from the backend's `get_state()`
   return shape. Flag any path the backend clearly cannot produce, and any state key the
   backend returns that no blueprint node ever reads (dead data is a smell, not
   automatically critical).
3. Unsafe patterns ("safety"): network calls (`httpx`, or any provider fetch) without
   `permissions` including `"network"`; any import outside the allowlist (json, time,
   datetime, math, re, asyncio, typing, dataclasses, collections, urllib.parse, httpx,
   gremlinboard_api.runtime.base) — flag `os`, `sys`, `subprocess`, `socket`,
   `pathlib`, `eval`, `exec`, dynamic imports as critical; unbounded loops or
   `while True` without a bounded exit; missing error handling around network/parsing
   calls that would raise instead of degrading.
4. Refresh-policy sanity ("refresh_policy"): `mode: "live"` used for genuinely static
   data, or `interval_seconds` under 60 for non-live mode (sub-60s polling is only
   defensible for `live`, and even then rarely below ~10s); missing conservative cache
   TTL usage in the backend despite an `interval`/`live` policy.
5. Size sanity ("sizing"): `min_size`/`preferred_size` not present in `allowed_sizes`;
   `preferred_size` clearly mismatched to content density (e.g. a five-column table
   crammed into `1x1`, or a single number padded out to `4x4`).

Severity guide: `critical` blocks install (safety violations, broken contract,
unresolvable binding mismatch); `warning` should be fixed but is not blocking (a
slightly aggressive interval, a borderline size choice); `info` is a suggestion/nit.
Approve for install only when there are zero `critical` issues.
""".strip()

REVIEW_SYSTEM_PROMPT = f"""
You are the GremlinBoard install-gate review agent. GremlinBoard never installs
generated widget code directly from raw model output — you are the reviewer that
stands between generation and install. Be specific and cite what you checked; do not
rubber-stamp with an empty issues list.

{REVIEW_RUBRIC}

Respond with STRICT JSON only, matching the review output schema, with no surrounding
text.
""".strip()


def review_system_prompt() -> str:
    """System prompt for the review stage (package -> structured review verdict)."""

    return REVIEW_SYSTEM_PROMPT


REVIEW_USER_PROMPT_TEMPLATE = """
Approved widget spec:
{spec_json}

Generated package summary:
{package_json}

Review this package against the rubric now. Return strict JSON only, matching the
review output schema, with no surrounding text.
""".strip()


def review_user_prompt(*, spec: dict[str, Any], package: dict[str, Any]) -> str:
    """User prompt for the review stage; embeds spec and the package under review."""

    return REVIEW_USER_PROMPT_TEMPLATE.format(
        spec_json=json.dumps(spec, indent=2, sort_keys=True),
        package_json=json.dumps(package, indent=2, sort_keys=True),
    )


def review_output_schema() -> dict[str, Any]:
    """Strict JSON Schema for the structured review verdict (additionalProperties: false)."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WidgetReviewVerdict",
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "issues", "approved_for_install_recommendation"],
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["severity", "area", "message", "fix_hint"],
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "warning", "info"],
                        },
                        "area": {
                            "type": "string",
                            "enum": ["contract", "bindings", "safety", "refresh_policy", "sizing", "other"],
                        },
                        "message": {"type": "string", "minLength": 1},
                        "fix_hint": {"type": "string", "minLength": 1},
                    },
                },
            },
            "approved_for_install_recommendation": {"type": "boolean"},
        },
    }


# ---------------------------------------------------------------------------
# 5. Repair prompts
# ---------------------------------------------------------------------------

REPAIR_USER_PROMPT_TEMPLATE = """
Your previous {stage} output failed validation with the following error(s):
{errors}

Fix ONLY the issues listed above. Do not otherwise change fields/content that were not
flagged. Return the full corrected {stage} artifact in the same format you were
originally asked for (strict JSON for spec/blueprint/review stages, a single fenced
Python code block for the backend stage) — not a diff, not a partial patch.
""".strip()


def repair_user_prompt(*, stage: str, errors: list[str]) -> str:
    """User prompt for a repair round; lists the prior validation errors to fix for `stage`."""

    errors_text = "\n".join(f"- {error}" for error in errors) or "- (no errors provided)"
    return REPAIR_USER_PROMPT_TEMPLATE.format(stage=stage, errors=errors_text)


# ---------------------------------------------------------------------------
# Legacy wrappers (deprecated) — kept only because ai/providers.py still imports
# these three names directly. New code should call the stage-specific functions
# above instead. Remove once providers.py migrates to ai/clients.py.
# ---------------------------------------------------------------------------


def render_idea_to_spec_prompt(*, idea: str) -> str:
    """Deprecated: use `spec_system_prompt()` + `spec_user_prompt(idea=...)` instead."""

    return f"{spec_system_prompt()}\n\n{spec_user_prompt(idea=idea)}"


def render_codegen_prompt(*, spec: dict[str, Any], scaffold_files: list[str]) -> str:
    """Deprecated: pre-blueprint codegen prompt kept for the legacy shell provider path.

    Use `blueprint_user_prompt()` + `backend_user_prompt()` for the real pipeline.
    """

    scaffold_list = "\n".join(f"- {path}" for path in scaffold_files) or "- (none)"
    return (
        f"{backend_system_prompt()}\n\n"
        "Approved widget spec:\n"
        f"{json.dumps(spec, indent=2, sort_keys=True)}\n\n"
        "Scaffold files:\n"
        f"{scaffold_list}\n\n"
        "(Legacy path: no blueprint is available yet for this call; infer reasonable "
        "get_state() bindings directly from the spec's output_schema hints.)"
    )


def render_review_prompt(*, spec: dict[str, Any], package: dict[str, Any]) -> str:
    """Deprecated: use `review_system_prompt()` + `review_user_prompt()` instead."""

    return f"{review_system_prompt()}\n\n{review_user_prompt(spec=spec, package=package)}"
