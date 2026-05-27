from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from gremlinboard_api.providers.models import ProviderHealthSnapshot, ProviderRequest, ProviderResult, utc_now


class ProviderError(Exception):
    pass


class CredentialsMissingError(ProviderError):
    def __init__(self, provider_id: str, credential: str):
        super().__init__(f"missing credential '{credential}' for provider '{provider_id}'")
        self.provider_id = provider_id
        self.credential = credential


class ExternalDataProvider(ABC):
    provider_id = "provider"
    label = "Provider"
    default_ttl_seconds = 60
    max_retries = 2

    def __init__(self, runtime):
        self.runtime = runtime
        self.health = ProviderHealthSnapshot(provider_id=self.provider_id, label=self.label)

    async def fetch(self, *, request: ProviderRequest) -> ProviderResult:
        cache_key = self._cache_key(request)
        if cache_key and not request.force_refresh:
            cached = await self.runtime.cache.get(cache_key)
            if cached is not None:
                self._record_provider_started()
                health = self._build_health(status="healthy", cache_status="hit")
                self._record_provider_finished(
                    status=health.status,
                    cache_status=health.cache_status,
                    fallback_used=health.fallback_used,
                    error=health.error,
                )
                return ProviderResult(
                    provider_id=self.provider_id,
                    label=self.label,
                    data=cached["data"],
                    health=health,
                    fetched_at=cached["fetched_at"],
                    source_url=cached.get("source_url"),
                    cached=True,
                )

        coalesce = getattr(self.runtime, "coalesce_request", None)
        if cache_key and callable(coalesce) and not self._provider_is_cooling_down():
            result, coalesced = await coalesce(
                provider_id=self.provider_id,
                key=self._request_fingerprint(request),
                factory=lambda: self._fetch_uncached(request=request, cache_key=cache_key),
            )
            if coalesced and cache_key and not result.cached and not result.fallback:
                ttl_seconds = request.cache_ttl_seconds or self.default_ttl_seconds
                await self.runtime.cache.set(
                    cache_key,
                    {
                        "data": result.data,
                        "source_url": result.source_url,
                        "fetched_at": result.fetched_at,
                    },
                    ttl_seconds=ttl_seconds,
                )
            return result

        return await self._fetch_uncached(request=request, cache_key=cache_key)

    async def _fetch_uncached(self, *, request: ProviderRequest, cache_key: str | None) -> ProviderResult:
        self._record_provider_started()
        provider_finished = False
        cache_status = "none"
        try:
            last_error: Exception | None = None
            cooldown_until = None if request.force_refresh else self._provider_cooldown_until()
            if cooldown_until is not None:
                last_error = ProviderError(f"{self.provider_id} is cooling down until {cooldown_until.isoformat()}")
            else:
                attempts = max(self.max_retries + 1, 1)
                for attempt in range(attempts):
                    started = time.perf_counter()
                    try:
                        payload = await self.fetch_remote(query=request.query)
                        fetched_at = utc_now()
                        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
                        ttl_seconds = request.cache_ttl_seconds or self.default_ttl_seconds
                        if cache_key:
                            await self.runtime.cache.set(
                                cache_key,
                                {
                                    "data": payload["data"],
                                    "source_url": payload.get("source_url"),
                                    "fetched_at": fetched_at,
                                },
                                ttl_seconds=ttl_seconds,
                            )
                            cache_status = "miss"
                        health = self._build_health(
                            status="healthy",
                            latency_ms=latency_ms,
                            cache_status=cache_status,
                        )
                        self._record_provider_finished(
                            status=health.status,
                            cache_status=health.cache_status,
                            fallback_used=health.fallback_used,
                            error=health.error,
                        )
                        provider_finished = True
                        return ProviderResult(
                            provider_id=self.provider_id,
                            label=self.label,
                            data=payload["data"],
                            health=health,
                            fetched_at=fetched_at,
                            source_url=payload.get("source_url"),
                        )
                    except CredentialsMissingError as exc:
                        last_error = exc
                        break
                    except (httpx.HTTPError, ValueError, KeyError) as exc:
                        last_error = exc
                        if attempt + 1 >= attempts:
                            break

            if cache_key:
                stale_cached = await self.runtime.cache.peek(cache_key)
                if stale_cached is not None:
                    health = self._build_health(
                        status="degraded",
                        error=str(last_error) if last_error else None,
                        cache_status="stale",
                        fallback_used=True,
                    )
                    self._record_provider_finished(
                        status=health.status,
                        cache_status=health.cache_status,
                        fallback_used=health.fallback_used,
                        error=health.error,
                    )
                    provider_finished = True
                    return ProviderResult(
                        provider_id=self.provider_id,
                        label=self.label,
                        data=stale_cached["data"],
                        health=health,
                        fetched_at=stale_cached["fetched_at"],
                        source_url=stale_cached.get("source_url"),
                        cached=True,
                        stale=True,
                        fallback=True,
                    )

            fallback_data = self.fallback_response(query=request.query, error=last_error)
            if fallback_data is not None:
                health = self._build_health(
                    status="degraded",
                    error=str(last_error) if last_error else None,
                    cache_status="fallback",
                    fallback_used=True,
                )
                self._record_provider_finished(
                    status=health.status,
                    cache_status=health.cache_status,
                    fallback_used=health.fallback_used,
                    error=health.error,
                )
                provider_finished = True
                return ProviderResult(
                    provider_id=self.provider_id,
                    label=self.label,
                    data=fallback_data,
                    health=health,
                    fetched_at=utc_now(),
                    fallback=True,
                )

            message = str(last_error) if last_error else f"{self.provider_id} fetch failed"
            self._record_provider_finished(
                status="error",
                cache_status=cache_status,
                error=message,
            )
            provider_finished = True
            raise ProviderError(message)
        except Exception as exc:
            if not provider_finished:
                self._record_provider_aborted(str(exc))
            raise

    @abstractmethod
    async def fetch_remote(self, *, query: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def fallback_response(self, *, query: dict[str, Any], error: Exception | None) -> Any | None:
        return None

    def require_credential(self, key: str) -> str:
        credentials = self.runtime.secrets.resolve(self.provider_id)
        value = credentials.get(key)
        if not value:
            raise CredentialsMissingError(self.provider_id, key)
        return value

    async def request_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self.runtime.client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()

    async def request_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        response = await self.runtime.client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.text

    def _cache_key(self, request: ProviderRequest) -> str | None:
        payload = json.dumps(request.query, sort_keys=True, default=str)
        return f"{request.cache_namespace}:{self.provider_id}:{payload}"

    def _request_fingerprint(self, request: ProviderRequest) -> str:
        payload = json.dumps(request.query, sort_keys=True, default=str)
        return f"{self.provider_id}:{payload}"

    def _build_health(
        self,
        *,
        status: str,
        error: str | None = None,
        latency_ms: int | None = None,
        cache_status: str = "none",
        fallback_used: bool = False,
    ) -> ProviderHealthSnapshot:
        now = utc_now()
        if error:
            self.health.last_error_at = now
            self.health.consecutive_failures += 1
        else:
            self.health.last_success_at = now
            self.health.consecutive_failures = 0
        self.health.status = status
        self.health.error = error
        self.health.latency_ms = latency_ms
        self.health.cache_status = cache_status
        self.health.fallback_used = fallback_used
        return ProviderHealthSnapshot(
            provider_id=self.health.provider_id,
            label=self.health.label,
            status=self.health.status,
            error=self.health.error,
            last_success_at=self.health.last_success_at,
            last_error_at=self.health.last_error_at,
            latency_ms=self.health.latency_ms,
            consecutive_failures=self.health.consecutive_failures,
            cache_status=self.health.cache_status,
            fallback_used=self.health.fallback_used,
        )

    def _record_provider_started(self) -> None:
        recorder = getattr(self.runtime, "record_provider_started", None)
        if callable(recorder):
            recorder(self.provider_id)

    def _record_provider_finished(
        self,
        *,
        status: str,
        cache_status: str = "none",
        fallback_used: bool = False,
        error: str | None = None,
    ) -> None:
        recorder = getattr(self.runtime, "record_provider_finished", None)
        if callable(recorder):
            recorder(
                self.provider_id,
                status=status,
                cache_status=cache_status,
                fallback_used=fallback_used,
                error=error,
            )

    def _record_provider_aborted(self, error: str) -> None:
        recorder = getattr(self.runtime, "record_provider_aborted", None)
        if callable(recorder):
            recorder(self.provider_id, error)

    def _provider_cooldown_until(self):
        cooldown = getattr(self.runtime, "provider_cooldown_until", None)
        if callable(cooldown):
            return cooldown(self.provider_id)
        return None

    def _provider_is_cooling_down(self) -> bool:
        cooldown = getattr(self.runtime, "is_provider_cooling_down", None)
        if callable(cooldown):
            return bool(cooldown(self.provider_id))
        return False
