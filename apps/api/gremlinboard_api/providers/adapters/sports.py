from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from gremlinboard_api.config import settings
from gremlinboard_api.providers.base import ExternalDataProvider
from gremlinboard_api.services.fixtures import build_sports_state


class CricketDataProvider(ExternalDataProvider):
    provider_id = "cricketdata"
    label = "CricketData"
    default_ttl_seconds = 20

    async def fetch_remote(self, *, query: dict[str, Any]) -> dict[str, Any]:
        api_key = self.require_credential("api_key")
        tournament = str(query.get("tournament", "IPL"))
        match_listing = await self.request_json(
            f"{settings.cricket_data_base_url}/api/cricket",
            params={"apikey": api_key},
        )
        candidates = match_listing.get("data") or match_listing.get("matches") or []
        match = next(
            (
                item
                for item in candidates
                if tournament.lower() in str(item.get("title", item.get("name", ""))).lower()
                or tournament.lower() in str(item.get("description", "")).lower()
            ),
            candidates[0] if candidates else None,
        )
        if not isinstance(match, dict):
            raise ValueError("cricketdata returned no matches")

        unique_id = match.get("unique_id") or match.get("id")
        score_response = {}
        if unique_id:
            score_response = await self.request_json(
                f"{settings.cricket_data_base_url}/api/cricketScore",
                params={"apikey": api_key, "unique_id": unique_id},
            )

        title = str(match.get("title") or match.get("name") or "IPL Live Centre")
        summary = str(score_response.get("score") or match.get("description") or "Live match feed unavailable")
        lower_summary = summary.lower()
        live = not any(marker in lower_summary for marker in ["result", "stumps", "won", "draw"])
        payload = {
            "headline": title,
            "status": "Live" if live else "Complete",
            "entries": [
                {"label": "Match", "detail": title},
                {"label": "Score", "detail": summary},
                {"label": "Source", "detail": "CricketData"},
            ],
            "live": live,
        }
        return {
            "data": payload,
            "source_url": str(match.get("source") or settings.cricket_data_base_url),
        }

    def fallback_response(self, *, query: dict[str, Any], error: Exception | None) -> Any | None:
        return build_sports_state("ipl") | {"live": True}


class OpenF1Provider(ExternalDataProvider):
    provider_id = "openf1"
    label = "OpenF1"
    default_ttl_seconds = 20

    async def fetch_remote(self, *, query: dict[str, Any]) -> dict[str, Any]:
        sessions = await self.request_json(
            f"{settings.openf1_base_url}/v1/sessions",
            params={"year": query.get("year") or datetime.now(UTC).year},
        )
        if not isinstance(sessions, list) or not sessions:
            raise ValueError("openf1 returned no sessions")

        session = sorted(
            (item for item in sessions if isinstance(item, dict)),
            key=lambda item: str(item.get("date_start") or item.get("date_end") or ""),
        )[-1]
        meeting = str(session.get("meeting_name") or session.get("country_name") or "Grand Prix")
        session_name = str(session.get("session_name") or "Session")
        session_status = str(session.get("session_status") or "Scheduled")
        live = session_status.lower() not in {"scheduled", "finished", "ended"}
        payload = {
            "headline": f"{meeting} {session_name}".strip(),
            "status": session_status,
            "entries": [
                {"label": "Track", "detail": str(session.get("location") or session.get("country_name") or "TBA")},
                {"label": "Start", "detail": str(session.get("date_start") or "TBA")},
                {"label": "Key", "detail": str(session.get("session_key") or "n/a")},
            ],
            "live": live,
        }
        return {
            "data": payload,
            "source_url": settings.openf1_base_url,
        }

    def fallback_response(self, *, query: dict[str, Any], error: Exception | None) -> Any | None:
        return build_sports_state("f1") | {"live": False}


class FootballDataProvider(ExternalDataProvider):
    provider_id = "football-data"
    label = "Football-Data"
    default_ttl_seconds = 45

    async def fetch_remote(self, *, query: dict[str, Any]) -> dict[str, Any]:
        api_key = self.require_credential("api_key")
        competition = str(query.get("competition_code") or "PL")
        response = await self.request_json(
            f"{settings.football_data_base_url}/v4/matches",
            params={"competitions": competition, "status": query.get("status") or "LIVE"},
            headers={"X-Auth-Token": api_key},
        )
        matches = response.get("matches") or []
        if not matches:
            response = await self.request_json(
                f"{settings.football_data_base_url}/v4/matches",
                params={"competitions": competition, "status": "SCHEDULED"},
                headers={"X-Auth-Token": api_key},
            )
            matches = response.get("matches") or []
        match = matches[0] if matches else None
        if not isinstance(match, dict):
            raise ValueError("football-data returned no matches")

        home_team = match.get("homeTeam") or {}
        away_team = match.get("awayTeam") or {}
        score = match.get("score") or {}
        full_time = score.get("fullTime") if isinstance(score, dict) else {}
        home = str(home_team.get("shortName") or home_team.get("name") or "Home")
        away = str(away_team.get("shortName") or away_team.get("name") or "Away")
        home_score = full_time.get("home") if isinstance(full_time, dict) else None
        away_score = full_time.get("away") if isinstance(full_time, dict) else None
        status = str(match.get("status") or "LIVE")
        live = status.upper() in {"LIVE", "IN_PLAY", "PAUSED"}
        payload = {
            "headline": f"{home} vs {away}",
            "status": status.replace("_", " ").title(),
            "entries": [
                {
                    "label": "Score",
                    "detail": f"{home_score if home_score is not None else '-'} - {away_score if away_score is not None else '-'}",
                },
                {"label": "Competition", "detail": competition},
                {"label": "Kickoff", "detail": str(match.get("utcDate") or "TBA")},
            ],
            "live": live,
        }
        return {
            "data": payload,
            "source_url": settings.football_data_base_url,
        }

    def fallback_response(self, *, query: dict[str, Any], error: Exception | None) -> Any | None:
        return build_sports_state("football") | {"live": True}
