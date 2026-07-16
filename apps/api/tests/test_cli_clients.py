from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from gremlinboard_api.ai.clients import AIClientError
from gremlinboard_api.ai.cli_clients import (
    ClaudeCliClient,
    CodexCliClient,
    clear_cli_cache,
    find_cli,
)


def _write_stub(tmp_path: Path, name: str, script_body: str) -> str:
    """Write a python stub script plus an executable shim, return the shim's absolute path.

    Windows gets a .cmd shim; POSIX gets a chmod +x shell script (CI runs on
    Linux, where .cmd files are not executable). All paths embedded in the shim
    are made absolute because the subprocess's cwd differs from the test's cwd.
    """

    stub_py = tmp_path / f"{name}_stub.py"
    stub_py.write_text(textwrap.dedent(script_body), encoding="utf-8")
    python_exe = Path(sys.executable).resolve()

    if os.name == "nt":
        stub_cmd = tmp_path / f"{name}_stub.cmd"
        stub_cmd.write_text(
            f'@echo off\r\n"{python_exe}" "{stub_py.resolve()}" %*\r\n',
            encoding="utf-8",
        )
        return str(stub_cmd.resolve())

    stub_sh = tmp_path / f"{name}_stub.sh"
    stub_sh.write_text(
        f'#!/bin/sh\nexec "{python_exe}" "{stub_py.resolve()}" "$@"\n',
        encoding="utf-8",
    )
    stub_sh.chmod(0o755)
    return str(stub_sh.resolve())


# ---------------------------------------------------------------------------
# ClaudeCliClient
# ---------------------------------------------------------------------------


CLAUDE_ENVELOPE_STUB = """
import json
import sys

envelope = {envelope}
sys.stdout.write(json.dumps(envelope))
sys.exit(0)
"""


@pytest.mark.asyncio
async def test_claude_complete_text_parses_envelope_result(tmp_path: Path) -> None:
    envelope = {"result": "Hello from claude", "usage": {"input_tokens": 5, "output_tokens": 7}}
    binary = _write_stub(
        tmp_path, "claude_ok", CLAUDE_ENVELOPE_STUB.format(envelope=json.dumps(envelope))
    )

    usage_events: list[dict[str, Any]] = []
    client = ClaudeCliClient(binary=binary, timeout=10.0, on_usage=usage_events.append)

    text = await client.complete_text(
        system_prompt="sys",
        user_prompt="user",
        model="claude-test-model",
    )

    assert text == "Hello from claude"
    assert usage_events == [
        {"input_tokens": 5, "output_tokens": 7, "model": "claude-test-model"}
    ]


@pytest.mark.asyncio
async def test_claude_complete_text_tolerates_missing_usage(tmp_path: Path) -> None:
    envelope = {"result": "no usage here"}
    binary = _write_stub(
        tmp_path, "claude_no_usage", CLAUDE_ENVELOPE_STUB.format(envelope=json.dumps(envelope))
    )

    usage_events: list[dict[str, Any]] = []
    client = ClaudeCliClient(binary=binary, timeout=10.0, on_usage=usage_events.append)

    text = await client.complete_text(system_prompt="sys", user_prompt="user", model="m")

    assert text == "no usage here"
    assert usage_events == []


@pytest.mark.asyncio
async def test_claude_complete_json_extracts_fenced_json(tmp_path: Path) -> None:
    fenced_result = '```json\n{"ok": true, "count": 3}\n```'
    envelope = {"result": fenced_result}
    binary = _write_stub(
        tmp_path, "claude_fenced", CLAUDE_ENVELOPE_STUB.format(envelope=json.dumps(envelope))
    )

    client = ClaudeCliClient(binary=binary, timeout=10.0)
    result = await client.complete_json(
        system_prompt="sys",
        user_prompt="user",
        json_schema={"type": "object"},
        model="m",
    )

    assert result == {"ok": True, "count": 3}


@pytest.mark.asyncio
async def test_claude_complete_json_extracts_plain_json(tmp_path: Path) -> None:
    envelope = {"result": '{"ok": true, "count": 9}'}
    binary = _write_stub(
        tmp_path, "claude_plain", CLAUDE_ENVELOPE_STUB.format(envelope=json.dumps(envelope))
    )

    client = ClaudeCliClient(binary=binary, timeout=10.0)
    result = await client.complete_json(
        system_prompt="sys",
        user_prompt="user",
        json_schema={"type": "object"},
        model="m",
    )

    assert result == {"ok": True, "count": 9}


@pytest.mark.asyncio
async def test_claude_nonzero_exit_raises_cli_error(tmp_path: Path) -> None:
    script = """
    import sys
    sys.stderr.write("boom: something went wrong\\n")
    sys.exit(2)
    """
    binary = _write_stub(tmp_path, "claude_fail", script)

    client = ClaudeCliClient(binary=binary, timeout=10.0)
    with pytest.raises(AIClientError) as exc_info:
        await client.complete_text(system_prompt="sys", user_prompt="user", model="m")

    assert exc_info.value.code == "cli_error"
    assert "boom" in exc_info.value.message
    assert exc_info.value.details["returncode"] == 2


