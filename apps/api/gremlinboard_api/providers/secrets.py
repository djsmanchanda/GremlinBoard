from __future__ import annotations

from dataclasses import dataclass

from gremlinboard_api.config import Settings


@dataclass(slots=True)
class ProviderCredentials:
    provider_id: str
    values: dict[str, str]

    def get(self, key: str) -> str | None:
        return self.values.get(key)


class SecretResolver:
    def __init__(self, settings: Settings):
        self.settings = settings

    def resolve(self, provider_id: str) -> ProviderCredentials:
        raw_values = {
            "cricketdata": {"api_key": self._unwrap(self.settings.cricket_data_api_key)},
            "football-data": {"api_key": self._unwrap(self.settings.football_data_api_key)},
            "newsapi": {"api_key": self._unwrap(self.settings.news_api_key)},
            "x": {"bearer_token": self._unwrap(self.settings.x_bearer_token)},
        }.get(provider_id, {})
        return ProviderCredentials(
            provider_id=provider_id,
            values={key: value for key, value in raw_values.items() if value},
        )

    @staticmethod
    def _unwrap(secret) -> str | None:
        if secret is None:
            return None
        return secret.get_secret_value()
