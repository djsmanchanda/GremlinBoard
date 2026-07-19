from gremlinboard_api.schemas.contracts import WidgetSpecDraft
from gremlinboard_api.services.scaffold_generator import WidgetScaffoldGenerator
from gremlinboard_api.specs.pipeline import scaffold_preview, validate_widget_spec


def test_spec_pipeline_accepts_supported_sizes() -> None:
    draft = WidgetSpecDraft(
        id="operations_board",
        name="Operations Board",
        category="ops",
        description="Shows critical runtime state for the operations team.",
        min_size="2x2",
        preferred_size="4x2",
        refresh_policy={"mode": "interval", "interval_seconds": 300},
        source_type="api",
        permissions=["network"],
        output_schema={"headline": "string"},
        renderer_type="card",
        lifecycle_policy={"expires": False, "stateful": True},
    )

    notes = validate_widget_spec(draft)
    preview = scaffold_preview(draft)

    assert notes == []
    assert preview["widget_root"] == "widgets/operations_board"
    assert preview["review_required"] is True

def test_scaffold_materializes_declared_config_fields() -> None:
    draft = WidgetSpecDraft(
        id="paged_feed",
        name="Paged Feed",
        category="news",
        description="Polls a public feed API.",
        min_size="2x2",
        preferred_size="4x2",
        refresh_policy={"mode": "interval", "interval_seconds": 300},
        source_type="api",
        permissions=["network"],
        output_schema={"items": "stories"},
        renderer_type="list",
        lifecycle_policy={"expires": False, "stateful": True},
        config_fields=[
            {"name": "offset", "type": "integer", "minimum": 0, "default": 0, "required": False},
            {"name": "page_size", "type": "integer", "minimum": 1, "default": 5, "required": False},
        ],
    )

    package = WidgetScaffoldGenerator().generate(spec=draft, version="0.1.0", artifact_version=1)["package"]
    properties = package["config_schema"]["properties"]

    assert properties["offset"] == {"type": "integer", "default": 0, "minimum": 0}
    assert properties["page_size"] == {"type": "integer", "default": 5, "minimum": 1}
    assert package["config_schema"]["additionalProperties"] is False