@pytest.mark.asyncio
async def test_claude_malformed_output_raises(tmp_path: Path) -> None:
    script = """
    import sys
    sys.stdout.write("not json at all")
    sys.exit(0)
    """
    binary = _write_stub(tmp_path, "claude_malformed", script)

    client = ClaudeCliClient(binary=binary, timeout=10.0)
    with pytest.raises(AIClientError) as exc_info:
        await client.complete_text(system_prompt="sys", user_prompt="user", model="m")

    assert exc_info.value.code == "malformed_output"


@pytest.mark.asyncio
async def test_claude_timeout_raises_and_leaves_no_orphan(tmp_path: Path) -> None:
    script = """
    import time
    time.sleep(30)
    """
    binary = _write_stub(tmp_path, "claude_hang", script)

    client = ClaudeCliClient(binary=binary, timeout=2.0)
    with pytest.raises(AIClientError) as exc_info:
        await client.complete_text(system_prompt="sys", user_prompt="user", model="m")

    assert exc_info.value.code == "timeout"

    try:
        import psutil

        current = psutil.Process(os.getpid())
        children = current.children(recursive=True)
        stray = [
            child
            for child in children
            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE
        ]
        assert stray == []
    except ImportError:
        pass


@pytest.mark.asyncio
async def test_claude_binary_not_found_raises() -> None:
    client = ClaudeCliClient(binary=None, timeout=10.0)
    with pytest.raises(AIClientError) as exc_info:
        await client.complete_text(system_prompt="sys", user_prompt="user", model="m")

    assert exc_info.value.code == "cli_not_found"


# ---------------------------------------------------------------------------
# ClaudeCliClient: argv construction (S4 web research support)
# ---------------------------------------------------------------------------


ARGV_DUMP_STUB = """
import json
import sys

with open(r"{dump_path}", "w", encoding="utf-8") as fh:
    json.dump(sys.argv, fh)

envelope = {envelope}
sys.stdout.write(json.dumps(envelope))
sys.exit(0)
"""


def _write_argv_dump_stub(tmp_path: Path, name: str, dump_path: Path, envelope: dict[str, Any]) -> str:
    return _write_stub(
        tmp_path,
        name,
        ARGV_DUMP_STUB.format(dump_path=str(dump_path.resolve()), envelope=json.dumps(envelope)),
    )


@pytest.mark.asyncio
async def test_claude_complete_text_default_argv_uses_max_turns_1_no_research_flags(tmp_path: Path) -> None:
    # Uses complete_text (not complete_json) because complete_json wraps the user
    # prompt with a multiline schema instruction, and the cmd-shim %* argument
    # passthrough used by these stubs does not survive embedded newlines faithfully.
    dump_path = tmp_path / "argv_default.json"
    binary = _write_argv_dump_stub(tmp_path, "claude_argv_default", dump_path, {"result": "hi"})

    client = ClaudeCliClient(binary=binary, timeout=10.0)
    await client.complete_text(
        system_prompt="sys",
        user_prompt="user",
        model="m",
    )

    argv = json.loads(dump_path.read_text(encoding="utf-8"))
    assert "--max-turns" in argv
    idx = argv.index("--max-turns")
    assert argv[idx + 1] == "1"
    assert "--allowedTools" not in argv


@pytest.mark.asyncio
async def test_claude_complete_text_research_argv_uses_max_turns_12_and_allowed_tools(tmp_path: Path) -> None:
    dump_path = tmp_path / "argv_research_text.json"
    binary = _write_argv_dump_stub(tmp_path, "claude_argv_research_text", dump_path, {"result": "hi"})

    client = ClaudeCliClient(binary=binary, timeout=10.0)
    await client.complete_text(
        system_prompt="sys",
        user_prompt="user",
        model="m",
        allow_web_research=True,
    )

    argv = json.loads(dump_path.read_text(encoding="utf-8"))
    idx = argv.index("--max-turns")
    assert argv[idx + 1] == "12"
    tools_idx = argv.index("--allowedTools")
    assert argv[tools_idx + 1] == "WebSearch"
    assert argv[tools_idx + 2] == "WebFetch"


