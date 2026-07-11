from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import random
from typing import Any

import httpx


class AIClientError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


Sleep = Callable[[float], Awaitable[None]]
UsageCallback = Callable[[dict[str, Any]], None]


def _report_usage(on_usage: UsageCallback | None, data: dict[str, Any], model: str) -> None:
    if on_usage is None:
        return
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
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


class AnthropicClient:
    endpoint = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
        sleep: Sleep = asyncio.sleep,
        on_usage: UsageCallback | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self._client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        self._sleep = sleep
        self.on_usage = on_usage

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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "tools": [
                {
                    "name": "gremlinboard_output",
                    "description": "Return the GremlinBoard generation artifact.",
                    "input_schema": json_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": "gremlinboard_output"},
        }
        if temperature is not None:
            payload["temperature"] = temperature
        thinking = _anthropic_thinking(reasoning_effort)
        if thinking is not None:
            payload["thinking"] = thinking

        data = await self._post(payload)
        _report_usage(self.on_usage, data, model)
        for block in _as_list(data.get("content")):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "gremlinboard_output":
                tool_input = block.get("input")
                if isinstance(tool_input, dict):
                    return tool_input
                raise AIClientError(
                    "malformed_output",
                    "Anthropic tool_use input was not a JSON object.",
                    {"input_type": type(tool_input).__name__},
                )
            if block.get("type") == "refusal":
                raise AIClientError("refusal", "Anthropic refused the request.", {"response": data})
        if data.get("stop_reason") == "refusal":
            raise AIClientError("refusal", "Anthropic refused the request.", {"response": data})
        raise AIClientError("malformed_output", "Anthropic response did not include the forced tool output.", {"response": data})

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 8192,
        temperature: float | None = None,
        reasoning_effort: str | None = "medium",
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        thinking = _anthropic_thinking(reasoning_effort)
        if thinking is not None:
            payload["thinking"] = thinking

        data = await self._post(payload)
        _report_usage(self.on_usage, data, model)
        if data.get("stop_reason") == "refusal":
            raise AIClientError("refusal", "Anthropic refused the request.", {"response": data})
        parts: list[str] = []
        for block in _as_list(data.get("content")):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            if block.get("type") == "refusal":
                raise AIClientError("refusal", "Anthropic refused the request.", {"response": data})
        text = "".join(parts).strip()
        if not text:
            raise AIClientError("malformed_output", "Anthropic response did not include text output.", {"response": data})
        return text

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "anthropic-version": "2023-06-01",
            "x-api-key": self.api_key,
            "content-type": "application/json",
        }
        return await _post_with_retry(
            self._client,
            self.endpoint,
            headers=headers,
            json_payload=payload,
            sleep=self._sleep,
        )


class OpenAIClient:
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
        sleep: Sleep = asyncio.sleep,
        on_usage: UsageCallback | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self._client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        self._sleep = sleep
        self.on_usage = on_usage

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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": max_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "gremlinboard_output",
                    "strict": True,
                    "schema": json_schema,
                }
            },
        }
        if temperature is not None:
            payload["temperature"] = temperature
        reasoning = _openai_reasoning(reasoning_effort)
        if reasoning is not None:
            payload["reasoning"] = reasoning

        data = await self._post(payload)
        _report_usage(self.on_usage, data, model)
        return _extract_openai_json(data)

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 8192,
        temperature: float | None = None,
        reasoning_effort: str | None = "medium",
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        reasoning = _openai_reasoning(reasoning_effort)
        if reasoning is not None:
            payload["reasoning"] = reasoning

        data = await self._post(payload)
        _report_usage(self.on_usage, data, model)
        text = _extract_openai_text(data)
        if not text:
            raise AIClientError("malformed_output", "OpenAI response did not include text output.", {"response": data})
        return text

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        return await _post_with_retry(
            self._client,
            self.endpoint,
            headers=headers,
            json_payload=payload,
            sleep=self._sleep,
        )


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    sleep: Sleep,
) -> dict[str, Any]:
    for attempt in range(2):
        try:
            response = await client.post(url, headers=headers, json=json_payload)
        except httpx.TimeoutException as exc:
            raise AIClientError("timeout", "LLM request timed out.", {"url": url}) from exc
        except httpx.HTTPError as exc:
            raise AIClientError("http_error", "LLM request failed before receiving a response.", {"url": url}) from exc

        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 0:
                await sleep(_retry_delay(response))
                continue
        if response.status_code >= 400:
            raise AIClientError(
                "http_error",
                f"LLM provider returned HTTP {response.status_code}.",
                {"status_code": response.status_code, "body": response.text[:2000]},
            )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise AIClientError("malformed_output", "LLM provider returned non-JSON response.", {"body": response.text[:2000]}) from exc
        if not isinstance(data, dict):
            raise AIClientError("malformed_output", "LLM provider returned a non-object response.", {"response": data})
        return data
    raise AIClientError("http_error", "LLM request retry loop exited unexpectedly.", {"url": url})


def _retry_delay(response: httpx.Response) -> float:
    header = response.headers.get("retry-after")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(header)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return 0.05 + random.uniform(0.0, 0.05)


def _anthropic_thinking(reasoning_effort: str | None) -> dict[str, Any] | None:
    if reasoning_effort is None:
        return None
    effort = reasoning_effort.lower()
    if effort in {"none", "low"}:
        return None
    if effort == "medium":
        return {"type": "enabled", "budget_tokens": 2000}
    if effort in {"high", "xhigh"}:
        return {"type": "enabled", "budget_tokens": 8000}
    return None


def _openai_reasoning(reasoning_effort: str | None) -> dict[str, str] | None:
    if reasoning_effort is None:
        return None
    effort = reasoning_effort.lower()
    if effort in {"none", "off"}:
        return None
    if effort == "xhigh":
        return {"effort": "high"}
    if effort in {"low", "medium", "high"}:
        return {"effort": effort}
    return None


def _extract_openai_json(data: dict[str, Any]) -> dict[str, Any]:
    parsed = data.get("output_parsed")
    if isinstance(parsed, dict):
        return parsed
    for item in _iter_openai_content(data):
        if _is_refusal(item):
            raise AIClientError("refusal", "OpenAI refused the request.", {"response": data})
        if isinstance(item.get("parsed"), dict):
            return item["parsed"]
    text = _extract_openai_text(data)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIClientError("malformed_output", "OpenAI response text was not valid JSON.", {"text": text[:2000]}) from exc
    if not isinstance(value, dict):
        raise AIClientError("malformed_output", "OpenAI JSON output was not an object.", {"output_type": type(value).__name__})
    return value


def _extract_openai_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str):
        return output_text.strip()
    parts: list[str] = []
    for item in _iter_openai_content(data):
        if _is_refusal(item):
            raise AIClientError("refusal", "OpenAI refused the request.", {"response": data})
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts).strip()


def _iter_openai_content(data: dict[str, Any]) -> list[dict[str, Any]]:
    content_items: list[dict[str, Any]] = []
    for item in _as_list(data.get("output")):
        if isinstance(item, dict):
            if item.get("type") in {"refusal", "output_text"}:
                content_items.append(item)
            for content in _as_list(item.get("content")):
                if isinstance(content, dict):
                    content_items.append(content)
    return content_items


def _is_refusal(item: dict[str, Any]) -> bool:
    return item.get("type") == "refusal" or isinstance(item.get("refusal"), str)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []