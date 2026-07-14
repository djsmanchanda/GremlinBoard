from __future__ import annotations

from typing import Any

import pytest

from gremlinboard_api.ai import cli_clients
from gremlinboard_api.ai.clients import AIClientError
from gremlinboard_api.ai.providers import ClaudeProvider, CodexProvider
from gremlinboard_api.schemas.contracts import WidgetSpecDraft


class FakeClient:
    def __init__(
        self,
        *,
        json_responses: list[dict[str, Any]] | None = None,
        text_responses: list[str] | None = None,
        usage_sequence: list[dict[str, Any]] | None = None,
    ) -> None:
        self.json_responses = list(json_responses or [])
        self.text_responses = list(text_responses or [])
        self.usage_sequence = list(usage_sequence or [])
        self.json_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []
        self.on_usage = None

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.json_calls.append(kwargs)
        self._report_usage()
        return self.json_responses.pop(0)

    async def complete_text(self, **kwargs: Any) -> str:
        self.text_calls.append(kwargs)
        self._report_usage()
        return self.text_responses.pop(0)

    def _report_usage(self) -> None:
        if self.usage_sequence and self.on_usage is not None:
            self.on_usage(self.usage_sequence.pop(0))


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


@pytest.mark.asyncio
async def test_draft_spec_aggregates_usage_across_repair_round(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    invalid = valid_spec_payload()
    del invalid["id"]
    fake_client = FakeClient(
        json_responses=[invalid, valid_spec_payload()],
        usage_sequence=[
            {"input_tokens": 100, "output_tokens": 40},
            {"input_tokens": 60, "output_tokens": 25},
        ],
    )
    provider = CodexProvider(credentials={"openai": "test-key"}, client=fake_client)

    result = await provider.draft_spec(idea="show ops status")

    assert result["generation_mode"] == "live"
    assert result["usage"] == {"input_tokens": 160, "output_tokens": 65, "calls": 2}


@pytest.mark.asyncio
async def test_generate_blueprint_reports_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    fake_client = FakeClient(
        json_responses=[valid_blueprint_payload(widget_id="ops_status")],
        usage_sequence=[{"input_tokens": 200, "output_tokens": 90}],
    )
    provider = CodexProvider(credentials={"openai": "test-key"}, client=fake_client)

    result = await provider.generate_blueprint(widget_spec=valid_spec_payload(), model_id="gpt-test")

    assert result["usage"] == {"input_tokens": 200, "output_tokens": 90, "calls": 1}


@pytest.mark.asyncio
async def test_generate_backend_returns_result_with_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    fake_client = FakeClient(
        text_responses=["def handler():\n    return 1\n"],
        usage_sequence=[{"input_tokens": 300, "output_tokens": 150}],
    )
    provider = CodexProvider(credentials={"openai": "test-key"}, client=fake_client)

    result = await provider.generate_backend(widget_spec=valid_spec_payload(), blueprint=valid_blueprint_payload())

    assert result.source == "def handler():\n    return 1"
    assert result.usage == {"input_tokens": 300, "output_tokens": 150, "calls": 1}


@pytest.mark.asyncio
async def test_review_package_live_reports_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    fake_client = FakeClient(
        json_responses=[{"summary": "ok", "issues": [], "requires_human_review": True}],
        usage_sequence=[{"input_tokens": 90, "output_tokens": 20}],
    )
    provider = CodexProvider(credentials={"openai": "test-key"}, client=fake_client)

    result = await provider.review_package(
        widget_spec=valid_spec_payload(),
        package={"manifest": {"id": "ops_status", "version": "0.1.0"}},
    )

    assert result["generation_mode"] == "live"
    assert result["usage"] == {"input_tokens": 90, "output_tokens": 20, "calls": 1}


# ---------------------------------------------------------------------------
# Backend resolution (S2): live (HTTP API) | cli (local agent CLI) | offline
# ---------------------------------------------------------------------------


class FakeCliClient:
    """Stand-in for ClaudeCliClient/CodexCliClient matching the client interface."""

    def __init__(
        self,
        *,
        json_responses: list[dict[str, Any]] | None = None,
        text_responses: list[str] | None = None,
        usage_sequence: list[dict[str, Any]] | None = None,
    ) -> None:
        self.json_responses = list(json_responses or [])
        self.text_responses = list(text_responses or [])
        self.usage_sequence = list(usage_sequence or [])
        self.json_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []
        self.on_usage = None

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.json_calls.append(kwargs)
        self._report_usage()
        return self.json_responses.pop(0)

    async def complete_text(self, **kwargs: Any) -> str:
        self.text_calls.append(kwargs)
        self._report_usage()
        return self.text_responses.pop(0)

    def _report_usage(self) -> None:
        if self.usage_sequence and self.on_usage is not None:
            self.on_usage(self.usage_sequence.pop(0))


@pytest.fixture(autouse=True)
def _clear_cli_cache_for_backend_tests() -> None:
    cli_clients.clear_cli_cache()
    yield
    cli_clients.clear_cli_cache()


def _force_auto_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # The repo-wide conftest fixture defaults GREMLINBOARD_AI_BACKEND to "offline";
    # these tests need to observe the real "auto" resolution precedence.
    monkeypatch.setenv("GREMLINBOARD_AI_BACKEND", "auto")


def test_resolve_backend_api_key_beats_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_auto_backend(monkeypatch)
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: f"/usr/bin/{name}")
    provider = CodexProvider(credentials={"openai": "test-key"})

    backend, client = provider._resolve_backend()

    assert backend == "live"
    assert client is not None


