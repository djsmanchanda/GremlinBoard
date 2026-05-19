from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GREMLINBOARD_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    app_name: str = "GremlinBoard API"
    environment: str = "development"
    default_board_id: str = "main"
    default_user_id: str = "local_operator"
    default_user_email: str = "operator@gremlinboard.local"
    default_user_name: str = "Local Operator"
    database_url: str = Field(
        default=f"sqlite+aiosqlite:///{(ROOT_DIR / 'data' / 'gremlinboard.db').as_posix()}"
    )
    widgets_dir: Path = ROOT_DIR / "widgets"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"
    session_cookie_name: str = "gremlinboard_session"
    session_ttl_hours: int = 168
    session_touch_interval_seconds: int = 300
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3100",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3100",
    ]
    provider_user_agent: str = "GremlinBoard/1.0"
    reddit_user_agent: str = "GremlinBoard/1.0 (reddit integration)"
    external_http_timeout_seconds: int = 8
    openf1_base_url: str = "https://api.openf1.org"
    cricket_data_base_url: str = "https://cricapi.com"
    football_data_base_url: str = "https://api.football-data.org"
    news_api_base_url: str = "https://newsapi.org"
    x_api_base_url: str = "https://api.x.com"
    cricket_data_api_key: SecretStr | None = None
    football_data_api_key: SecretStr | None = None
    news_api_key: SecretStr | None = None
    x_bearer_token: SecretStr | None = None


settings = Settings()
