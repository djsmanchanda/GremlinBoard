from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WidgetTemplate:
    id: str
    name: str
    description: str
    renderer_types: tuple[str, ...]
    category_hints: tuple[str, ...]
    output_schema_roles: tuple[str, ...]
    blueprint: dict[str, Any]


TEMPLATE_CATALOG: tuple[WidgetTemplate, ...] = (
    WidgetTemplate(
        id="single_stat",
        name="Single stat",
        description="A single primary value with an optional trend, such as uptime, price, or a count.",
        renderer_types=("card",),
        category_hints=("price", "uptime", "quote", "single stat"),
        output_schema_roles=("primary", "value", "metric", "trend", "change"),
        blueprint={
            "blueprint_version": "1",
            "widget_id": "template_single_stat",
            "layouts": {
                "medium": {
                    "type": "stat",
                    "label": "Current value",
                    "value_path": "metrics.primary_value",
                    "trend_path": "metrics.trend",
                    "emphasis": "primary",
                }
            },
        },
    ),
    WidgetTemplate(
        id="stat_cluster_monitor",
        name="Stat cluster monitor",
        description="A service or system monitor with several metrics, bounded progress, and identifying details.",
        renderer_types=("card",),
        category_hints=("monitoring", "service", "system", "health", "infrastructure"),
        output_schema_roles=("metrics", "status", "progress", "details", "health"),
        blueprint={
            "blueprint_version": "1",
            "widget_id": "template_stat_cluster_monitor",
            "layouts": {
                "compact": {
                    "type": "stat",
                    "label": "Primary",
                    "value_path": "metrics.primary_value",
                    "emphasis": "primary",
                    "status_path": "status",
                    "status_map": {"ok": "ok", "warn": "warn", "critical": "critical"},
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
                                    "label": "Primary",
                                    "value_path": "metrics.primary_value",
                                    "emphasis": "primary",
                                    "status_path": "status",
                                    "status_map": {"ok": "ok", "warn": "warn", "critical": "critical"},
                                },
                                {
                                    "type": "stat",
                                    "label": "Secondary",
                                    "value_path": "metrics.secondary_value",
                                    "emphasis": "secondary",
                                },
                                {
                                    "type": "stat",
                                    "label": "Tertiary",
                                    "value_path": "metrics.tertiary_value",
                                    "emphasis": "secondary",
                                },
                            ],
                        },
                        {
                            "type": "progress",
                            "value_path": "metrics.progress_value",
                            "max_path": "metrics.progress_max",
                            "label": "Capacity",
                        },
                        {
                            "type": "key_value",
                            "entries": [
                                {"label": "Host", "value_path": "details.hostname"},
                                {"label": "Region", "value_path": "details.region"},
                            ],
                        },
                    ],
                },
            },
        },
    ),
    WidgetTemplate(
        id="feed_list",
        name="Feed list",
        description="A scrollable news, trending, or activity feed with links, refresh, and offset pagination.",
        renderer_types=("list",),
        category_hints=("news", "trending", "feed", "headline", "stories", "activity"),
        output_schema_roles=("items", "headlines", "stories", "feed", "entries"),
        blueprint={
            "blueprint_version": "1",
            "widget_id": "template_feed_list",
            "layouts": {
                "medium": {
                    "type": "stack",
                    "gap": "sm",
                    "children": [
                        {
                            "type": "row",
                            "gap": "sm",
                            "children": [
                                {
                                    "type": "action_button",
                                    "label": "Refresh",
                                    "action": "refresh",
                                    "style": "secondary",
                                },
                                {
                                    "type": "action_button",
                                    "label": "Next 5",
                                    "action": "config_patch",
                                    "config_patch": {"offset": 5},
                                    "style": "secondary",
                                },
                            ],
                        },
                        {
                            "type": "scroll",
                            "gap": "sm",
                            "children": [
                                {
                                    "type": "list",
                                    "items_path": "items",
                                    "limit": 5,
                                    "item": {
                                        "primary_path": "title",
                                        "secondary_path": "summary",
                                        "meta_path": "published_at",
                                        "href_path": "url",
                                    },
                                },
                                {
                                    "type": "empty_state",
                                    "message": "No items yet",
                                    "show_if_empty_path": "items",
                                },
                            ],
                        },
                    ],
                }
            },
        },
    ),
    WidgetTemplate(
        id="table_report",
        name="Table report",
        description="A tabular report for leaderboards, standings, comparisons, and multi-column records.",
        renderer_types=("table",),
        category_hints=("leaderboard", "standings", "comparison", "report", "ranking"),
        output_schema_roles=("rows", "records", "rankings", "results", "columns"),
        blueprint={
            "blueprint_version": "1",
            "widget_id": "template_table_report",
            "layouts": {
                "medium": {
                    "type": "stack",
                    "gap": "sm",
                    "children": [
                        {
                            "type": "table",
                            "items_path": "rows",
                            "limit": 8,
                            "columns": [
                                {"header": "Name", "value_path": "name", "align": "left"},
                                {"header": "Value", "value_path": "value", "align": "right"},
                                {"header": "Status", "value_path": "status", "align": "left"},
                            ],
                        },
                        {
                            "type": "empty_state",
                            "message": "No rows available",
                            "show_if_empty_path": "rows",
                        },
                    ],
                }
            },
        },
    ),
    WidgetTemplate(
        id="countdown_timer",
        name="Countdown timer",
        description="A renderer-local countdown to a deadline or event, with a data-bound label.",
        renderer_types=("card",),
        category_hints=("countdown", "timer", "deadline", "event"),
        output_schema_roles=("target", "target_at", "deadline", "remaining", "label"),
        blueprint={
            "blueprint_version": "1",
            "widget_id": "template_countdown_timer",
            "layouts": {
                "medium": {
                    "type": "stack",
                    "gap": "sm",
                    "children": [
                        {"type": "text", "value_path": "countdown.label", "variant": "caption"},
                        {
                            "type": "timer",
                            "target_path": "countdown.target_at",
                            "direction": "down",
                            "label_path": "countdown.label",
                        },
                    ],
                }
            },
        },
    ),
    WidgetTemplate(
        id="key_value_summary",
        name="Key-value summary",
        description="A compact host, region, configuration, or metadata summary made of labeled values.",
        renderer_types=("card",),
        category_hints=("configuration", "config", "host", "region", "summary", "metadata"),
        output_schema_roles=("details", "summary", "fields", "entries", "host", "region"),
        blueprint={
            "blueprint_version": "1",
            "widget_id": "template_key_value_summary",
            "layouts": {
                "medium": {
                    "type": "key_value",
                    "entries": [
                        {"label": "Host", "value_path": "summary.host"},
                        {"label": "Region", "value_path": "summary.region"},
                        {"label": "Mode", "value_path": "summary.mode"},
                    ],
                }
            },
        },
    ),
)


def select_template(spec: dict[str, Any]) -> WidgetTemplate | None:
    renderer_type = str(spec.get("renderer_type") or "").lower()
    category_text = " ".join(
        (str(spec.get("category") or ""), str(spec.get("description") or ""))
    ).lower()
    output_schema = spec.get("output_schema")
    output_schema_keys = (
        {str(key).lower() for key in output_schema}
        if isinstance(output_schema, dict)
        else set()
    )

    best_template: WidgetTemplate | None = None
    best_score = 0
    for template in TEMPLATE_CATALOG:
        score = 2 if renderer_type in template.renderer_types else 0
        score += sum(hint in category_text for hint in template.category_hints)
        score += sum(role in output_schema_keys for role in template.output_schema_roles)
        if score > best_score:
            best_template = template
            best_score = score

    return best_template if best_score >= 2 else None
