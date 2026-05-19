from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.config import settings
from gremlinboard_api.repositories.platform import PlatformRepository, serialize_session, serialize_user
from gremlinboard_api.schemas.contracts import AuthContextRead


@dataclass(slots=True)
class AuthResolution:
    context: AuthContextRead
    set_cookie_session_id: str | None = None


class AuthService:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def ensure_default_user(self) -> None:
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            await repository.upsert_user(
                user_id=settings.default_user_id,
                email=settings.default_user_email,
                display_name=settings.default_user_name,
                role="operator",
                is_active=True,
            )

    async def resolve_context(
        self,
        *,
        header_user_id: str | None,
        session_id: str | None,
    ) -> AuthResolution:
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            user = await repository.get_user(header_user_id or settings.default_user_id)
            if user is None:
                user = await repository.upsert_user(
                    user_id=settings.default_user_id,
                    email=settings.default_user_email,
                    display_name=settings.default_user_name,
                    role="operator",
                    is_active=True,
                )

            resolved_session = None
            if session_id:
                resolved_session = await repository.get_session(session_id)
                if resolved_session is not None:
                    expires_at = _coerce_utc(resolved_session.expires_at)
                    if expires_at <= datetime.now(timezone.utc):
                        resolved_session = None
                    elif resolved_session.user_id != user.id:
                        resolved_session = None

            set_cookie_session_id = None
            if resolved_session is None:
                set_cookie_session_id = uuid4().hex
                resolved_session = await repository.create_session(
                    session_id=set_cookie_session_id,
                    user_id=user.id,
                    expires_at=self._expires_at(),
                )
            elif self._should_touch_session(resolved_session.last_seen_at):
                resolved_session = await repository.touch_session(
                    resolved_session,
                    expires_at=self._expires_at(),
                )

            return AuthResolution(
                context=AuthContextRead(
                    user=serialize_user(user),
                    session=serialize_session(resolved_session),
                ),
                set_cookie_session_id=set_cookie_session_id,
            )

    @staticmethod
    def _expires_at() -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours)

    @staticmethod
    def _should_touch_session(last_seen_at: datetime) -> bool:
        age_seconds = (datetime.now(timezone.utc) - _coerce_utc(last_seen_at)).total_seconds()
        return age_seconds >= settings.session_touch_interval_seconds


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
