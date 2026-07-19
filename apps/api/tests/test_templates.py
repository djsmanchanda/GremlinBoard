from __future__ import annotations

from typing import Any

import pytest

from gremlinboard_api.ai.templates import TEMPLATE_CATALOG, select_template
from gremlinboard_api.schemas.blueprint import validate_blueprint


def _spec(
    *,
    renderer_type: str,
    category: str,
    description: str,
    output_schema: dict[str, str],
) -> dict[str, Any]:
    return {
        "renderer_type": renderer_type,
        "category": category,
        "description": description,
        "output_schema": output_schema,
    }


def test_every_template_blueprint_validates() -> None:
    assert len(TEMPLATE_CATALOG) == 6

    for template in TEMPLATE_CATALOG:
        blueprint = validate_blueprint(template.blueprint)
        assert blueprint.widget_id == f"template_{template.id}"


@pytest.mark.parametrize(
    ("expected_template_id", "spec"),
    [
        (
            "single_stat",
            _spec(
                renderer_type="card",
                category="finance",
                description="Shows the current asset price and its trend.",
                output_schema={"primary": "price", "trend": "price_change"},
            ),
        ),
        (
            "stat_cluster_monitor",
            _spec(
                renderer_type="card",
                category="monitoring",
                description="Service health monitor for a local system.",
                output_schema={"metrics": "measurements", "status": "health", "details": "host"},
            ),
        ),
        (
            "feed_list",
            _spec(
                renderer_type="list",
                category="news",
                description="Scrollable feed of trending stories.",
                output_schema={"items": "stories", "headlines": "titles"},
            ),
        ),
        (
            "table_report",
            _spec(
                renderer_type="table",
                category="leaderboard",
                description="Comparison report with ranked records.",
                output_schema={"rows": "rankings", "columns": "fields"},
            ),
        ),
        (
            "countdown_timer",
            _spec(
                renderer_type="card",
                category="countdown",
                description="Countdown timer to an event deadline.",
                output_schema={"deadline": "target_at", "remaining": "duration", "label": "event_name"},
            ),
        ),
        (
            "key_value_summary",
            _spec(
                renderer_type="card",
                category="configuration",
                description="Host and region config summary.",
                output_schema={"summary": "config", "host": "hostname", "region": "location"},
            ),
        ),
    ],
)
def test_select_template_picks_expected_template(
    expected_template_id: str,
    spec: dict[str, Any],
) -> None:
    selected = select_template(spec)

    assert selected is not None
    assert selected.id == expected_template_id


def test_select_template_returns_none_without_any_matching_signal() -> None:
    spec = _spec(
        renderer_type="constellation",
        category="alchemy",
        description="Transforms unknown symbols into an implausible shape.",
        output_schema={"mystery": "unknown"},
    )

    assert select_template(spec) is None
