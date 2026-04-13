from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def build_news_items(topic: str) -> list[dict[str, str]]:
    stamp = now_utc().strftime("%H:%M UTC")
    return [
        {
            "title": f"{topic.title()} market shifts after late briefing",
            "source": "Gremlin Wire",
            "summary": "Operators are watching a fast-moving update cycle across major teams.",
            "published_at": stamp,
        },
        {
            "title": f"{topic.title()} product roadmap tightens around live operations",
            "source": "Board Daily",
            "summary": "Leaders are prioritizing durability, observability, and response speed.",
            "published_at": stamp,
        },
        {
            "title": f"{topic.title()} teams rebalance workloads ahead of peak demand",
            "source": "Signal Desk",
            "summary": "Engineering leads are consolidating dashboards and reducing manual checks.",
            "published_at": stamp,
        },
    ]


def build_trending_sections(sources: list[str]) -> list[dict[str, object]]:
    baseline = {
        "reddit": ["r/formula1 quali thread", "r/cricket semi-finals watch", "r/soccer tactical breakdown"],
        "x": ["#RaceDay", "#IPL", "#TransferWatch"],
        "hackernews": [
            "Launch: microservice observability board",
            "Ask HN: low-overhead schedulers",
            "Show HN: timeline widgets",
        ],
    }
    return [
        {
            "source": source,
            "items": [
                {"label": label, "score": 100 - (index * 7), "href": f"https://example.com/{source}/{index}"}
                for index, label in enumerate(baseline.get(source, ["No trend available"]))
            ],
        }
        for source in sources
    ]


def build_sports_state(sport: str) -> dict[str, object]:
    if sport == "ipl":
        return {
            "headline": "IPL Live Centre",
            "status": "Live",
            "entries": [
                {"label": "GT 187/5", "detail": "19.2 overs"},
                {"label": "CSK 132/4", "detail": "Target 188"},
                {"label": "Req RR", "detail": "14.1"},
            ],
        }
    if sport == "f1":
        return {
            "headline": "F1 Session Tracker",
            "status": "Qualifying",
            "entries": [
                {"label": "P1", "detail": "Norris 1:27.442"},
                {"label": "P2", "detail": "+0.118 Verstappen"},
                {"label": "P3", "detail": "+0.227 Leclerc"},
            ],
        }
    return {
        "headline": "Football Watch",
        "status": "In Play",
        "entries": [
            {"label": "Arsenal 2-1 Milan", "detail": "71'"},
            {"label": "xG", "detail": "1.94 - 1.08"},
            {"label": "Possession", "detail": "61% - 39%"},
        ],
    }


def default_countdown_target(minutes: int = 90) -> str:
    return (now_utc() + timedelta(minutes=minutes)).isoformat()
