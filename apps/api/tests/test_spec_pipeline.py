from gremlinboard_api.schemas.contracts import WidgetSpecDraft
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
