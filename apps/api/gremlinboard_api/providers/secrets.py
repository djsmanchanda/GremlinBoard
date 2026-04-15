from __future__ import annotations

from dataclasses import dataclass
import re

from gremlinboard_api.config import Settings
from gremlinboard_api.repositories.platform import PlatformRepository


@dataclass(slots=True)
class ProviderCredentials:
    provider_id: str
    values: dict[str, str]

    def get(self, key: str) -> str | None:
        return self.values.get(key)


class SecretResolver:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._overrides: dict[str, dict[str, str]] = {}

    def resolve(self, provider_id: str) -> ProviderCredentials:
        raw_values = {
            "cricketdata": {"api_key": self._unwrap(self.settings.cricket_data_api_key)},
            "football-data": {"api_key": self._unwrap(self.settings.football_data_api_key)},
            "newsapi": {"api_key": self._unwrap(self.settings.news_api_key)},
            "x": {"bearer_token": self._unwrap(self.settings.x_bearer_token)},
        }.get(provider_id, {})
        runtime_overrides = self._overrides.get(provider_id, {})
        return ProviderCredentials(
            provider_id=provider_id,
            values={key: value for key, value in {**raw_values, **runtime_overrides}.items() if value},
        )

    async def sync_from_repository(self, session_factory) -> None:
        async with session_factory() as session:
            repository = PlatformRepository(session)
            credentials = await repository.list_credentials()

        next_overrides: dict[str, dict[str, str]] = {}
        for credential in credentials:
            provider_id = credential.provider.strip().lower()
            key = _credential_key(credential.label)
            required_keys = PROVIDER_SECRET_KEYS.get(provider_id, ())
            provider_values = next_overrides.setdefault(provider_id, {})
            provider_values[key] = credential.value_secret
            if len(required_keys) == 1 and key not in required_keys:
                provider_values[required_keys[0]] = credential.value_secret
        self._overrides = next_overrides

    @staticmethod
    def _unwrap(secret) -> str | None:
        if secret is None:
            return None
        return secret.get_secret_value()


PROVIDER_SECRET_KEYS = {
    "cricketdata": ("api_key",),
    "football-data": ("api_key",),
    "newsapi": ("api_key",),
    "x": ("bearer_token",),
}


def _credential_key(label: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return normalized or "default"
