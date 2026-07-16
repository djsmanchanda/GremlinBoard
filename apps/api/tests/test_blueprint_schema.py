from __future__ import annotations

import json
from copy import deepcopy
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pytest

from gremlinboard_api.schemas.blueprint import collect_binding_paths, validate_blueprint


# The schema ships as package data so wheel installs work outside a checkout.
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "gremlinboard_api" / "schemas" / "widget-blueprint.schema.json"


def sample_blueprint() -> dict[str, Any]:
    return {
        "blueprint_version": "1",
        "widget_id": "system_monitor",
        "layouts": {
            "compact": {
                "type": "stack",
                "gap": "sm",
                "children": [
                    {
                        "type": "stat",
                        "label": "CPU",
                        "value_path": "output.cpu.percent",
                        "unit": "%",
                        "emphasis": "primary",
                        "trend_path": "output.cpu.trend",
                        "status_path": "output.cpu.status",
                        "status_map": {"hot": "critical", "warm": "warn", "normal": "ok"},
                    }
                ],
            },
            "medium": {
                "type": "grid",
                "gap": "md",
                "columns": 2,
                "show_if": {"path": "output.ready", "op": "eq", "value": True},
                "children": [
                    {"type": "text", "literal": "System", "variant": "title"},
                    {"type": "text", "value_path": "output.summary", "variant": "body"},
                    {
                        "type": "badge_row",
                        "items": [
                            {
                                "label_path": "output.mode",
                                "status_path": "output.mode_status",
                                "status_map": {"active": "ok", "degraded": "warn"},
                            },
                            {"literal": "live"},
                        ],
                    },
                    {
                        "type": "list",
                        "items_path": "output.alerts",
                        "limit": 3,
                        "item": {
                            "primary_path": "title",
                            "secondary_path": "detail",
                            "meta_path": "age",
                            "status_path": "severity",
                            "status_map": {"critical": "critical", "warning": "warn"},
                        },
                    },
                    {
                        "type": "table",
                        "items_path": "output.processes",
                        "limit": 4,
                        "columns": [
                            {"header": "Name", "value_path": "name"},
                            {"header": "CPU", "value_path": "cpu", "align": "right"},
                        ],
                    },
                    {
                        "type": "key_value",
                        "entries": [
                            {"label": "Host", "value_path": "output.host"},
                            {"label": "Boot", "value_path": "output.booted_at"},
                        ],
                    },
                    {"type": "key_value", "entries_path": "output.metadata"},
                    {
                        "type": "progress",
                        "value_path": "output.memory.used",
                        "max_path": "output.memory.total",
                        "label": "Memory",
                    },
                    {"type": "progress", "value_path": "output.disk.used", "max_literal": 100},
                    {"type": "sparkline", "values_path": "output.cpu.history", "label": "CPU history"},
                    {
                        "type": "timer",
                        "target_path": "output.next_refresh_at",
                        "direction": "down",
                        "label_path": "output.refresh_label",
                    },
                    {"type": "empty_state", "message": "No alerts", "show_if_empty_path": "output.alerts"},
                    {
                        "type": "scroll",
                        "gap": "sm",
                        "children": [
                            {
                                "type": "row",
                                "gap": "none",
                                "children": [
                                    {"type": "text", "value_path": "items[0].title", "variant": "caption"}
                                ],
                            }
                        ],
                    },
                ],
            },
            "wide": {
                "type": "row",
                "children": [
                    {"type": "stat", "label": "Score", "value_path": "output.score", "emphasis": "secondary"}
                ],
            },
        },
        "defaults": {
            "offline": {
                "type": "text",
                "value_path": "output.offline_reason",
                "variant": "caption",
                "show_if": {"path": "output.offline", "op": "exists"},
            }
        },
    }


def test_valid_full_featured_blueprint_parses() -> None:
    blueprint = validate_blueprint(sample_blueprint())

    assert blueprint.blueprint_version == "1"
    assert blueprint.layouts.medium.type == "grid"


def test_unknown_node_type_rejected() -> None:
    data = sample_blueprint()
    data["layouts"]["medium"]["children"][0]["type"] = "chart"

    with pytest.raises(ValueError, match="union_tag_invalid|Input tag"):
        validate_blueprint(data)


def test_bad_dot_path_rejected() -> None:
    data = sample_blueprint()
    data["layouts"]["medium"]["children"][1]["value_path"] = "output..summary"

    with pytest.raises(ValueError, match="string_pattern_mismatch|pattern"):
        validate_blueprint(data)


def test_missing_medium_tier_rejected() -> None:
    data = sample_blueprint()
    del data["layouts"]["medium"]

    with pytest.raises(ValueError, match="layouts.medium"):
        validate_blueprint(data)


def test_extra_properties_rejected() -> None:
    data = sample_blueprint()
    data["layouts"]["medium"]["children"][0]["className"] = "text-xl"

    with pytest.raises(ValueError, match="extra_forbidden|Extra inputs"):
        validate_blueprint(data)


def test_collect_binding_paths_returns_every_referenced_dot_path() -> None:
    blueprint = validate_blueprint(sample_blueprint())

    assert collect_binding_paths(blueprint) == {
        "age",
        "cpu",
        "detail",
        "items[0].title",
        "name",
        "output.alerts",
        "output.booted_at",
        "output.cpu.history",
        "output.cpu.percent",
        "output.cpu.status",
        "output.cpu.trend",
        "output.disk.used",
        "output.host",
        "output.memory.total",
        "output.memory.used",
        "output.metadata",
        "output.mode",
        "output.mode_status",
        "output.next_refresh_at",
        "output.offline",
        "output.offline_reason",
        "output.processes",
        "output.ready",
        "output.refresh_label",
        "output.score",
        "output.summary",
        "severity",
        "title",
    }


def test_json_schema_file_is_valid_json() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "medium" in schema["properties"]["layouts"]["required"]


def test_json_schema_accepts_valid_sample_when_dependency_is_available() -> None:
    if find_spec("jsonschema") is None:
        pytest.skip("jsonschema is not installed")

    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    validator = Draft202012Validator(schema)
    validator.validate(deepcopy(sample_blueprint()))