def test_resolve_backend_no_key_cli_found_uses_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_auto_backend(monkeypatch)
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: f"/usr/bin/{name}")
    provider = CodexProvider()

    backend, client = provider._resolve_backend()

    assert backend == "cli"
    assert client is not None


def test_resolve_backend_no_key_no_cli_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_auto_backend(monkeypatch)
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: None)
    provider = CodexProvider()

    backend, client = provider._resolve_backend()

    assert backend == "offline"
    assert client is None


def test_resolve_backend_env_cli_with_key_present_prefers_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GREMLINBOARD_AI_BACKEND", "cli")
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: f"/usr/bin/{name}")
    provider = CodexProvider(credentials={"openai": "test-key"})

    backend, client = provider._resolve_backend()

    assert backend == "cli"
    assert client is not None


def test_resolve_backend_env_api_with_no_key_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GREMLINBOARD_AI_BACKEND", "api")
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: f"/usr/bin/{name}")
    provider = CodexProvider()

    backend, client = provider._resolve_backend()

    assert backend == "offline"
    assert client is None


def test_resolve_backend_env_offline_with_key_and_cli_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GREMLINBOARD_AI_BACKEND", "offline")
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: f"/usr/bin/{name}")
    provider = CodexProvider(credentials={"openai": "test-key"})

    backend, client = provider._resolve_backend()

    assert backend == "offline"
    assert client is None


@pytest.mark.asyncio
async def test_draft_spec_cli_mode_reports_generation_mode_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    _force_auto_backend(monkeypatch)
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: f"/usr/bin/{name}")
    fake_cli_client = FakeCliClient(
        json_responses=[valid_spec_payload()],
        usage_sequence=[{"input_tokens": 50, "output_tokens": 20}],
    )
    monkeypatch.setattr(CodexProvider, "_create_cli_client", lambda self, binary: fake_cli_client)
    provider = CodexProvider()

    result = await provider.draft_spec(idea="show ops status")

    assert result["generation_mode"] == "cli"
    assert result["id"] == "ops_status"
    assert result["usage"] == {"input_tokens": 50, "output_tokens": 20, "calls": 1}


@pytest.mark.asyncio
async def test_generate_blueprint_cli_mode_reports_generation_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    _force_auto_backend(monkeypatch)
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: f"/usr/bin/{name}")
    fake_cli_client = FakeCliClient(json_responses=[valid_blueprint_payload(widget_id="ops_status")])
    monkeypatch.setattr(CodexProvider, "_create_cli_client", lambda self, binary: fake_cli_client)
    provider = CodexProvider()

    result = await provider.generate_blueprint(widget_spec=valid_spec_payload(), model_id="gpt-test")

    assert result["generation_mode"] == "cli"
    assert result["widget_id"] == "ops_status"


@pytest.mark.asyncio
async def test_review_package_cli_mode_uses_claude_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    install_prompt_functions(monkeypatch)
    _force_auto_backend(monkeypatch)
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: f"/usr/bin/{name}")
    fake_cli_client = FakeCliClient(
        json_responses=[{"summary": "ok", "issues": [], "requires_human_review": True}],
        usage_sequence=[{"input_tokens": 10, "output_tokens": 5}],
    )
    monkeypatch.setattr(ClaudeProvider, "_create_cli_client", lambda self, binary: fake_cli_client)
    provider = ClaudeProvider()

    result = await provider.review_package(
        widget_spec=valid_spec_payload(),
        package={"manifest": {"id": "ops_status", "version": "0.1.0"}},
    )

    assert result["generation_mode"] == "cli"
    assert result["usage"] == {"input_tokens": 10, "output_tokens": 5, "calls": 1}


@pytest.mark.asyncio
async def test_health_reports_backend_field(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_auto_backend(monkeypatch)
    monkeypatch.setattr(cli_clients, "find_cli", lambda name, explicit_path=None: None)
    provider = CodexProvider()

    health = await provider.health()

    assert health["backend"] == "offline"
    assert health["mode"] == "offline"