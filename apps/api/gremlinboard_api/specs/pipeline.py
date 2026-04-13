from __future__ import annotations

from typing import Any

from gremlinboard_api.schemas.contracts import ALLOWED_TILE_SIZES, WidgetSpecDraft


def validate_widget_spec(spec: WidgetSpecDraft) -> list[str]:
    notes: list[str] = []
    if spec.min_size.value not in ALLOWED_TILE_SIZES:
        notes.append("min_size is not supported by the board grid")
    if spec.preferred_size.value not in ALLOWED_TILE_SIZES:
        notes.append("preferred_size is not supported by the board grid")
    if spec.preferred_size.cols < spec.min_size.cols or spec.preferred_size.rows < spec.min_size.rows:
        notes.append("preferred_size must not be smaller than min_size")
    if "manifest" in spec.description.lower():
        notes.append("description should describe behavior instead of implementation artifacts")
    return notes


def scaffold_preview(spec: WidgetSpecDraft) -> dict[str, Any]:
    widget_root = f"widgets/{spec.id}"
    return {
        "widget_root": widget_root,
        "files": [
            f"{widget_root}/manifest.json",
            f"{widget_root}/backend.py",
            f"{widget_root}/renderer.tsx",
            f"{widget_root}/config.schema.json",
            f"apps/api/tests/test_{spec.id}_widget.py",
        ],
        "review_required": True,
        "install_blocked": True,
    }
