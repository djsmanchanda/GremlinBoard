from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from gremlinboard_api.ai.prompts import (
    render_codegen_prompt,
    render_idea_to_spec_prompt,
    render_review_prompt,
)
from gremlinboard_api.schemas.contracts import WidgetSpecDraft


class AIProvider(ABC):
    provider_id: str
    label: str

    @property
    def supports_idea_to_spec(self) -> bool:
        return True

    @property
    def supports_codegen(self) -> bool:
        return True

    @property
    def supports_review(self) -> bool:
        return True

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def draft_spec(self, *, idea: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def build_generation_plan(self, *, widget_spec: dict[str, Any], stage_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def prepare_codegen(
        self,
        *,
        widget_spec: dict[str, Any],
        scaffold_files: list[str],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def review_package(
        self,
        *,
        widget_spec: dict[str, Any],
        package: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


class CodexProvider(AIProvider):
    provider_id = "codex"
    label = "Codex"

    async def health(self) -> dict[str, Any]:
        return {"status": "shell", "provider_id": self.provider_id, "mode": "deterministic-placeholder"}

    async def draft_spec(self, *, idea: str) -> dict[str, Any]:
        return _draft_spec_payload(idea=idea, provider_label=self.label)

    async def build_generation_plan(self, *, widget_spec: dict[str, Any], stage_id: str) -> dict[str, Any]:
        return {
            "stage_id": stage_id,
            "provider_id": self.provider_id,
            "steps": [
                {"id": "spec", "label": "Draft or confirm widget spec", "status": "ready"},
                {"id": "scaffold", "label": "Generate manifest and file scaffold", "status": "ready"},
                {"id": "codegen", "label": "Produce backend and renderer artifact set", "status": "ready"},
                {"id": "review", "label": "Require human review before install", "status": "required"},
                {"id": "install", "label": "Install only after approval", "status": "blocked"},
            ],
            "widget_id": widget_spec.get("id"),
        }

    async def prepare_codegen(
        self,
        *,
        widget_spec: dict[str, Any],
        scaffold_files: list[str],
    ) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "prompt": render_codegen_prompt(spec=widget_spec, scaffold_files=scaffold_files),
            "notes": [
                "Codex shell prepared deterministic scaffold-backed generation guidance.",
                "No direct model execution occurred; install remains blocked pending review.",
            ],
        }

    async def review_package(
        self,
        *,
        widget_spec: dict[str, Any],
        package: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "prompt": render_review_prompt(spec=widget_spec, package=package),
            "summary": "Contract-focused review shell completed. Human approval is still required.",
            "issues": [],
            "checklist": [
                "Manifest uses supported fixed sizes only.",
                "Service contract includes start/stop/health/get_state.",
                "Generated install is blocked until explicit approval.",
            ],
            "requires_human_review": True,
        }


class ClaudeProvider(AIProvider):
    provider_id = "claude"
    label = "Claude"

    async def health(self) -> dict[str, Any]:
        return {"status": "shell", "provider_id": self.provider_id, "mode": "deterministic-placeholder"}

    async def draft_spec(self, *, idea: str) -> dict[str, Any]:
        payload = _draft_spec_payload(idea=idea, provider_label=self.label)
        payload["description"] = f"{payload['description']} Generated through the staged spec shell."
        return payload

    async def build_generation_plan(self, *, widget_spec: dict[str, Any], stage_id: str) -> dict[str, Any]:
        return {
            "stage_id": stage_id,
            "provider_id": self.provider_id,
            "steps": [
                {"id": "spec", "label": "Draft or confirm widget spec", "status": "ready"},
                {"id": "scaffold", "label": "Prepare scaffold and regeneration targets", "status": "ready"},
                {"id": "codegen", "label": "Build implementation artifact set", "status": "ready"},
                {"id": "review", "label": "Attach review summary and wait for approval", "status": "required"},
                {"id": "install", "label": "Install only after approval", "status": "blocked"},
            ],
            "widget_id": widget_spec.get("id"),
        }

    async def prepare_codegen(
        self,
        *,
        widget_spec: dict[str, Any],
        scaffold_files: list[str],
    ) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "prompt": render_codegen_prompt(spec=widget_spec, scaffold_files=scaffold_files),
            "notes": [
                "Claude shell prepared a regeneration-oriented codegen prompt.",
                "Artifacts are versioned before any install action is available.",
            ],
        }

    async def review_package(
        self,
        *,
        widget_spec: dict[str, Any],
        package: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "prompt": render_review_prompt(spec=widget_spec, package=package),
            "summary": "Readability and contract review shell completed. Human approval is still required.",
            "issues": [],
            "checklist": [
                "Spec-first flow preserved.",
                "Registry install remains explicit and review-gated.",
                "Generated package can be diffed before deployment.",
            ],
            "requires_human_review": True,
        }


def provider_from_id(provider_id: str, providers: dict[str, AIProvider]) -> AIProvider:
    provider = providers.get(provider_id)
    if provider is None:
        raise ValueError(f"unknown provider '{provider_id}'")
    return provider


def _draft_spec_payload(*, idea: str, provider_label: str) -> dict[str, Any]:
    normalized = " ".join(idea.split())
    widget_id = _slugify(normalized)
    category = _detect_category(normalized)
    min_size, preferred_size = _detect_sizes(normalized)
    refresh_policy = _detect_refresh_policy(normalized, category)
    permissions = _detect_permissions(normalized, category)
    title = _titleize(widget_id)
    description = f"{title} widget drafted from idea using the {provider_label} adapter shell."
    prompt = render_idea_to_spec_prompt(idea=idea)
    return WidgetSpecDraft(
        id=widget_id,
        name=title,
        category=category,
        description=description,
        min_size=min_size,
        preferred_size=preferred_size,
        refresh_policy=refresh_policy,
        source_type="generated",
        permissions=permissions,
        output_schema={"primary": "string", "secondary": "string", "status": "string"},
        renderer_type="card",
        lifecycle_policy={"expires": False, "stateful": True},
    ).model_dump(mode="json") | {"idea_prompt": prompt}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not slug:
        slug = "generated_widget"
    if not slug[0].isalpha():
        slug = f"widget_{slug}"
    return slug[:48]


def _titleize(widget_id: str) -> str:
    return " ".join(part.capitalize() for part in widget_id.split("_")) or "Generated Widget"


def _detect_category(idea: str) -> str:
    lowered = idea.lower()
    if any(token in lowered for token in ("sport", "ipl", "f1", "football")):
        return "sports"
    if any(token in lowered for token in ("news", "headline", "briefing")):
        return "news"
    if any(token in lowered for token in ("trend", "reddit", "x ", "hacker news", "hackernews")):
        return "trending"
    if any(token in lowered for token in ("countdown", "timer", "deadline")):
        return "countdown"
    if any(token in lowered for token in ("pin", "note", "todo", "personal")):
        return "pinboard"
    return "custom"


def _detect_sizes(idea: str) -> tuple[str, str]:
    lowered = idea.lower()
    if any(token in lowered for token in ("compact", "small", "badge")):
        return "1x1", "1x2"
    if any(token in lowered for token in ("wide", "ticker", "headline")):
        return "2x2", "4x2"
    if any(token in lowered for token in ("tall", "feed", "stack")):
        return "1x2", "2x4"
    if any(token in lowered for token in ("dashboard", "board", "dense")):
        return "2x2", "4x4"
    return "2x2", "4x2"


def _detect_refresh_policy(idea: str, category: str) -> dict[str, Any]:
    lowered = idea.lower()
    if any(token in lowered for token in ("manual", "pin", "notes")):
        return {"mode": "manual", "interval_seconds": 0}
    if category == "sports":
        return {"mode": "interval", "interval_seconds": 60}
    if category == "news":
        return {"mode": "interval", "interval_seconds": 600}
    if category == "trending":
        return {"mode": "interval", "interval_seconds": 300}
    if "live" in lowered:
        return {"mode": "live", "interval_seconds": 0}
    return {"mode": "interval", "interval_seconds": 300}


def _detect_permissions(idea: str, category: str) -> list[str]:
    lowered = idea.lower()
    permissions: list[str] = []
    if any(token in lowered for token in ("api", "http", "network")) or category in {"sports", "news", "trending"}:
        permissions.append("network")
    if any(token in lowered for token in ("personal", "pin", "notes", "store")):
        permissions.append("storage")
    return permissions or ["network"]
