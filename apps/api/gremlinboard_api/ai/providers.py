from __future__ import annotations
from abc import ABC, abstractmethod
import re
import time
from typing import Any

import httpx

from gremlinboard_api.ai.prompts import (
    render_codegen_prompt,
    render_idea_to_spec_prompt,
    render_review_prompt,
)
from gremlinboard_api.schemas.contracts import WidgetSpecDraft
from gremlinboard_api.specs.widget_ids import sanitize_widget_id


class AIProvider(ABC):
    provider_id: str
    label: str
    supported_model_ids: tuple[str, ...] = ()
    default_model_id: str | None = None
    fallback_model_options: tuple[dict[str, Any], ...] = ()
    model_api_credential_providers: tuple[str, ...] = ()
    model_cache_ttl_seconds = 600
    _model_cache: tuple[list[dict[str, Any]], str, str, float, str] | None = None

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
    async def draft_spec(self, *, idea: str, model_id: str | None = None) -> dict[str, Any]:
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
        model_id: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def review_package(
        self,
        *,
        widget_spec: dict[str, Any],
        package: dict[str, Any],
        model_id: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def list_model_options(self, *, credentials: dict[str, str]) -> tuple[list[dict[str, Any]], str, str]:
        api_key = self._credential_for(credentials)
        cache_key = "credential" if api_key else "fallback"
        cached = self._model_cache
        if cached is not None and cached[3] > time.monotonic() and cached[4] == cache_key:
            return [dict(option) for option in cached[0]], cached[1], cached[2]

        if api_key:
            try:
                options = await self._fetch_model_options(api_key=api_key)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                options = []
            if options:
                self._model_cache = (options, "provider_api", "live", time.monotonic() + self.model_cache_ttl_seconds, cache_key)
                return options, "provider_api", "live"
        fallback = [dict(option) for option in self.fallback_model_options]
        if fallback:
            self._model_cache = (fallback, "fallback", "fallback", time.monotonic() + self.model_cache_ttl_seconds, cache_key)
            return fallback, "fallback", "fallback"
        options = [{"id": model_id, "label": model_id, "source": "fallback"} for model_id in self.supported_model_ids]
        self._model_cache = (options, "fallback", "fallback", time.monotonic() + self.model_cache_ttl_seconds, cache_key)
        return options, "fallback", "fallback"

    async def _fetch_model_options(self, *, api_key: str) -> list[dict[str, Any]]:
        return []

    def _credential_for(self, credentials: dict[str, str]) -> str | None:
        for provider_id in self.model_api_credential_providers:
            secret = credentials.get(provider_id)
            if secret:
                return secret
        return None


class CodexProvider(AIProvider):
    provider_id = "codex"
    label = "Codex"
    supported_model_ids = ("gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.3-codex")
    default_model_id = "gpt-5.5"
    model_api_credential_providers = ("codex", "openai")
    fallback_model_options = (
        {
            "id": "gpt-5.5",
            "label": "GPT-5.5",
            "intelligence_level": "highest",
            "speed_level": "fast",
            "reasoning_effort_options": ["none", "low", "medium", "high", "xhigh"],
            "source": "fallback",
        },
        {
            "id": "gpt-5.4",
            "label": "GPT-5.4",
            "intelligence_level": "high",
            "speed_level": "fast",
            "reasoning_effort_options": ["none", "low", "medium", "high", "xhigh"],
            "source": "fallback",
        },
        {
            "id": "gpt-5.4-mini",
            "label": "GPT-5.4 mini",
            "intelligence_level": "medium",
            "speed_level": "faster",
            "reasoning_effort_options": ["none", "low", "medium", "high", "xhigh"],
            "source": "fallback",
        },
        {
            "id": "gpt-5.4-nano",
            "label": "GPT-5.4 nano",
            "intelligence_level": "low",
            "speed_level": "fastest",
            "reasoning_effort_options": ["none", "low", "medium", "high", "xhigh"],
            "source": "fallback",
        },
        {
            "id": "gpt-5.3-codex",
            "label": "GPT-5.3 Codex",
            "intelligence_level": "coding",
            "speed_level": "balanced",
            "reasoning_effort_options": ["low", "medium", "high", "xhigh"],
            "source": "fallback",
        },
    )

    async def _fetch_model_options(self, *, api_key: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as client:
            response = await client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"})
            response.raise_for_status()
        data = response.json().get("data", [])
        available_ids = {
            str(item.get("id"))
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str) and _is_generation_model_id(item["id"])
        }
        return _merge_known_model_metadata(available_ids, self.fallback_model_options)

    async def health(self) -> dict[str, Any]:
        return {"status": "shell", "provider_id": self.provider_id, "mode": "deterministic-placeholder"}

    async def draft_spec(self, *, idea: str, model_id: str | None = None) -> dict[str, Any]:
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
        model_id: str | None = None,
    ) -> dict[str, Any]:
        selected_model = self._resolve_model(model_id)
        return {
            "provider_id": self.provider_id,
            "model_id": selected_model,
            "prompt": render_codegen_prompt(spec=widget_spec, scaffold_files=scaffold_files),
            "notes": [
                f"Codex scaffold handoff prepared with requested model '{selected_model}'.",
                "No direct model execution occurred; install remains blocked pending review.",
            ],
        }

    async def review_package(
        self,
        *,
        widget_spec: dict[str, Any],
        package: dict[str, Any],
        model_id: str | None = None,
    ) -> dict[str, Any]:
        selected_model = self._resolve_model(model_id)
        return {
            "provider_id": self.provider_id,
            "model_id": selected_model,
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

    def _resolve_model(self, model_id: str | None) -> str:
        if model_id and model_id in self.supported_model_ids:
            return model_id
        return self.default_model_id or self.supported_model_ids[0]


class ClaudeProvider(AIProvider):
    provider_id = "claude"
    label = "Claude"
    supported_model_ids = ("claude-fable-5", "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5")
    default_model_id = "claude-fable-5"
    model_api_credential_providers = ("claude", "anthropic")
    fallback_model_options = (
        {
            "id": "claude-fable-5",
            "label": "Claude Fable 5",
            "intelligence_level": "highest",
            "speed_level": "moderate",
            "source": "fallback",
        },
        {
            "id": "claude-opus-4-8",
            "label": "Claude Opus 4.8",
            "intelligence_level": "high",
            "speed_level": "moderate",
            "reasoning_effort_options": ["low", "medium", "high"],
            "source": "fallback",
        },
        {
            "id": "claude-sonnet-4-6",
            "label": "Claude Sonnet 4.6",
            "intelligence_level": "high",
            "speed_level": "fast",
            "reasoning_effort_options": ["low", "medium", "high"],
            "source": "fallback",
        },
        {
            "id": "claude-haiku-4-5",
            "label": "Claude Haiku 4.5",
            "intelligence_level": "near-frontier",
            "speed_level": "fastest",
            "reasoning_effort_options": ["low", "medium", "high"],
            "source": "fallback",
        },
    )

    async def _fetch_model_options(self, *, api_key: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as client:
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            )
            response.raise_for_status()
        data = response.json().get("data", [])
        available_ids = {
            str(item.get("id"))
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        merged = _merge_known_model_metadata(available_ids, self.fallback_model_options)
        names = {str(item.get("id")): str(item.get("display_name")) for item in data if isinstance(item, dict) and item.get("display_name")}
        for option in merged:
            option["label"] = names.get(option["id"], option.get("label") or option["id"])
        return merged

    async def health(self) -> dict[str, Any]:
        return {"status": "shell", "provider_id": self.provider_id, "mode": "deterministic-placeholder"}

    async def draft_spec(self, *, idea: str, model_id: str | None = None) -> dict[str, Any]:
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
        model_id: str | None = None,
    ) -> dict[str, Any]:
        selected_model = model_id if model_id in self.supported_model_ids else self.default_model_id
        return {
            "provider_id": self.provider_id,
            "model_id": selected_model,
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
        model_id: str | None = None,
    ) -> dict[str, Any]:
        selected_model = model_id if model_id in self.supported_model_ids else self.default_model_id
        return {
            "provider_id": self.provider_id,
            "model_id": selected_model,
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


def _is_generation_model_id(model_id: str) -> bool:
    prefixes = ("gpt-5", "gpt-4.1", "o3", "o4")
    return model_id.startswith(prefixes) and not any(fragment in model_id for fragment in ("audio", "transcribe", "tts", "image", "realtime"))


def _merge_known_model_metadata(available_ids: set[str], fallback_options: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    known = {str(option["id"]): dict(option) | {"source": "provider_api"} for option in fallback_options}
    ordered = [known[model_id] for model_id in known if model_id in available_ids]
    unknown = [
        {"id": model_id, "label": model_id, "source": "provider_api"}
        for model_id in sorted(available_ids)
        if model_id not in known
    ]
    return ordered + unknown


def _draft_spec_payload(*, idea: str, provider_label: str) -> dict[str, Any]:
    normalized = " ".join(idea.split())
    title = _detect_title(normalized)
    widget_id = _slugify(title)
    category = _detect_category(normalized)
    min_size, preferred_size = _detect_sizes(normalized)
    refresh_policy = _detect_refresh_policy(normalized, category)
    permissions = _detect_permissions(normalized, category)
    renderer_type = _detect_renderer_type(normalized)
    output_schema = _detect_output_schema(normalized, category)
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
        output_schema=output_schema,
        renderer_type=renderer_type,
        lifecycle_policy={"expires": False, "stateful": True},
    ).model_dump(mode="json") | {"idea_prompt": prompt}


def _slugify(value: str) -> str:
    return sanitize_widget_id(value or "generated_widget")


def _titleize(widget_id: str) -> str:
    return " ".join(part.capitalize() for part in widget_id.split("_")) or "Generated Widget"


def _detect_title(idea: str) -> str:
    quoted = _quoted_text(idea)
    if quoted:
        return quoted
    lowered = idea.lower()
    for suffix in (" widget", " dashboard", " board", " panel", " tracker", " monitor", " feed", " card"):
        index = lowered.find(suffix)
        if index > 0:
            start = max(0, lowered.rfind(" ", 0, index - 1))
            candidate = idea[start:index + len(suffix)].strip(" .,:;-")
            words = candidate.split()
            if len(words) >= 2:
                return _human_title(" ".join(words[-4:]))
    compact = re.sub(r"\b(build|make|create|show|a|an|the|with|for|that|and|using|from)\b", " ", lowered)
    words = [word for word in re.sub(r"[^a-z0-9]+", " ", compact).split() if len(word) > 1]
    return _human_title(" ".join(words[:4]) or "Generated Widget")


def _quoted_text(value: str) -> str | None:
    match = re.search(r"[\"']([^\"']{2,80})[\"']", value)
    if match is None:
        return None
    return _human_title(match.group(1))


def _human_title(value: str) -> str:
    return " ".join(part.capitalize() for part in re.sub(r"[^A-Za-z0-9]+", " ", value).split())


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


def _detect_renderer_type(idea: str) -> str:
    lowered = idea.lower()
    if any(token in lowered for token in ("chart", "graph", "sparkline")):
        return "chart"
    if "table" in lowered:
        return "table"
    if any(token in lowered for token in ("list", "feed", "timeline")):
        return "list"
    return "card"


def _detect_output_schema(idea: str, category: str) -> dict[str, Any]:
    lowered = idea.lower()
    fields: dict[str, Any] = {"summary": "string", "status": "string"}
    for token, field in (
        ("score", "score"),
        ("headline", "headline"),
        ("alert", "alert"),
        ("risk", "risk"),
        ("deadline", "deadline"),
        ("trend", "trend"),
        ("metric", "metric"),
        ("temperature", "temperature"),
        ("count", "count"),
        ("rank", "rank"),
    ):
        if token in lowered:
            fields[field] = "string"
    if category == "sports":
        fields |= {"score": "string", "next_game": "string"}
    if category == "news":
        fields |= {"headline": "string", "source": "string"}
    if category == "trending":
        fields |= {"trend": "string", "rank": "string"}
    if category == "countdown":
        fields |= {"deadline": "string", "remaining": "string"}
    return fields


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
