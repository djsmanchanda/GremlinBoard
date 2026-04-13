from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GREMLINBOARD_", extra="ignore")

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
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
