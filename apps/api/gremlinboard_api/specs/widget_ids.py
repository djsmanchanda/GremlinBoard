from __future__ import annotations

import re

MAX_WIDGET_ID_LENGTH = 48


def sanitize_widget_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    if not normalized:
        raise ValueError("widget id must include at least one letter or digit")
    if not normalized[0].isalpha():
        normalized = f"widget_{normalized}"
    normalized = normalized[:MAX_WIDGET_ID_LENGTH].strip("_")
    if not normalized:
        raise ValueError("widget id must include at least one letter after normalization")
    return normalized


def sanitize_identifier(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", " ", value).title().replace(" ", "")
    return normalized or fallback


def widget_service_module(widget_id: str) -> str:
    return f"widgets.{sanitize_widget_id(widget_id)}.backend"


def widget_root_name(widget_id: str) -> str:
    return sanitize_widget_id(widget_id)
