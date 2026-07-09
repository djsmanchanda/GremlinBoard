from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from gremlinboard_api.ai.clients import AIClientError, AnthropicClient, OpenAIClient


async def _no_sleep(_delay: float) -> None:
    return None


@pytest.mark.asyncio
async def test_anthropic_complete_json_parses_forced_tool_use() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "tool_use",
                        "name": "gremlinboard_output",
                        "input": {"ok": True, "name": "Spec"},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AnthropicClient(api_key="anthropic-test", http_client=http_client, sleep=_no_sleep)
        result = await client.complete_json(
            system_prompt="system",
            user_prompt="user",
            json_schema={"type": "object"},
            model="claude-test",
            reasoning_effort="medium",
        )

    assert result == {"ok": True, "name": "Spec"}
    assert seen["headers"]["x-api-key"] == "anthropic-test"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["payload"]["tool_choice"] == {"type": "tool", "name": "gremlinboard_output"}
    assert seen["payload"]["thinking"] == {"type": "enabled", "budget_tokens": 2000}


@pytest.mark.asyncio
async def test_openai_complete_json_parses_responses_output_text() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"output_text": '{"ok": true, "count": 2}'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAIClient(api_key="openai-test", http_client=http_client, sleep=_no_sleep)
        result = await client.complete_json(
            system_prompt="system",
            user_prompt="user",
            json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            model="gpt-test",
            reasoning_effort="high",
        )

    assert result == {"ok": True, "count": 2}
    assert seen["headers"]["authorization"] == "Bearer openai-test"
    assert seen["payload"]["text"]["format"]["type"] == "json_schema"
    assert seen["payload"]["text"]["format"]["strict"] is True
    assert seen["payload"]["reasoning"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_retry_on_429_then_success() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"output_text": '{"ok": true}'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAIClient(api_key="openai-test", http_client=http_client, sleep=_no_sleep)
        result = await client.complete_json(
            system_prompt="system",
            user_prompt="user",
            json_schema={"type": "object"},
            model="gpt-test",
        )

    assert result == {"ok": True}
    assert calls == 2


@pytest.mark.asyncio
async def test_timeout_raises_ai_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAIClient(api_key="openai-test", http_client=http_client, sleep=_no_sleep)
        with pytest.raises(AIClientError) as exc_info:
            await client.complete_json(
                system_prompt="system",
                user_prompt="user",
                json_schema={"type": "object"},
                model="gpt-test",
            )

    assert exc_info.value.code == "timeout"