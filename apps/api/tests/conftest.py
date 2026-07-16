from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Must run before gremlinboard_api.config is first imported (its `settings`
# singleton resolves `data_dir` at import time): points the whole test session
# at a throwaway data directory so default-resolution code paths never touch
# the real platform AppData location, and tests never share state with a real
# GremlinBoard installation on this machine.
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="gremlinboard-test-data-"))
os.environ.setdefault("GREMLINBOARD_DATA_DIR", str(_TEST_DATA_DIR))

from gremlinboard_api.ai import cli_clients  # noqa: E402 (must follow the env var above)


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
