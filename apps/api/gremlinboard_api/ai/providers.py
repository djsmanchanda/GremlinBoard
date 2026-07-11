from __future__ import annotations

import ast
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import re
import time
from typing import Any

import httpx
from pydantic import ValidationError

from gremlinboard_api.ai.clients import AIClientError, AnthropicClient, OpenAIClient
from gremlinboard_api.schemas.blueprint import validate_blueprint
from gremlinboard_api.schemas.contracts import WidgetSpecDraft
from gremlinboard_api.specs.widget_ids import sanitize_widget_id


CredentialsGetter = Callable[[], dict[str, str]]


@dataclass(frozen=True)
class BackendGenerationResult:
    """Result of a live backend codegen call, carrying aggregated token usage."""

    source: str
    usage: dict[str, int] | None = None


class _UsageTracker:
    """Accumulates token usage across the calls (including repair rounds) made in one provider method."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def record(self, payload: dict[str, Any]) -> None:
        self.input_tokens += int(payload.get("input_tokens") or 0)
        self.output_tokens += int(payload.get("output_tokens") or 0)
        self.calls += 1

    def as_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "calls": self.calls}


def _attach_usage_tracker(client: Any, tracker: _UsageTracker) -> None:
    try:
        client.on_usage = tracker.record
    except AttributeError:
        pass


def _combine_usage(*usages: dict[str, Any] | None) -> dict[str, int] | None:
    combined = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    found = False
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        found = True
        combined["input_tokens"] += int(usage.get("input_tokens") or 0)
        combined["output_tokens"] += int(usage.get("output_tokens") or 0)
        combined["calls"] += int(usage.get("calls") or 0)
    return combined if found else None


class AIProvider(ABC):
    provider_id: str
    label: str
    supported_model_ids: tuple[str, ...] = ()
    default_model_id: str | None = None
    fallback_model_options: tuple[dict[str, Any], ...] = ()
    model_api_credential_providers: tuple[str, ...] = ()
    model_cache_ttl_seconds = 600
    _model_cache: tuple[list[dict[str, Any]], str, str, float, str] | None = None

    def __init__(
        self,
        *,
        credentials: dict[str, str] | None = None,
        credentials_getter: CredentialsGetter | None = None,
        client: Any | None = None,
    ) -> None:
        self._credentials = dict(credentials or {})
        self._credentials_getter = credentials_getter
        self._client = client

    @property
    def supports_idea_to_spec(self) -> bool:
        return True

    @property
    def supports_codegen(self) -> bool:
        return True

    @property
    def supports_review(self) -> bool:
        return True

    def set_credentials(self, credentials: dict[str, str]) -> None:
        self._credentials = dict(credentials)
        self._model_cache = None

    async def health(self) -> dict[str, Any]:
        mode = "live" if self._api_key() else "offline"
        return {"status": "available", "provider_id": self.provider_id, "mode": mode}

    async def draft_spec(
        self,
        *,
        idea: str,
        model_id: str | None = None,
        reasoning_effort: str | None = "medium",
    ) -> dict[str, Any]:
        selected_model = self._resolve_model(model_id)
        api_key = self._api_key()
        if not api_key:
            payload = self._offline_draft_spec(idea=idea)
            idea_prompt = str(payload.pop("idea_prompt", ""))
            return _SpecResult(
                payload,
                {"generation_mode": "offline", "model_id": selected_model, "idea_prompt": idea_prompt},
            )

        system_prompt = _prompt_call("spec_system_prompt")
        user_prompt = _prompt_call("spec_user_prompt", idea=idea)
        schema = _prompt_call("spec_output_schema")
        client = self._live_client(api_key)
        tracker = _UsageTracker()
        _attach_usage_tracker(client, tracker)
        raw = await client.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_schema=schema,
            model=selected_model,
            reasoning_effort=reasoning_effort,
        )
        spec = await self._validate_spec_with_repair(
            raw,
            client=client,
            model_id=selected_model,
            system_prompt=system_prompt,
            schema=schema,
            reasoning_effort=reasoning_effort,
        )
        payload = spec.model_dump(mode="json")
        return _SpecResult(
            payload,
            {
                "generation_mode": "live",
                "model_id": selected_model,
                "idea_prompt": user_prompt,
                "usage": tracker.as_dict(),
            },
        )

    async def generate_blueprint(
        self,
        *,
        widget_spec: dict[str, Any] | WidgetSpecDraft,
        model_id: str | None = None,
        reasoning_effort: str | None = "medium",
    ) -> dict[str, Any]:
        api_key = self._api_key()
        if not api_key:
            raise NotImplementedError("offline blueprint generation is handled by the generation pipeline fallback")
        spec = WidgetSpecDraft.model_validate(widget_spec)
        selected_model = self._resolve_model(model_id)
        schema = _blueprint_schema()
        system_prompt = _prompt_call("blueprint_system_prompt")
        user_prompt = _prompt_call("blueprint_user_prompt", spec=spec.model_dump(mode="json"))
        client = self._live_client(api_key)
        tracker = _UsageTracker()
        _attach_usage_tracker(client, tracker)
        raw = await client.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_schema=schema,
            model=selected_model,
            reasoning_effort=reasoning_effort,
        )
        blueprint = await self._validate_blueprint_with_repair(
            raw,
            spec=spec,
            client=client,
            model_id=selected_model,
            system_prompt=system_prompt,
            schema=schema,
            reasoning_effort=reasoning_effort,
        )
        return blueprint.model_dump(mode="json") | {
            "generation_mode": "live",
            "model_id": selected_model,
            "usage": tracker.as_dict(),
        }

    async def generate_backend(
        self,
        *,
        widget_spec: dict[str, Any] | WidgetSpecDraft,
        blueprint: dict[str, Any],
        model_id: str | None = None,
        reasoning_effort: str | None = "medium",
    ) -> BackendGenerationResult:
        api_key = self._api_key()
        if not api_key:
            raise NotImplementedError("offline backend generation is handled by the generation pipeline fallback")
        spec = WidgetSpecDraft.model_validate(widget_spec)
        selected_model = self._resolve_model(model_id)
        system_prompt = _prompt_call("backend_system_prompt")
        user_prompt = _prompt_call("backend_user_prompt", spec=spec.model_dump(mode="json"), blueprint=blueprint)
        client = self._live_client(api_key)
        tracker = _UsageTracker()
        _attach_usage_tracker(client, tracker)
        text = await client.complete_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=selected_model,
            reasoning_effort=reasoning_effort,
        )
        source = await self._validate_backend_with_repair(
            text,
            client=client,
            model_id=selected_model,
            system_prompt=system_prompt,
            reasoning_effort=reasoning_effort,
        )
        return BackendGenerationResult(source=source, usage=tracker.as_dict())
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
        reasoning_effort: str | None = "medium",
    ) -> dict[str, Any]:
        selected_model = self._resolve_model(model_id)
        mode = "live" if self._api_key() else "offline"
        return {
            "provider_id": self.provider_id,
            "model_id": selected_model,
            "generation_mode": mode,
            "reasoning_effort": reasoning_effort,
            "prompt": _legacy_codegen_prompt(spec=widget_spec, scaffold_files=scaffold_files),
            "notes": self._codegen_notes(selected_model=selected_model, generation_mode=mode),
        }

    async def review_package(
        self,
        *,
        widget_spec: dict[str, Any],
        package: dict[str, Any],
        model_id: str | None = None,
        reasoning_effort: str | None = "medium",
    ) -> dict[str, Any]:
        selected_model = self._resolve_model(model_id)
        api_key = self._api_key()
        if not api_key:
            return self._offline_review(widget_spec=widget_spec, package=package, selected_model=selected_model)

        client = self._live_client(api_key)
        tracker = _UsageTracker()
        _attach_usage_tracker(client, tracker)
        result = await client.complete_json(
            system_prompt=_prompt_call("review_system_prompt"),
            user_prompt=_prompt_call("review_user_prompt", spec=widget_spec, package=package),
            json_schema=_prompt_call("review_output_schema"),
            model=selected_model,
            reasoning_effort=reasoning_effort,
        )
        return result | {
            "provider_id": self.provider_id,
            "model_id": selected_model,
            "generation_mode": "live",
            "usage": tracker.as_dict(),
        }

    async def list_model_options(self, *, credentials: dict[str, str]) -> tuple[list[dict[str, Any]], str, str]:
        self.set_credentials(credentials)
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

    def _live_client(self, api_key: str) -> Any:
        if self._client is not None:
            return self._client
        return self._create_client(api_key)

    def _create_client(self, api_key: str) -> Any:
        raise NotImplementedError

    def _credentials_snapshot(self) -> dict[str, str]:
        values = dict(self._credentials)
        if self._credentials_getter is not None:
            values |= dict(self._credentials_getter())
        return values

    def _api_key(self) -> str | None:
        return self._credential_for(self._credentials_snapshot())

    def _credential_for(self, credentials: dict[str, str]) -> str | None:
        for provider_id in self.model_api_credential_providers:
            secret = credentials.get(provider_id)
            if secret:
                return secret
        return None

    def _resolve_model(self, model_id: str | None) -> str:
        if model_id:
            return model_id
        return self.default_model_id or self.supported_model_ids[0]

    def _offline_draft_spec(self, *, idea: str) -> dict[str, Any]:
        return _draft_spec_payload(idea=idea, provider_label=self.label)

    def _codegen_notes(self, *, selected_model: str, generation_mode: str) -> list[str]:
        return [
            f"{self.label} scaffold handoff prepared with requested model '{selected_model}'.",
            f"Provider is in {generation_mode} mode for this pipeline-compatible handoff.",
            "Install remains blocked pending review.",
        ]

    def _offline_review(self, *, widget_spec: dict[str, Any], package: dict[str, Any], selected_model: str) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model_id": selected_model,
            "generation_mode": "offline",
            "prompt": _legacy_review_prompt(spec=widget_spec, package=package),
            "summary": "Contract-focused review shell completed. Human approval is still required.",
            "issues": [],
            "checklist": [
                "Manifest uses supported fixed sizes only.",
                "Service contract includes start/stop/health/get_state.",
                "Generated install is blocked until explicit approval.",
            ],
            "requires_human_review": True,
        }

    async def _validate_spec_with_repair(
        self,
        raw: dict[str, Any],
        *,
        client: Any,
        model_id: str,
        system_prompt: str,
        schema: dict[str, Any],
        reasoning_effort: str | None,
    ) -> WidgetSpecDraft:
        try:
            return WidgetSpecDraft.model_validate(raw)
        except ValidationError as first_error:
            repair = await client.complete_json(
                system_prompt=system_prompt,
                user_prompt=_prompt_call("repair_user_prompt", stage="spec", errors=_validation_errors(first_error)),
                json_schema=schema,
                model=model_id,
                reasoning_effort=reasoning_effort,
            )
            try:
                return WidgetSpecDraft.model_validate(repair)
            except ValidationError as second_error:
                raise AIClientError(
                    "invalid_spec",
                    "LLM returned an invalid widget spec after one repair round.",
                    {"errors": _validation_errors(second_error)},
                ) from second_error
    async def _validate_blueprint_with_repair(
        self,
        raw: dict[str, Any],
        *,
        spec: WidgetSpecDraft,
        client: Any,
        model_id: str,
        system_prompt: str,
        schema: dict[str, Any],
        reasoning_effort: str | None,
    ):
        try:
            return validate_blueprint(_patch_blueprint_widget_id(raw, spec.id))
        except ValueError as first_error:
            repair = await client.complete_json(
                system_prompt=system_prompt,
                user_prompt=_prompt_call("repair_user_prompt", stage="blueprint", errors=str(first_error)),
                json_schema=schema,
                model=model_id,
                reasoning_effort=reasoning_effort,
            )
            try:
                return validate_blueprint(_patch_blueprint_widget_id(repair, spec.id))
            except ValueError as second_error:
                raise AIClientError(
                    "invalid_blueprint",
                    "LLM returned an invalid blueprint after one repair round.",
                    {"errors": str(second_error)},
                ) from second_error

    async def _validate_backend_with_repair(
        self,
        text: str,
        *,
        client: Any,
        model_id: str,
        system_prompt: str,
        reasoning_effort: str | None,
    ) -> str:
        source = _strip_single_python_fence(text)
        try:
            ast.parse(source)
            return source
        except SyntaxError as first_error:
            repaired = await client.complete_text(
                system_prompt=system_prompt,
                user_prompt=_prompt_call("repair_user_prompt", stage="backend", errors=str(first_error)),
                model=model_id,
                reasoning_effort=reasoning_effort,
            )
            source = _strip_single_python_fence(repaired)
            try:
                ast.parse(source)
                return source
            except SyntaxError as second_error:
                raise AIClientError(
                    "invalid_backend",
                    "LLM returned non-compiling Python after one repair round.",
                    {"errors": str(second_error)},
                ) from second_error


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

    def _create_client(self, api_key: str) -> OpenAIClient:
        return OpenAIClient(api_key=api_key)

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


class ClaudeProvider(AIProvider):
    provider_id = "claude"
    label = "Claude"
    supported_model_ids = ("claude-fable-5", "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5")
    default_model_id = "claude-fable-5"
    model_api_credential_providers = ("claude", "anthropic")
    fallback_model_options = (
        {"id": "claude-fable-5", "label": "Claude Fable 5", "intelligence_level": "highest", "speed_level": "moderate", "source": "fallback"},
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

    def _create_client(self, api_key: str) -> AnthropicClient:
        return AnthropicClient(api_key=api_key)

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

    def _offline_draft_spec(self, *, idea: str) -> dict[str, Any]:
        payload = _draft_spec_payload(idea=idea, provider_label=self.label)
        payload["description"] = f"{payload['description']} Generated through the staged spec shell."
        return payload

    def _codegen_notes(self, *, selected_model: str, generation_mode: str) -> list[str]:
        return [
            "Claude shell prepared a regeneration-oriented codegen prompt.",
            f"Provider is in {generation_mode} mode for requested model '{selected_model}'.",
            "Artifacts are versioned before any install action is available.",
        ]

    def _offline_review(self, *, widget_spec: dict[str, Any], package: dict[str, Any], selected_model: str) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model_id": selected_model,
            "generation_mode": "offline",
            "prompt": _legacy_review_prompt(spec=widget_spec, package=package),
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


class _SpecResult(dict[str, Any]):
    def __init__(self, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
        super().__init__(payload)
        self._metadata = dict(metadata)

    def __getitem__(self, key: str) -> Any:
        if key in self._metadata:
            return self._metadata[key]
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._metadata:
            return self._metadata[key]
        return super().get(key, default)

    def pop(self, key: str, default: Any = None) -> Any:
        if key in self._metadata:
            return self._metadata.pop(key)
        return super().pop(key, default)


def _prompt_call(name: str, **kwargs: Any) -> Any:
    prompts = importlib.import_module("gremlinboard_api.ai.prompts")
    fn = getattr(prompts, name, None)
    if not callable(fn):
        raise AIClientError("prompt_unavailable", f"ai.prompts.{name} is not available yet.")
    return fn(**kwargs)


def _legacy_idea_prompt(*, idea: str) -> str:
    prompts = importlib.import_module("gremlinboard_api.ai.prompts")
    fn = getattr(prompts, "render_idea_to_spec_prompt", None)
    if callable(fn):
        return str(fn(idea=idea))
    return f"Idea:\n{idea.strip()}"


def _legacy_codegen_prompt(*, spec: dict[str, Any], scaffold_files: list[str]) -> str:
    prompts = importlib.import_module("gremlinboard_api.ai.prompts")
    fn = getattr(prompts, "render_codegen_prompt", None)
    if callable(fn):
        return str(fn(spec=spec, scaffold_files=scaffold_files))
    return "Spec:\n" + json.dumps(spec, indent=2, sort_keys=True)


def _legacy_review_prompt(*, spec: dict[str, Any], package: dict[str, Any]) -> str:
    prompts = importlib.import_module("gremlinboard_api.ai.prompts")
    fn = getattr(prompts, "render_review_prompt", None)
    if callable(fn):
        return str(fn(spec=spec, package=package))
    return "Review package:\n" + json.dumps({"spec": spec, "package": package}, indent=2, sort_keys=True)


def _blueprint_schema() -> dict[str, Any]:
    schema_path = Path(__file__).resolve().parents[4] / "schemas" / "widget-blueprint.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8-sig"))


def _patch_blueprint_widget_id(data: dict[str, Any], widget_id: str) -> dict[str, Any]:
    patched = dict(data)
    patched["widget_id"] = widget_id
    return patched


def _strip_single_python_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:python)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else stripped


def _validation_errors(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors())


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
    ).model_dump(mode="json") | {"idea_prompt": _legacy_idea_prompt(idea=idea)}


def _slugify(value: str) -> str:
    return sanitize_widget_id(value or "generated_widget")


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