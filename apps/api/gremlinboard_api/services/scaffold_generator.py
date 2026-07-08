from __future__ import annotations

import json
from textwrap import dedent
from typing import Any

from gremlinboard_api.schemas.contracts import WidgetPackagePayload, WidgetSpecDraft
from gremlinboard_api.specs.pipeline import build_manifest_preview_with_version, scaffold_preview
from gremlinboard_api.specs.widget_ids import sanitize_identifier, sanitize_widget_id


class WidgetScaffoldGenerator:
    def generate(
        self,
        *,
        spec: WidgetSpecDraft,
        version: str,
        artifact_version: int,
    ) -> dict[str, Any]:
        widget_id = sanitize_widget_id(spec.id)
        manifest = build_manifest_preview_with_version(spec, version=version)
        config_schema = self._build_config_schema(spec)
        backend_source = self._build_backend_source(spec)
        blueprint = self._build_blueprint(spec)
        test_source = self._build_test_source(spec, version)
        package = WidgetPackagePayload(
            manifest=manifest,
            config_schema=config_schema,
            backend_source=backend_source,
            blueprint=blueprint,
        )
        preview = scaffold_preview(spec)
        files = [
            {
                "path": f"widgets/{widget_id}/manifest.json",
                "language": "json",
                "content": json.dumps(manifest, indent=2) + "\n",
            },
            {
                "path": f"widgets/{widget_id}/config.schema.json",
                "language": "json",
                "content": json.dumps(config_schema, indent=2) + "\n",
            },
            {
                "path": f"widgets/{widget_id}/backend.py",
                "language": "python",
                "content": backend_source,
            },
            {
                "path": f"widgets/{widget_id}/view.blueprint.json",
                "language": "json",
                "content": json.dumps(blueprint, indent=2) + "\n",
            },
            {
                "path": f"apps/api/tests/test_{widget_id}_widget.py",
                "language": "python",
                "content": test_source,
            },
        ]
        return {
            "artifact_version": artifact_version,
            "package": package.model_dump(mode="json", exclude_none=True),
            "files": files,
            "preview": preview,
        }

    def _build_config_schema(self, spec: WidgetSpecDraft) -> dict[str, Any]:
        properties: dict[str, Any] = {
            "title_override": {
                "type": "string",
                "title": "Title Override",
                "description": "Optional display title shown by the renderer.",
            }
        }
        if spec.category in {"news", "trending", "sports"} or "network" in spec.permissions:
            properties["query"] = {
                "type": "string",
                "title": "Query",
                "description": "Topic, team, source, or search query used by the generated widget.",
            }
        if spec.category == "sports":
            properties["team"] = {
                "type": "string",
                "title": "Team",
                "description": "Preferred team or league focus.",
            }
        if spec.category == "countdown":
            properties["target"] = {
                "type": "string",
                "title": "Target",
                "description": "Countdown target date or label.",
            }
        if spec.renderer_type in {"list", "table"}:
            properties["limit"] = {
                "type": "integer",
                "title": "Limit",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            }
        return {
            "title": f"{spec.name} Config",
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": [],
        }

    def _build_backend_source(self, spec: WidgetSpecDraft) -> str:
        widget_id = sanitize_widget_id(spec.id)
        class_name = _service_class_name(spec.name)
        output_json = json.dumps(_sample_output_from_schema(spec.output_schema), sort_keys=True)
        return dedent(
            f"""
            from __future__ import annotations

            from gremlinboard_api.runtime.base import BaseWidgetService


            class {class_name}(BaseWidgetService):
                async def start(self) -> None:
                    self.state = await self.get_state()

                async def stop(self) -> None:
                    return None

                async def health(self) -> dict[str, object]:
                    return {{
                        "status": "running",
                        "provider": "generated-shell",
                        "refresh_mode": {json.dumps(spec.refresh_policy.get("mode", "manual"))},
                    }}

                async def get_state(self) -> dict[str, object]:
                    title = self.config.get("title_override") or {json.dumps(spec.name)}
                    return {{
                        "kind": {json.dumps(widget_id)},
                        "title": title,
                        "category": {json.dumps(spec.category)},
                        "description": {json.dumps(spec.description)},
                        "output": {output_json},
                    }}
            """
        ).strip() + "\n"

    def _build_blueprint(self, spec: WidgetSpecDraft) -> dict[str, Any]:
        entries = [
            {"label": _label_from_path(path), "value_path": f"output.{path}"}
            for path in (_flatten_output_schema_keys(spec.output_schema) or ["primary"])[:6]
        ]
        children: list[dict[str, Any]] = [
            {"type": "text", "literal": spec.name, "variant": "title"},
        ]
        if spec.description:
            children.append({"type": "text", "literal": spec.description, "variant": "caption"})
        children.append({"type": "key_value", "entries": entries})
        return {
            "blueprint_version": "1",
            "widget_id": sanitize_widget_id(spec.id),
            "layouts": {
                "medium": {
                    "type": "stack",
                    "gap": "md",
                    "children": children,
                }
            },
        }

    def _build_test_source(self, spec: WidgetSpecDraft, version: str) -> str:
        widget_id = sanitize_widget_id(spec.id)
        return dedent(
            f"""
            from gremlinboard_api.specs.pipeline import build_manifest_preview_with_version
            from gremlinboard_api.schemas.contracts import WidgetSpecDraft


            def test_{widget_id}_generated_manifest_shape() -> None:
                spec = WidgetSpecDraft.model_validate(
                    {json.dumps(spec.model_dump(mode="json"), indent=2)}
                )
                manifest = build_manifest_preview_with_version(spec, version={json.dumps(version)})

                assert manifest["id"] == {json.dumps(widget_id)}
                assert manifest["version"] == {json.dumps(version)}
            """
        ).strip() + "\n"


def _service_class_name(name: str) -> str:
    cleaned = sanitize_identifier(name, fallback="GeneratedWidget")
    return f"{cleaned}Service"



def _sample_output_from_schema(value: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for index, (key, child) in enumerate(value.items()):
        if isinstance(child, dict):
            nested = _sample_output_from_schema(child)
            output[key] = nested or f"sample_{index + 1}"
        else:
            output[key] = f"sample_{index + 1}"
    return output or {"primary": "sample_1"}


def _label_from_path(path: str) -> str:
    return path.rsplit(".", 1)[-1].replace("_", " ").title()

def _flatten_output_schema_keys(value: dict[str, Any], *, prefix: str = "") -> list[str]:
    keys: list[str] = []
    for key, child in value.items():
        child_key = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            keys.extend(_flatten_output_schema_keys(child, prefix=child_key))
        else:
            keys.append(child_key)
    return keys
