from gremlinboard_api.schemas.contracts import SpecDocumentFormat
from gremlinboard_api.specs.pipeline import build_manifest_preview, parse_and_validate_spec


def test_parse_and_validate_spec_accepts_json_document() -> None:
    document = """
    {
      "id": "news_custom",
      "name": "News Custom",
      "category": "news",
      "description": "Curated news stream",
      "min_size": "2x2",
      "preferred_size": "4x2",
      "refresh_policy": {"mode": "interval", "interval_seconds": 300},
      "source_type": "api",
      "permissions": ["network"],
      "output_schema": {"headline": "string"},
      "renderer_type": "card",
      "lifecycle_policy": {"expires": false, "stateful": true}
    }
    """

    spec, errors = parse_and_validate_spec(content=document, format=SpecDocumentFormat.JSON)

    assert errors == []
    assert spec is not None
    manifest = build_manifest_preview(spec)
    assert manifest["id"] == "news_custom"
    assert manifest["version"] == "0.1.0"


def test_parse_and_validate_spec_reports_json_errors() -> None:
    spec, errors = parse_and_validate_spec(content='{"id": "broken"', format=SpecDocumentFormat.JSON)

    assert spec is None
    assert errors
    assert errors[0]["line"] == 1
