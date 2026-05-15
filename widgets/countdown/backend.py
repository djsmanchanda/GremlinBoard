from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from gremlinboard_api.runtime.base import BaseWidgetService


def _parse_target_time(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    target = datetime.fromisoformat(normalized)
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return target.astimezone(timezone.utc)


def _timer_id(index: int, label: str, target_time: str) -> str:
    base = "".join(character.lower() if character.isalnum() else "-" for character in label).strip("-")
    return f"{base or 'timer'}-{index}-{abs(hash(target_time)) % 10000}"


def _normalize_timers(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_timers = config.get("timers")
    if isinstance(raw_timers, list):
        source = [timer for timer in raw_timers if isinstance(timer, dict)]
    elif isinstance(config.get("target_time"), str):
        source = [
            {
                "id": "primary",
                "label": config.get("label", "Countdown"),
                "target_time": config["target_time"],
                "duration_seconds": config.get("duration_seconds"),
            }
        ]
    else:
        source = []

    timers: list[dict[str, Any]] = []
    for index, timer in enumerate(source[:4]):
        label = str(timer.get("label") or f"Timer {index + 1}")
        target_time = str(timer.get("target_time") or "")
        try:
            target = _parse_target_time(target_time)
        except ValueError:
            continue
        duration = timer.get("duration_seconds")
        timers.append(
            {
                "id": str(timer.get("id") or _timer_id(index, label, target.isoformat())),
                "label": label,
                "target_time": target.isoformat(),
                "duration_seconds": duration if isinstance(duration, int) and duration > 0 else None,
            }
        )
    return timers


def _timer_state(timer: dict[str, Any], now: datetime) -> dict[str, Any]:
    target = _parse_target_time(str(timer["target_time"]))
    remaining = max(int((target - now).total_seconds()), 0)
    days, day_remainder = divmod(remaining, 86_400)
    hours, remainder = divmod(day_remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    formatted = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if days == 0 else f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    return {
        **timer,
        "target_time": target.isoformat(),
        "remaining_seconds": remaining,
        "formatted_remaining": formatted,
        "complete": remaining == 0,
    }


class CountdownWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        states = [_timer_state(timer, now) for timer in _normalize_timers(self.config)]
        all_complete = bool(states) and all(bool(timer["complete"]) for timer in states)
        return {
            "status": "complete" if all_complete else "running",
            "expired": False,
            "expires_at": max((str(timer["target_time"]) for timer in states), default=None),
        }

    async def get_state(self) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        timers = [_timer_state(timer, now) for timer in _normalize_timers(self.config)]
        primary = timers[0] if timers else {}
        return {
            "kind": "countdown",
            "label": primary.get("label", self.config.get("label", "Countdown")),
            "target_time": primary.get("target_time", self.config.get("target_time")),
            "remaining_seconds": primary.get("remaining_seconds", 0),
            "formatted_remaining": primary.get("formatted_remaining", "--:--:--"),
            "complete": all(bool(timer["complete"]) for timer in timers) if timers else False,
            "timers": timers,
        }
