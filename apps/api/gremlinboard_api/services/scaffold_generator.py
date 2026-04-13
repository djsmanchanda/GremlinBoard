from __future__ import annotations

import json
import re
from textwrap import dedent
from typing import Any

from gremlinboard_api.schemas.contracts import WidgetPackagePayload, WidgetSpecDraft
from gremlinboard_api.specs.pipeline import build_manifest_preview_with_version, scaffold_preview


class WidgetScaffoldGenerator:
    def generate(
        self,
        *,
        spec: WidgetSpecDraft,
        version: str,
        artifact_version: int,
    ) -> dict[str, Any]:
        manifest = build_manifest_preview_with_version(spec, version=version)
        config_schema = self._build_config_schema(spec)
        backend_source = self._build_backend_source(spec)
        renderer_source = self._build_renderer_source(spec)
        test_source = self._build_test_source(spec, version)
        package = WidgetPackagePayload(
            manifest=manifest,
            config_schema=config_schema,
            backend_source=backend_source,
            renderer_source=renderer_source,
        )
        preview = scaffold_preview(spec)
        files = [
            {
                "path": f"widgets/{spec.id}/manifest.json",
                "language": "json",
                "content": json.dumps(manifest, indent=2) + "\n",
            },
            {
                "path": f"widgets/{spec.id}/config.schema.json",
                "language": "json",
                "content": json.dumps(config_schema, indent=2) + "\n",
            },
            {
                "path": f"widgets/{spec.id}/backend.py",
                "language": "python",
                "content": backend_source,
            },
            {
                "path": f"widgets/{spec.id}/renderer.tsx",
                "language": "tsx",
                "content": renderer_source,
            },
            {
                "path": f"apps/api/tests/test_{spec.id}_widget.py",
                "language": "python",
                "content": test_source,
            },
        ]
        return {
            "artifact_version": artifact_version,
            "package": package.model_dump(mode="json"),
            "files": files,
            "preview": preview,
        }

    def _build_config_schema(self, spec: WidgetSpecDraft) -> dict[str, Any]:
        return {
            "title": f"{spec.name} Config",
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title_override": {
                    "type": "string",
                    "title": "Title Override",
                    "description": "Optional display title shown by the renderer.",
                }
            },
            "required": [],
        }

    def _build_backend_source(self, spec: WidgetSpecDraft) -> str:
        class_name = _service_class_name(spec.name)
        state_template = {
            "kind": spec.id,
            "title": {"$ref": "config.title_override", "fallback": spec.name},
            "category": spec.category,
            "description": spec.description,
            "output": {
                key: f"sample_{index + 1}"
                for index, key in enumerate(_flatten_output_schema_keys(spec.output_schema) or ["primary"])
            },
        }
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
                        "kind": {json.dumps(spec.id)},
                        "title": title,
                        "category": {json.dumps(spec.category)},
                        "description": {json.dumps(spec.description)},
                        "output": {json.dumps(state_template["output"], indent=2)},
                    }}
            """
        ).strip() + "\n"

    def _build_renderer_source(self, spec: WidgetSpecDraft) -> str:
        component_name = _component_name(spec.name)
        return dedent(
            f"""
            import type {{ WidgetRendererProps }} from "@/lib/types";


            export function {component_name}({{ widget }}: WidgetRendererProps) {{
              const title = typeof widget.state.title === "string" ? widget.state.title : widget.title;
              const description =
                typeof widget.state.description === "string" ? widget.state.description : {json.dumps(spec.description)};
              const output =
                widget.state.output && typeof widget.state.output === "object" && !Array.isArray(widget.state.output)
                  ? Object.entries(widget.state.output)
                  : [];

              return (
                <div className="flex h-full flex-col justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{spec.category}</p>
                    <h3 className="mt-2 text-lg font-semibold text-white">{{title}}</h3>
                    <p className="mt-2 text-sm text-slate-300">{{description}}</p>
                  </div>
                  <div className="grid gap-2">
                    {{output.map(([key, value]) => (
                      <div key={{key}} className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
                        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{{key}}</p>
                        <p className="mt-1 text-sm text-slate-100">{{String(value)}}</p>
                      </div>
                    ))}}
                  </div>
                </div>
              );
            }}
            """
        ).strip() + "\n"

    def _build_test_source(self, spec: WidgetSpecDraft, version: str) -> str:
        return dedent(
            f"""
            from gremlinboard_api.specs.pipeline import build_manifest_preview_with_version
            from gremlinboard_api.schemas.contracts import WidgetSpecDraft


            def test_{spec.id}_generated_manifest_shape() -> None:
                spec = WidgetSpecDraft.model_validate(
                    {json.dumps(spec.model_dump(mode="json"), indent=2)}
                )
                manifest = build_manifest_preview_with_version(spec, version={json.dumps(version)})

                assert manifest["id"] == {json.dumps(spec.id)}
                assert manifest["version"] == {json.dumps(version)}
            """
        ).strip() + "\n"


def _service_class_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", name).title().replace(" ", "")
    return f"{cleaned}Service" if cleaned else "GeneratedWidgetService"


def _component_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", name).title().replace(" ", "")
    return f"{cleaned}Renderer" if cleaned else "GeneratedWidgetRenderer"


def _flatten_output_schema_keys(value: dict[str, Any], *, prefix: str = "") -> list[str]:
    keys: list[str] = []
    for key, child in value.items():
        child_key = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            keys.extend(_flatten_output_schema_keys(child, prefix=child_key))
        else:
            keys.append(child_key)
    return keys
