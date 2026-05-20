from gremlinboard_api.config import settings
from gremlinboard_api.registry.loader import load_registry


def test_registry_loads_expected_widgets() -> None:
    registry = load_registry(settings.widgets_dir)
    widget_ids = sorted(entry.manifest.id for entry in registry.all())

    assert widget_ids == ["agent_overview", "countdown", "news", "pinboard", "sports", "trending"]
    assert registry.get("sports").manifest.preferred_size.value == "4x2"
    assert "4x4" in [size.value for size in registry.get("pinboard").manifest.allowed_sizes]