@pytest.mark.asyncio
async def test_codex_complete_json_accepts_and_ignores_allow_web_research(tmp_path: Path) -> None:
    lines = [
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"ok": true}'},
            }
        ),
    ]
    script = f"""
    import sys
    for line in {lines!r}:
        sys.stdout.write(line + chr(10))
    sys.exit(0)
    """
    binary = _write_stub(tmp_path, "codex_research_kwarg", script)

    client = CodexCliClient(binary=binary, timeout=10.0)
    result = await client.complete_json(
        system_prompt="sys",
        user_prompt="user",
        json_schema={"type": "object"},
        model="m",
        allow_web_research=True,
    )

    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# CodexCliClient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_complete_text_parses_jsonl_events(tmp_path: Path) -> None:
    lines = [
        "this is not json at all {{{",
        json.dumps({"type": "item.started", "item": {"type": "reasoning"}}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Hello from codex"},
            }
        ),
        json.dumps({"type": "token_count", "usage": {"input_tokens": 11, "output_tokens": 22}}),
    ]
    script = f"""
    import sys
    for line in {lines!r}:
        sys.stdout.write(line + chr(10))
    sys.exit(0)
    """
    binary = _write_stub(tmp_path, "codex_ok", script)

    usage_events: list[dict[str, Any]] = []
    client = CodexCliClient(binary=binary, timeout=10.0, on_usage=usage_events.append)

    text = await client.complete_text(system_prompt="sys", user_prompt="user", model="codex-model")

    assert text == "Hello from codex"
    assert usage_events == [
        {"input_tokens": 11, "output_tokens": 22, "model": "codex-model"}
    ]


@pytest.mark.asyncio
async def test_codex_complete_json_extracts_json_from_message(tmp_path: Path) -> None:
    lines = [
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"ok": true, "value": 42}'},
            }
        ),
    ]
    script = f"""
    import sys
    for line in {lines!r}:
        sys.stdout.write(line + chr(10))
    sys.exit(0)
    """
    binary = _write_stub(tmp_path, "codex_json", script)

    client = CodexCliClient(binary=binary, timeout=10.0)
    result = await client.complete_json(
        system_prompt="sys",
        user_prompt="user",
        json_schema={"type": "object"},
        model="m",
    )

    assert result == {"ok": True, "value": 42}


@pytest.mark.asyncio
async def test_codex_no_message_raises_malformed_output(tmp_path: Path) -> None:
    lines = [json.dumps({"type": "item.started", "item": {"type": "reasoning"}})]
    script = f"""
    import sys
    for line in {lines!r}:
        sys.stdout.write(line + chr(10))
    sys.exit(0)
    """
    binary = _write_stub(tmp_path, "codex_nomsg", script)

    client = CodexCliClient(binary=binary, timeout=10.0)
    with pytest.raises(AIClientError) as exc_info:
        await client.complete_text(system_prompt="sys", user_prompt="user", model="m")

    assert exc_info.value.code == "malformed_output"


@pytest.mark.asyncio
async def test_codex_nonzero_exit_raises_cli_error(tmp_path: Path) -> None:
    script = """
    import sys
    sys.stderr.write("codex exploded\\n")
    sys.exit(1)
    """
    binary = _write_stub(tmp_path, "codex_fail", script)

    client = CodexCliClient(binary=binary, timeout=10.0)
    with pytest.raises(AIClientError) as exc_info:
        await client.complete_text(system_prompt="sys", user_prompt="user", model="m")

    assert exc_info.value.code == "cli_error"


@pytest.mark.asyncio
async def test_codex_binary_not_found_raises() -> None:
    client = CodexCliClient(binary=None, timeout=10.0)
    with pytest.raises(AIClientError) as exc_info:
        await client.complete_text(system_prompt="sys", user_prompt="user", model="m")

    assert exc_info.value.code == "cli_not_found"


# ---------------------------------------------------------------------------
# find_cli
# ---------------------------------------------------------------------------


def test_find_cli_explicit_path_wins(tmp_path: Path) -> None:
    fake_binary = tmp_path / "explicit_claude.cmd"
    fake_binary.write_text("@echo off\r\n", encoding="utf-8")

    clear_cli_cache()
    resolved = find_cli("claude", explicit_path=str(fake_binary))
    assert resolved == str(fake_binary)


def test_find_cli_explicit_path_missing_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.cmd"
    clear_cli_cache()
    resolved = find_cli("claude", explicit_path=str(missing))
    assert resolved is None


def test_find_cli_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_binary = tmp_path / "env_claude.cmd"
    fake_binary.write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setenv("GREMLINBOARD_CLAUDE_CLI", str(fake_binary))

    clear_cli_cache()
    resolved = find_cli("claude")
    assert resolved == str(fake_binary)


def test_find_cli_which_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GREMLINBOARD_CLAUDE_CLI", raising=False)
    monkeypatch.setattr(
        "gremlinboard_api.ai.cli_clients.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "claude" else None,
    )

    clear_cli_cache()
    resolved = find_cli("claude")
    assert resolved == "/usr/bin/claude"


def test_find_cli_caches_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GREMLINBOARD_CLAUDE_CLI", raising=False)
    calls = {"count": 0}

    def fake_which(name: str) -> str | None:
        calls["count"] += 1
        return f"/usr/bin/{name}"

    monkeypatch.setattr("gremlinboard_api.ai.cli_clients.shutil.which", fake_which)

    clear_cli_cache()
    first = find_cli("claude")
    second = find_cli("claude")

    assert first == second == "/usr/bin/claude"
    assert calls["count"] == 1

    clear_cli_cache()
    find_cli("claude")
    assert calls["count"] == 2
