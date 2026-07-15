from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

from .clients import AIClientError, UsageCallback

# ---------------------------------------------------------------------------
# CLI resolution
# ---------------------------------------------------------------------------

_CLI_ENV_VARS = {
    "claude": "GREMLINBOARD_CLAUDE_CLI",
    "codex": "GREMLINBOARD_CODEX_CLI",
}

_CLI_CACHE_TTL = 60.0
_cli_cache: dict[str, tuple[float, str | None]] = {}


def clear_cli_cache() -> None:
    """Clear the module-level TTL cache used by :func:`find_cli`. Test helper."""

    _cli_cache.clear()


def find_cli(name: str, explicit_path: str | None = None) -> str | None:
    """Resolve the path to a CLI binary.

    Resolution order:
      1. ``explicit_path`` if given (validated to exist).
      2. An environment variable override (``GREMLINBOARD_CLAUDE_CLI`` /
         ``GREMLINBOARD_CODEX_CLI``), depending on ``name``.
      3. ``shutil.which(name)``.

    Results (including negative ones) are cached per-name for
    :data:`_CLI_CACHE_TTL` seconds so repeated availability checks don't
    repeatedly hit the filesystem/PATH lookup.
    """

    if explicit_path is not None:
        if os.path.exists(explicit_path):
            return explicit_path
        return None

    now = time.monotonic()
    cached = _cli_cache.get(name)
    if cached is not None:
        cached_at, cached_value = cached
        if now - cached_at < _CLI_CACHE_TTL:
            return cached_value

    env_var = _CLI_ENV_VARS.get(name)
    env_value = os.environ.get(env_var) if env_var else None
    if env_value:
        resolved = env_value
    else:
        resolved = shutil.which(name)

    _cli_cache[name] = (now, resolved)
    return resolved


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _clean_child_env() -> dict[str, str]:
    """Environment for spawned agent CLIs.

    The API server can itself be a descendant of a Claude Code session (tray
    launched from a Claude-driven shell), and inherited nested-session markers
    (CLAUDECODE, CLAUDE_CODE_*) make the child CLI behave as if it were running
    inside another session. Strip them so headless runs are independent.
    """

    return {
        key: value
        for key, value in os.environ.items()
        if key != "CLAUDECODE" and not key.startswith("CLAUDE_CODE_")
    }


