from __future__ import annotations

import pytest

from gremlinboard_api.registry.loader import validate_widget_package_source
from gremlinboard_api.services.backend_sandbox import dry_run_backend


WIDGET_ID = "sandbox_widget"
CLASS_NAME = "SandboxWidgetService"


def _manifest() -> dict[str, object]:
    return {
        "id": WIDGET_ID,
        "version": "1.0.0",
        "name": "Sandbox Widget",
        "category": "test",
        "description": "Temporary backend sandbox test widget.",
        "min_size": "2x2",
        "preferred_size": "2x2",
        "allowed_sizes": ["2x2"],
        "refresh_policy": {"mode": "manual", "interval_seconds": 0},
        "lifecycle_policy": {"stateful": True, "expires": False, "default_ttl_seconds": None},
        "permissions": [],
        "renderer": {
            "kind": "module",
            "target": "react",
            "module": f"@widgets/{WIDGET_ID}/renderer",
            "export_name": "SandboxWidgetRenderer",
        },
        "service": {
            "kind": "python",
            "module": f"widgets.{WIDGET_ID}.backend",
            "class_name": CLASS_NAME,
        },
        "config_schema": "config.schema.json",
    }


def _backend_source(*, start_body: str = "self.state = await self.get_state()", state_body: str = "return {'status': 'ready'}") -> str:
    return f"""
from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService


class {CLASS_NAME}(BaseWidgetService):
    async def start(self) -> None:
        {start_body}

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {{"status": "running"}}

    async def get_state(self) -> dict[str, object]:
        {state_body}
""".strip() + "\n"


def _skip_if_subprocess_is_blocked(result: dict[str, object]) -> None:
    error = str(result.get("error") or "").lower()
    if "access is denied" in error or "operation not permitted" in error:
        pytest.skip("backend dry-run subprocesses are blocked in this Windows sandbox")


@pytest.mark.parametrize(
    ("backend_source", "match"),
    [
        ("import os\n", "non-allowlisted module"),
        ("eval('1 + 1')\n", "blocked builtin 'eval'"),
        ("exec('value = 1')\n", "blocked builtin 'exec'"),
    ],
)
def test_generated_package_validation_rejects_unsafe_backend_source(backend_source: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        validate_widget_package_source(
            backend_source=backend_source,
            renderer_source="",
            widget_id=WIDGET_ID,
            generated=True,
        )


def test_generated_package_validation_permits_allowlisted_json_and_httpx() -> None:
    validate_widget_package_source(
        backend_source="import json\nimport httpx\n",
        renderer_source="",
        widget_id=WIDGET_ID,
        generated=True,
    )


def test_core_package_validation_keeps_legacy_internal_imports_compatible() -> None:
    validate_widget_package_source(
        backend_source="from gremlinboard_api.services.fixtures import build_news_items\n",
        renderer_source="",
        widget_id="news",
        generated=False,
    )


@pytest.mark.asyncio
async def test_dry_run_backend_returns_service_state_for_temporary_package() -> None:
    result = await dry_run_backend(_backend_source(), _manifest(), config={"enabled": True}, timeout=3.0)

    _skip_if_subprocess_is_blocked(result)

    assert result == {"ok": True, "state": {"status": "ready"}}


@pytest.mark.asyncio
async def test_dry_run_backend_reports_backend_crash() -> None:
    result = await dry_run_backend(
        _backend_source(state_body="raise RuntimeError('dry-run crash')"),
        _manifest(),
        timeout=3.0,
    )

    _skip_if_subprocess_is_blocked(result)

    assert result["ok"] is False
    assert "RuntimeError: dry-run crash" in str(result["error"])


@pytest.mark.asyncio
async def test_dry_run_backend_enforces_timeout_for_temporary_package() -> None:
    result = await dry_run_backend(
        _backend_source(
            state_body="import asyncio\n        await asyncio.sleep(10)\n        return {'status': 'late'}"
        ),
        _manifest(),
        timeout=3.0,
    )

    _skip_if_subprocess_is_blocked(result)

    assert result == {"ok": False, "error": "backend dry-run timed out after 3s"}
