from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from gremlinboard_api.schemas.contracts import (
    ALLOWED_TILE_SIZES,
    SpecDocumentFormat,
    WidgetManifest,
    WidgetSpecDraft,
)
from gremlinboard_api.specs.widget_ids import sanitize_widget_id, sanitize_identifier, widget_root_name, widget_service_module

try:
    import yaml
except ImportError:  # pragma: no cover - depends on local environment
    yaml = None


def parse_spec_document(*, content: str, format: SpecDocumentFormat) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        if format == SpecDocumentFormat.JSON:
            parsed = json.loads(content)
        else:
            if yaml is None:
                return None, [{"message": "PyYAML is not installed; YAML validation is unavailable."}]
            parsed = yaml.safe_load(content)
    except json.JSONDecodeError as exc:
        return None, [{"message": exc.msg, "line": exc.lineno, "column": exc.colno}]
    except yaml.YAMLError as exc:  # type: ignore[union-attr]
        mark = getattr(exc, "problem_mark", None)
        return None, [
            {
                "message": str(exc),
                "line": getattr(mark, "line", 0) + 1 if mark is not None else None,
                "column": getattr(mark, "column", 0) + 1 if mark is not None else None,
            }
        ]

    if not isinstance(parsed, dict):
        return None, [{"message": "Spec document must evaluate to an object"}]
    return parsed, []


def parse_and_validate_spec(
    *, content: str, format: SpecDocumentFormat
) -> tuple[WidgetSpecDraft | None, list[dict[str, Any]]]:
    parsed, errors = parse_spec_document(content=content, format=format)
    if errors:
        return None, errors
    try:
        return WidgetSpecDraft.model_validate(parsed), []
    except ValidationError as exc:
        return None, [
            {
                "message": item["msg"],
                "path": ".".join(str(part) for part in item["loc"]),
                "type": item["type"],
            }
            for item in exc.errors()
        ]


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


def build_manifest_preview(spec: WidgetSpecDraft) -> dict[str, Any]:
    return build_manifest_preview_with_version(spec, version="0.1.0")


def build_manifest_preview_with_version(spec: WidgetSpecDraft, *, version: str) -> dict[str, Any]:
    widget_id = sanitize_widget_id(spec.id)
    service_class_name = f"{sanitize_identifier(spec.name, fallback='GeneratedWidget')}Service"
    manifest = WidgetManifest(
        id=widget_id,
        version=version,
        name=spec.name,
        category=spec.category,
        description=spec.description,
        min_size=spec.min_size,
        preferred_size=spec.preferred_size,
        allowed_sizes=[spec.min_size, spec.preferred_size],
        refresh_policy=spec.refresh_policy,
        lifecycle_policy={
            "stateful": bool(spec.lifecycle_policy.get("stateful", True)),
            "expires": bool(spec.lifecycle_policy.get("expires", False)),
            "default_ttl_seconds": spec.lifecycle_policy.get("default_ttl_seconds"),
        },
        permissions=spec.permissions,
        renderer={"target": spec.renderer_type},
        service={"module": widget_service_module(widget_id), "class_name": service_class_name},
        config_schema="config.schema.json",
    )
    return manifest.model_dump(mode="json")


def scaffold_preview(spec: WidgetSpecDraft) -> dict[str, Any]:
    widget_id = widget_root_name(spec.id)
    widget_root = f"widgets/{widget_id}"
    return {
        "widget_root": widget_root,
        "files": [
            f"{widget_root}/manifest.json",
            f"{widget_root}/backend.py",
            f"{widget_root}/renderer.tsx",
            f"{widget_root}/config.schema.json",
            f"apps/api/tests/test_{widget_id}_widget.py",
        ],
        "review_required": True,
        "install_blocked": True,
    }