def _schema_instruction(json_schema: dict[str, Any]) -> str:
    return (
        "\n\n---\n"
        "Respond with a single JSON object matching this schema exactly. "
        "No prose, no markdown fences.\n"
        f"Schema: {json.dumps(json_schema)}"
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from CLI output text.

    Strips a single leading/trailing markdown fence (optionally ```json),
    then narrows to the substring between the first ``{`` and the last
    ``}`` before parsing.
    """

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise AIClientError(
            "malformed_output",
            "CLI output did not contain a JSON object.",
            {"output_sample": stripped[:500]},
        )
    candidate = stripped[start : end + 1]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AIClientError(
            "malformed_output",
            "CLI output was not valid JSON.",
            {"output_sample": stripped[:500]},
        ) from exc
    if not isinstance(value, dict):
        raise AIClientError(
            "malformed_output",
            "CLI JSON output was not an object.",
            {"output_type": type(value).__name__},
        )
    return value


def _reasoning_effort_thinking_tokens(reasoning_effort: str | None) -> str | None:
    if reasoning_effort is None:
        return None
    effort = reasoning_effort.lower()
    if effort == "low":
        return None
    if effort == "medium":
        return "4096"
    if effort == "high":
        return "12288"
    return None


def _run_subprocess(
    argv: list[str],
    *,
    timeout: float,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        cwd=cwd,
    )


def _report_usage_ints(
    on_usage: UsageCallback | None,
    *,
    input_tokens: Any,
    output_tokens: Any,
    model: str,
) -> None:
    if on_usage is None:
        return
    if input_tokens is None and output_tokens is None:
        return
    try:
        on_usage(
            {
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "model": model,
            }
        )
    except (TypeError, ValueError):
        pass


def _find_usage_dict(obj: Any) -> dict[str, Any] | None:
    """Defensively search a parsed JSON value for a usage-like dict."""

    if isinstance(obj, dict):
        usage = obj.get("usage")
        if isinstance(usage, dict):
            return usage
        for value in obj.values():
            found = _find_usage_dict(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_usage_dict(item)
            if found is not None:
                return found
    return None


def _usage_tokens(usage: dict[str, Any]) -> tuple[Any, Any]:
    input_tokens = (
        usage.get("input_tokens")
        if usage.get("input_tokens") is not None
        else usage.get("prompt_tokens")
    )
    output_tokens = (
        usage.get("output_tokens")
        if usage.get("output_tokens") is not None
        else usage.get("completion_tokens")
    )
    return input_tokens, output_tokens


# ---------------------------------------------------------------------------
# Claude Code CLI client
# ---------------------------------------------------------------------------


class ClaudeCliClient:
    """Drop-in LLM client that shells out to the ``claude`` CLI."""

    def __init__(
        self,
        *,
        binary: str | None = None,
        timeout: float = 300.0,
        on_usage: UsageCallback | None = None,
    ) -> None:
        self.binary = binary
        self.timeout = timeout
        self.on_usage = on_usage

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 8192,
        temperature: float | None = None,
        reasoning_effort: str | None = "medium",
        allow_web_research: bool = False,
    ) -> str:
        envelope = await self._invoke(
            system_prompt, user_prompt, model, reasoning_effort, allow_web_research=allow_web_research
        )
        return self._extract_result_text(envelope, model)

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        model: str,
        max_tokens: int = 8192,
        temperature: float | None = None,
        reasoning_effort: str | None = "medium",
        allow_web_research: bool = False,
    ) -> dict[str, Any]:
        wrapped_prompt = user_prompt + _schema_instruction(json_schema)
        envelope = await self._invoke(
            system_prompt, wrapped_prompt, model, reasoning_effort, allow_web_research=allow_web_research
        )
        text = self._extract_result_text(envelope, model)
        return _extract_json_object(text)

    async def _invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        reasoning_effort: str | None,
        *,
        allow_web_research: bool = False,
    ) -> dict[str, Any]:
        binary = self.binary
        if not binary:
            raise AIClientError(
                "cli_not_found",
                "Claude Code CLI binary was not found.",
                {"argv0": self.binary},
            )

        argv = [
            binary,
            "-p",
            user_prompt,
            "--system-prompt",
            system_prompt,
            "--output-format",
            "json",
            "--model",
            model,
        ]
        if allow_web_research:
            argv.extend(["--max-turns", "12", "--allowedTools", "WebSearch", "WebFetch"])
        else:
            argv.extend(["--max-turns", "1"])

        env = _clean_child_env()
        thinking_tokens = _reasoning_effort_thinking_tokens(reasoning_effort)
        if thinking_tokens is not None:
            env["MAX_THINKING_TOKENS"] = thinking_tokens
        else:
            env.pop("MAX_THINKING_TOKENS", None)

        try:
            completed = await asyncio.to_thread(
                _run_subprocess, argv, timeout=self.timeout, env=env
            )
        except FileNotFoundError as exc:
            raise AIClientError(
                "cli_not_found",
                "Claude Code CLI binary could not be executed.",
                {"argv0": argv[0]},
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AIClientError(
                "timeout",
                f"Claude Code CLI timed out after {self.timeout:g}s.",
                {"argv0": argv[0]},
            ) from exc

        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "").strip()[-2000:]
            raise AIClientError(
                "cli_error",
                stderr_tail or f"Claude Code CLI exited with code {completed.returncode}.",
                {"argv0": argv[0], "returncode": completed.returncode},
            )

        stdout_text = completed.stdout or ""
        try:
            envelope = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            raise AIClientError(
                "malformed_output",
                "Claude Code CLI did not return valid JSON.",
                {"output_sample": stdout_text.strip()[:500]},
            ) from exc
        if not isinstance(envelope, dict):
            raise AIClientError(
                "malformed_output",
                "Claude Code CLI JSON output was not an object.",
                {"output_type": type(envelope).__name__},
            )
        return envelope

    def _extract_result_text(self, envelope: dict[str, Any], model: str) -> str:
        usage = envelope.get("usage")
        if isinstance(usage, dict):
            input_tokens, output_tokens = _usage_tokens(usage)
            _report_usage_ints(
                self.on_usage, input_tokens=input_tokens, output_tokens=output_tokens, model=model
            )

        result = envelope.get("result")
        if isinstance(result, str) and result.strip():
            return result
        content = envelope.get("content")
        if isinstance(content, str) and content.strip():
            return content
        text = envelope.get("text")
        if isinstance(text, str) and text.strip():
            return text
        raise AIClientError(
            "malformed_output",
            "Claude Code CLI response envelope did not contain result text.",
            {"output_sample": json.dumps(envelope)[:500]},
        )


# ---------------------------------------------------------------------------
# Codex CLI client
# ---------------------------------------------------------------------------


class CodexCliClient:
    """Drop-in LLM client that shells out to the ``codex`` CLI."""

    def __init__(
        self,
        *,
        binary: str | None = None,
        timeout: float = 300.0,
        on_usage: UsageCallback | None = None,
    ) -> None:
        self.binary = binary
        self.timeout = timeout
        self.on_usage = on_usage

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 8192,
        temperature: float | None = None,
        reasoning_effort: str | None = "medium",
        allow_web_research: bool = False,
    ) -> str:
        # allow_web_research is accepted for signature parity with ClaudeCliClient but
        # ignored: `codex exec` gets no research-specific flags for now.
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        events = await self._invoke(combined_prompt, model, reasoning_effort)
        return self._extract_message_text(events, model)

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        model: str,
        max_tokens: int = 8192,
        temperature: float | None = None,
        reasoning_effort: str | None = "medium",
        allow_web_research: bool = False,
    ) -> dict[str, Any]:
        # allow_web_research is accepted for signature parity with ClaudeCliClient but
        # ignored: `codex exec` gets no research-specific flags for now.
        combined_prompt = f"{system_prompt}\n\n{user_prompt}" + _schema_instruction(json_schema)
        events = await self._invoke(combined_prompt, model, reasoning_effort)
        text = self._extract_message_text(events, model)
        return _extract_json_object(text)

    async def _invoke(
        self,
        combined_prompt: str,
        model: str,
        reasoning_effort: str | None,
    ) -> list[dict[str, Any]]:
        binary = self.binary
        if not binary:
            raise AIClientError(
                "cli_not_found",
                "Codex CLI binary was not found.",
                {"argv0": self.binary},
            )

        argv = [
            binary,
            "exec",
            combined_prompt,
            "--json",
            "--skip-git-repo-check",
            "-m",
            model,
            "--sandbox",
            "read-only",
        ]
        if reasoning_effort is not None:
            argv.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])

        neutral_cwd = tempfile.gettempdir()

        try:
            completed = await asyncio.to_thread(
                _run_subprocess, argv, timeout=self.timeout, cwd=neutral_cwd
            )
        except FileNotFoundError as exc:
            raise AIClientError(
                "cli_not_found",
                "Codex CLI binary could not be executed.",
                {"argv0": argv[0]},
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AIClientError(
                "timeout",
                f"Codex CLI timed out after {self.timeout:g}s.",
                {"argv0": argv[0]},
            ) from exc

        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "").strip()[-2000:]
            raise AIClientError(
                "cli_error",
                stderr_tail or f"Codex CLI exited with code {completed.returncode}.",
                {"argv0": argv[0], "returncode": completed.returncode},
            )

        events: list[dict[str, Any]] = []
        for line in (completed.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    def _extract_message_text(self, events: list[dict[str, Any]], model: str) -> str:
        message_text: str | None = None
        for event in events:
            usage = _find_usage_dict(event)
            if usage is not None:
                input_tokens, output_tokens = _usage_tokens(usage)
                _report_usage_ints(
                    self.on_usage,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model=model,
                )

            text = self._message_text_from_event(event)
            if text is not None:
                message_text = text

        if message_text is not None:
            return message_text

        raw_tail = ""
        if events:
            raw_tail = json.dumps(events[-1])[-500:]
        raise AIClientError(
            "malformed_output",
            "Codex CLI produced no agent/assistant message text.",
            {"output_sample": raw_tail},
        )

    @staticmethod
    def _message_text_from_event(event: dict[str, Any]) -> str | None:
        candidates: list[dict[str, Any]] = [event]
        item = event.get("item")
        if isinstance(item, dict):
            candidates.append(item)
        msg = event.get("msg")
        if isinstance(msg, dict):
            candidates.append(msg)

        for candidate in candidates:
            event_type = candidate.get("type")
            if isinstance(event_type, str) and (
                "agent_message" in event_type or "message" in event_type
            ):
                for key in ("text", "content", "message"):
                    value = candidate.get(key)
                    if isinstance(value, str) and value.strip():
                        return value
        return None
