from gremlinboard_api.validation import ConfigValidationError, normalize_config


def test_normalize_config_applies_defaults() -> None:
    schema = {
        "type": "object",
        "properties": {
            "provider": {"type": "string", "default": "rss"},
            "refresh_interval_seconds": {"type": "integer", "default": 300, "minimum": 30},
            "sources": {
                "type": "array",
                "items": {"type": "string", "enum": ["reddit", "x"]},
                "default": ["reddit"],
            },
        },
        "additionalProperties": False,
    }

    normalized = normalize_config(schema, {"provider": "rss"})

    assert normalized == {
        "provider": "rss",
        "refresh_interval_seconds": 300,
        "sources": ["reddit"],
    }


def test_normalize_config_rejects_unexpected_fields() -> None:
    schema = {
        "type": "object",
        "properties": {
            "provider": {"type": "string", "default": "rss"},
        },
        "additionalProperties": False,
    }

    try:
        normalize_config(schema, {"provider": "rss", "unexpected": "value"})
    except ConfigValidationError as exc:
        assert exc.errors == [{"path": "$.unexpected", "message": "unexpected property"}]
    else:  # pragma: no cover
        raise AssertionError("expected validation error")
