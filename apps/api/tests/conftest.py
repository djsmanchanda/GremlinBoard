from __future__ import annotations

import pytest

from gremlinboard_api.ai import cli_clients


@pytest.fixture(autouse=True)
def _default_offline_ai_backend(monkeypatch: pytest.MonkeyPatch):
    """Force AI provider backend resolution to "offline" by default in tests.

    Without this, a provider constructed without explicit credentials or an
    injected client would fall through to `AIProvider._resolve_backend`'s
    "auto" mode, which probes for a local CLI binary (`claude` / `codex`) on
    PATH. The machine running these tests may actually have the `claude` CLI
    installed, which would otherwise cause tests to shell out to a real CLI
    process instead of exercising the deterministic offline fallback they
    expect.

    Tests that specifically exercise "live" or "cli" backend resolution
    override this per-test via ``monkeypatch.setenv("GREMLINBOARD_AI_BACKEND", ...)``.
    Injecting an explicit ``client=`` into a provider always takes precedence
    over this env var regardless.
    """

    monkeypatch.setenv("GREMLINBOARD_AI_BACKEND", "offline")
    cli_clients.clear_cli_cache()
    yield
    cli_clients.clear_cli_cache()
