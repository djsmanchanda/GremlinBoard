from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    template: str

    def render(self, **context: Any) -> str:
        return self.template.format(**context)


IDEA_TO_SPEC_TEMPLATE = PromptTemplate(
    name="idea-to-spec",
    template=(
        "Turn this widget idea into a strict GremlinBoard widget spec.\n"
        "Use only supported tile sizes.\n"
        "Return machine-readable JSON only.\n"
        "Idea:\n{idea}\n"
    ),
)

CODEGEN_TEMPLATE = PromptTemplate(
    name="spec-to-codegen",
    template=(
        "Generate widget implementation guidance for this validated GremlinBoard spec.\n"
        "Keep registry-first architecture intact.\n"
        "Spec:\n{spec_json}\n"
        "Scaffold files:\n{scaffold_files}\n"
    ),
)

REVIEW_TEMPLATE = PromptTemplate(
    name="code-review",
    template=(
        "Review this generated GremlinBoard widget package before install.\n"
        "Focus on contract compliance, runtime safety, and missing validation.\n"
        "Spec:\n{spec_json}\n"
        "Package summary:\n{package_summary}\n"
    ),
)


def render_idea_to_spec_prompt(*, idea: str) -> str:
    return IDEA_TO_SPEC_TEMPLATE.render(idea=idea.strip())


def render_codegen_prompt(*, spec: dict[str, Any], scaffold_files: list[str]) -> str:
    return CODEGEN_TEMPLATE.render(
        spec_json=json.dumps(spec, indent=2, sort_keys=True),
        scaffold_files="\n".join(f"- {path}" for path in scaffold_files),
    )


def render_review_prompt(*, spec: dict[str, Any], package: dict[str, Any]) -> str:
    summary = {
        "manifest_id": package["manifest"]["id"],
        "manifest_version": package["manifest"]["version"],
        "files": [
            "manifest.json",
            "config.schema.json",
            "backend.py",
            "renderer.tsx",
        ],
    }
    return REVIEW_TEMPLATE.render(
        spec_json=json.dumps(spec, indent=2, sort_keys=True),
        package_summary=json.dumps(summary, indent=2, sort_keys=True),
    )
