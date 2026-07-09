from __future__ import annotations

from typing import Any

import pytest

from gremlinboard_api.ai.clients import AIClientError
from gremlinboard_api.ai.providers import CodexProvider
from gremlinboard_api.schemas.contracts import WidgetSpecDraft


class FakeClient:
    def __init__(
        self,
        *,
        json_responses: list[dict[str, Any]] | None = None,
        text_responses: list[str] | None = None,
    ) -> None:
        self.json_responses = list(json_responses or [])
        self.text_responses = list(text_responses or [])
        self.json_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.json_calls.append(kwargs)
        return self.json_responses.pop(0)

    async def complete_text(self, **kwargs: Any) -> str:
        self.text_calls.append(kwargs)
        return self.text_responses.pop(0)


def valid_spec_payload() -> dict[str, Any]:
    return {
        "id": "ops_status",
        "name": "Ops Status",
        "category": "custom",
        "description": "Operational status snapshot",
        "min_size": "2x2",
        "preferred_size": "4x2",
        "refresh_policy": {"mode": "interval", "interval_seconds": 300},
        "source_type": "generated",
        "permissions": ["network"],
        "output_schema": {"summary": "string", "status": "string"},
        "renderer_type": "card",
        "lifecycle_policy": {"expires": False, "stateful": True},
    }


def valid_blueprint_payload(widget_id: str = "ops_status") -> dict[str, Any]:
    return {
        "blueprint_version": "1",
        "widget_id": widget_id,
        "layouts": {"medium": {"type": "text", "literal": "Ops", "variant": "title"}},
    }


def install_prompt_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    import gremlinboard_api.ai.prompts as prompts

    monkeypatch.setattr(prompts, "spec_system_prompt", lambda: "spec system", raising=False)
    monkeypatch.setattr(prompts, "spec_user_prompt", lambda *, idea: f"spec user: {idea}", raising=False)
    monkeypatch.setattr(prompts, "spec_output_schema", lambda: {"type": "object"}, raising=False)
    monkeypatch.setattr(prompts, "blueprint_system_prompt", lambda: "blueprint system", raising=False)
    monkeypatch.setattr(prompts, "blueprint_user_prompt", lambda *, spec: f"blueprint user: {spec['id']}", raising=False)
    monkeypatch.setattr(prompts, "backend_system_prompt", lambda: "backend system", raising=False)
    monkeypatch.setattr(
        prompts,
        "backend_user_prompt",
        lambda *, spec, blueprint: f"backend user: {spec['id']} {blueprint['widget_id']}",
        raising=False,
    )
    monkeypatch.setattr(prompts, "review_system_prompt", lambda: "review system", raising=False)
    monkeypatch.setattr(prompts, "review_user_prompt", lambda *, spec, package: f"review user: {spec['id']}", raising=False)
    monkeypatch.setattr(prompts, "review_output_schema", lambda: {"type": "object"}, raising=False)
    monkeypatch.setattr(prompts, "repair_user_prompt", lambda *, stage, errors: f"repair {stage}: {errors}", raising=False)


@pytest.mark.asyncio
async def test_draft_spec_live_returns_validated_spec_with_generation_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    fake_client = FakeClient(json_responses=[valid_spec_payload()])
    provider = CodexProvider(credentials={"openai": "test-key"}, client=fake_client)

    result = await provider.draft_spec(idea="show ops status", model_id="gpt-test", reasoning_effort="high")

    assert result["id"] == "ops_status"
    assert result["generation_mode"] == "live"
    assert result["model_id"] == "gpt-test"
    assert WidgetSpecDraft.model_validate(result).id == "ops_status"
    assert fake_client.json_calls[0]["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_draft_spec_repairs_first_invalid_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    invalid = valid_spec_payload()
    del invalid["id"]
    fake_client = FakeClient(json_responses=[invalid, valid_spec_payload()])
    provider = CodexProvider(credentials={"openai": "test-key"}, client=fake_client)

    result = await provider.draft_spec(idea="show ops status")

    assert result["generation_mode"] == "live"
    assert result["id"] == "ops_status"
    assert len(fake_client.json_calls) == 2
    assert fake_client.json_calls[1]["user_prompt"].startswith("repair spec:")


@pytest.mark.asyncio
async def test_draft_spec_offline_without_credentials_uses_deterministic_fallback() -> None:
    provider = CodexProvider()

    result = await provider.draft_spec(idea='Build a wide "Sprint Risk" dashboard with trend chart.')

    assert result["generation_mode"] == "offline"
    assert result["model_id"] == "gpt-5.5"
    assert result["id"] == "sprint_risk"
    assert result["preferred_size"] == "4x2"
    assert WidgetSpecDraft.model_validate(result).id == "sprint_risk"


@pytest.mark.asyncio
async def test_generate_blueprint_validates_schema_and_patches_widget_id(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    fake_client = FakeClient(json_responses=[valid_blueprint_payload(widget_id="wrong_id")])
    provider = CodexProvider(credentials={"openai": "test-key"}, client=fake_client)

    result = await provider.generate_blueprint(widget_spec=valid_spec_payload(), model_id="gpt-test")

    assert result["widget_id"] == "ops_status"
    assert result["generation_mode"] == "live"
    assert result["layouts"]["medium"]["type"] == "text"
    assert fake_client.json_calls[0]["json_schema"]["$id"].endswith("widget-blueprint.schema.json")


@pytest.mark.asyncio
async def test_generate_backend_rejects_non_compiling_code_after_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    fake_client = FakeClient(text_responses=["def bad(:\n    pass", "def still_bad(:\n    pass"])
    provider = CodexProvider(credentials={"openai": "test-key"}, client=fake_client)

    with pytest.raises(AIClientError) as exc_info:
        await provider.generate_backend(widget_spec=valid_spec_payload(), blueprint=valid_blueprint_payload())

    assert exc_info.value.code == "invalid_backend"
    assert len(fake_client.text_calls) == 2
    assert fake_client.text_calls[1]["user_prompt"].startswith("repair backend:")


@pytest.mark.asyncio
async def test_review_package_offline_marks_generation_mode() -> None:
    provider = CodexProvider()

    result = await provider.review_package(
        widget_spec=valid_spec_payload(),
        package={"manifest": {"id": "ops_status", "version": "0.1.0"}},
    )

    assert result["generation_mode"] == "offline"
    assert result["requires_human_review"] is True