from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]


def default_data_dir() -> Path:
    """Resolve the platform-appropriate user-data directory.

    This is a fallback only: ``GREMLINBOARD_DATA_DIR`` (read automatically by
    pydantic-settings via ``env_prefix``) always wins when set. Hand-rolled
    rather than pulled from a dependency (e.g. ``platformdirs``) because the
    logic is a handful of ``sys.platform`` branches.
    """

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "GremlinBoard"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "GremlinBoard"
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base_dir / "gremlinboard"


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
    data_dir: Path = Field(default_factory=default_data_dir)
    # These two are derived from `data_dir` by `_apply_data_dir_defaults` below
    # unless explicitly overridden (GREMLINBOARD_DATABASE_URL /
    # GREMLINBOARD_USER_WIDGETS_DIR, or an explicit constructor kwarg).
    database_url: str | None = None
    user_widgets_dir: Path | None = None
    widgets_dir: Path = ROOT_DIR / "widgets"
    api_host: str = "127.0.0.1"
    api_port: int = 2555
    web_origin: str = "http://localhost:7555"
    session_cookie_name: str = "gremlinboard_session"
    session_ttl_hours: int = 168
    session_touch_interval_seconds: int = 300
    cors_origins: list[str] = [
        "http://localhost:7555",
        "http://localhost:7556",
        "http://localhost:3100",
        "http://127.0.0.1:7555",
        "http://127.0.0.1:7556",
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

    @model_validator(mode="after")
    def _apply_data_dir_defaults(self) -> "Settings":
        # `data_dir` is fully resolved (env override or default_factory) by the
        # time an "after" validator runs, so derived paths below always see the
        # right base directory. Only fill in fields that weren't explicitly
        # provided (constructor kwarg or their own env var) so
        # GREMLINBOARD_DATABASE_URL keeps working exactly as before.
        if self.database_url is None:
            self.database_url = f"sqlite+aiosqlite:///{(self.data_dir / 'gremlinboard.db').as_posix()}"
        if self.user_widgets_dir is None:
            self.user_widgets_dir = self.data_dir / "widgets"
        return self


settings = Settings()
