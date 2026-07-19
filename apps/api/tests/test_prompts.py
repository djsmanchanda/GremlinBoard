from __future__ import annotations

import json

import pytest

from gremlinboard_api.ai import prompts
from gremlinboard_api.schemas.blueprint import validate_blueprint
from gremlinboard_api.schemas.contracts import WidgetSpecDraft


# ---------------------------------------------------------------------------
# Rendering: every function returns non-empty text / dict output.
# ---------------------------------------------------------------------------


def test_prompt_pack_version_is_set() -> None:
    assert prompts.PROMPT_PACK_VERSION == "2"


def test_spec_prompts_render_non_empty() -> None:
    assert prompts.spec_system_prompt().strip()
    assert prompts.spec_user_prompt(idea="a widget that shows something").strip()


def test_blueprint_prompts_render_non_empty() -> None:
    spec = _sample_spec()
    assert prompts.blueprint_system_prompt().strip()
    assert prompts.blueprint_user_prompt(spec=spec).strip()


def test_backend_prompts_render_non_empty() -> None:
    spec = _sample_spec()
    blueprint = prompts.BLUEPRINT_EXAMPLE_SERVICE_MONITOR
    assert prompts.backend_system_prompt().strip()
    assert prompts.backend_user_prompt(spec=spec, blueprint=blueprint).strip()


def test_review_prompts_render_non_empty() -> None:
    spec = _sample_spec()
    package = _sample_package()
    assert prompts.review_system_prompt().strip()
    assert prompts.review_user_prompt(spec=spec, package=package).strip()


def test_repair_prompt_renders_non_empty() -> None:
    text = prompts.repair_user_prompt(stage="spec", errors=["min_size not in allowed_sizes"])
    assert text.strip()


def test_refine_spec_user_prompt_renders_non_empty() -> None:
    spec = _sample_spec()
    blueprint = prompts.BLUEPRINT_EXAMPLE_SERVICE_MONITOR
    rendered = prompts.refine_spec_user_prompt(spec=spec, blueprint=blueprint, feedback="add a refresh button")
    assert rendered.strip()


# ---------------------------------------------------------------------------
# User prompts embed their inputs.
# ---------------------------------------------------------------------------


def test_spec_user_prompt_embeds_idea() -> None:
    idea = "a very distinctive idea marker ZQX123"
    rendered = prompts.spec_user_prompt(idea=idea)
    assert idea in rendered


def test_blueprint_user_prompt_embeds_spec() -> None:
    spec = _sample_spec()
    spec["id"] = "unique_marker_widget_777"
    rendered = prompts.blueprint_user_prompt(spec=spec)
    assert "unique_marker_widget_777" in rendered


def test_backend_user_prompt_embeds_spec_and_blueprint_and_bindings() -> None:
    spec = _sample_spec()
    spec["id"] = "unique_backend_marker_888"
    blueprint = prompts.BLUEPRINT_EXAMPLE_SERVICE_MONITOR
    rendered = prompts.backend_user_prompt(spec=spec, blueprint=blueprint)
    assert "unique_backend_marker_888" in rendered
    # Binding paths collected from the blueprint must be listed for the model.
    assert "metrics.cpu_percent" in rendered
    assert "metrics.disk_percent" in rendered
    assert "details.hostname" in rendered


def test_backend_user_prompt_lists_bindings_from_list_blueprint() -> None:
    spec = _sample_spec()
    blueprint = prompts.BLUEPRINT_EXAMPLE_FEED_LIST
    rendered = prompts.backend_user_prompt(spec=spec, blueprint=blueprint)
    assert "items" in rendered
    assert "title" in rendered
    assert "source" in rendered


def test_review_user_prompt_embeds_spec_and_package() -> None:
    spec = _sample_spec()
    spec["id"] = "unique_review_marker_999"
    package = _sample_package()
    package["manifest"]["id"] = "unique_review_marker_999"
    rendered = prompts.review_user_prompt(spec=spec, package=package)
    assert "unique_review_marker_999" in rendered


def test_refine_spec_user_prompt_embeds_spec_blueprint_and_feedback() -> None:
    spec = _sample_spec()
    spec["id"] = "unique_refine_marker_555"
    blueprint = prompts.BLUEPRINT_EXAMPLE_SERVICE_MONITOR
    feedback = "distinct feedback marker XYZ999: add a refresh button"
    rendered = prompts.refine_spec_user_prompt(spec=spec, blueprint=blueprint, feedback=feedback)
    assert "unique_refine_marker_555" in rendered
    assert blueprint["widget_id"] in rendered
    assert "distinct feedback marker XYZ999" in rendered


def test_blueprint_user_prompt_embeds_extra_guidance_when_present() -> None:
    spec = _sample_spec()
    rendered_without = prompts.blueprint_user_prompt(spec=spec)
    rendered_with = prompts.blueprint_user_prompt(spec=spec, extra_guidance="distinct blueprint guidance marker QQQ111")
    assert "distinct blueprint guidance marker QQQ111" not in rendered_without
    assert "distinct blueprint guidance marker QQQ111" in rendered_with


def test_blueprint_user_prompt_template_none_matches_omitted_argument() -> None:
    spec = _sample_spec()

    assert prompts.blueprint_user_prompt(spec=spec, template=None) == prompts.blueprint_user_prompt(spec=spec)


def test_blueprint_user_prompt_embeds_template_json() -> None:
    spec = _sample_spec()
    template = {
        "id": "distinct_template_id_123",
        "description": "A distinct template description.",
        "blueprint": {
            "blueprint_version": "1",
            "widget_id": "template_marker_widget",
            "layouts": {"medium": {"type": "stat", "label": "Marker", "value_path": "metrics.marker"}},
        },
    }

    rendered = prompts.blueprint_user_prompt(spec=spec, template=template)

    assert "distinct_template_id_123" in rendered
    assert json.dumps(template["blueprint"], indent=2, sort_keys=True) in rendered


def test_backend_user_prompt_embeds_extra_guidance_when_present() -> None:
    spec = _sample_spec()
    blueprint = prompts.BLUEPRINT_EXAMPLE_SERVICE_MONITOR
    rendered_without = prompts.backend_user_prompt(spec=spec, blueprint=blueprint)
    rendered_with = prompts.backend_user_prompt(
        spec=spec, blueprint=blueprint, extra_guidance="distinct backend guidance marker RRR222"
    )
    assert "distinct backend guidance marker RRR222" not in rendered_without
    assert "distinct backend guidance marker RRR222" in rendered_with


def test_refinement_prompts_embed_config_schema_and_existing_backend() -> None:
    spec = _sample_spec()
    blueprint = prompts.BLUEPRINT_EXAMPLE_FEED_LIST
    config_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"offset": {"type": "integer", "minimum": 0, "default": 0}},
        "required": [],
    }
    previous_backend = "import asyncio\n\nBASELINE_CACHE_MARKER = True\n"

    refine_rendered = prompts.refine_spec_user_prompt(
        spec=spec,
        blueprint=blueprint,
        feedback="add page controls",
        config_schema=config_schema,
    )
    backend_rendered = prompts.backend_user_prompt(
        spec=spec,
        blueprint=blueprint,
        extra_guidance="add page controls",
        config_schema=config_schema,
        previous_backend_source=previous_backend,
    )

    assert '"offset"' in refine_rendered
    assert '"offset"' in backend_rendered
    assert "BASELINE_CACHE_MARKER" in backend_rendered
    assert "incremental refinement" in backend_rendered
    assert "add page controls" in backend_rendered


def test_repair_user_prompt_embeds_stage_and_errors() -> None:
    rendered = prompts.repair_user_prompt(
        stage="blueprint",
        errors=["distinct error marker AAA111", "second error marker BBB222"],
    )
    assert "blueprint" in rendered
    assert "distinct error marker AAA111" in rendered
    assert "second error marker BBB222" in rendered


# ---------------------------------------------------------------------------
# Output schemas are valid JSON-serializable dicts with additionalProperties false.
# ---------------------------------------------------------------------------


def test_spec_output_schema_is_json_serializable_and_strict() -> None:
    schema = prompts.spec_output_schema()
    json.dumps(schema)  # must not raise
    assert schema["additionalProperties"] is False
    assert schema["type"] == "object"


def test_spec_output_schema_matches_widget_spec_draft_fields_exactly() -> None:
    schema = prompts.spec_output_schema()
    schema_fields = set(schema["properties"].keys())
    model_fields = set(WidgetSpecDraft.model_fields.keys())
    assert schema_fields == model_fields
    assert set(schema["required"]) == model_fields


def test_review_output_schema_is_json_serializable_and_strict() -> None:
    schema = prompts.review_output_schema()
    json.dumps(schema)  # must not raise
    assert schema["additionalProperties"] is False
    assert schema["type"] == "object"
    expected_fields = {"summary", "issues", "approved_for_install_recommendation"}
    assert set(schema["properties"].keys()) == expected_fields
    assert set(schema["required"]) == expected_fields

    issue_schema = schema["properties"]["issues"]["items"]
    assert issue_schema["additionalProperties"] is False
    issue_fields = {"severity", "area", "message", "fix_hint"}
    assert set(issue_schema["properties"].keys()) == issue_fields
    assert set(issue_schema["required"]) == issue_fields
    assert set(issue_schema["properties"]["severity"]["enum"]) == {"critical", "warning", "info"}


# ---------------------------------------------------------------------------
# Few-shot blueprint JSON parses and validates against the blueprint schema.
# ---------------------------------------------------------------------------


def test_blueprint_fewshot_service_monitor_validates() -> None:
    example = prompts.BLUEPRINT_EXAMPLE_SERVICE_MONITOR
    # Round-trip through JSON to mirror how it is embedded in the prompt text.
    round_tripped = json.loads(json.dumps(example))
    blueprint = validate_blueprint(round_tripped)
    assert blueprint.widget_id == "svc_uptime_monitor"
    assert blueprint.layouts.medium is not None


def test_blueprint_fewshot_feed_list_validates() -> None:
    example = prompts.BLUEPRINT_EXAMPLE_FEED_LIST
    round_tripped = json.loads(json.dumps(example))
    blueprint = validate_blueprint(round_tripped)
    assert blueprint.widget_id == "feed_top_stories"
    assert blueprint.layouts.medium is not None


def test_blueprint_fewshot_examples_appear_in_blueprint_system_prompt() -> None:
    rendered = prompts.blueprint_system_prompt()
    assert json.dumps(prompts.BLUEPRINT_EXAMPLE_SERVICE_MONITOR, indent=2) in rendered
    assert json.dumps(prompts.BLUEPRINT_EXAMPLE_FEED_LIST, indent=2) in rendered


# ---------------------------------------------------------------------------
# Content requirements: allowed sizes, import allowlist, rubric, category rules.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", ["1x1", "1x2", "2x2", "4x2", "2x4", "4x4"])
def test_spec_system_prompt_lists_allowed_sizes(size: str) -> None:
    assert size in prompts.spec_system_prompt()


def test_spec_system_prompt_forbids_vague_sample_data() -> None:
    rendered = prompts.spec_system_prompt()
    assert "concrete data source" in rendered.lower() or "concrete" in rendered.lower()
    assert "sample" in rendered.lower()


def test_backend_system_prompt_lists_import_allowlist() -> None:
    rendered = prompts.backend_system_prompt()
    for module in prompts.IMPORT_ALLOWLIST:
        assert module in rendered
    for forbidden in ("os", "subprocess", "socket", "pathlib"):
        assert forbidden in rendered  # named explicitly as forbidden


def test_backend_system_prompt_includes_worked_example_class() -> None:
    rendered = prompts.backend_system_prompt()
    assert "BaseWidgetService" in rendered
    assert "NewsWidgetService" in rendered
    assert "async def get_state" in rendered


def test_review_system_prompt_covers_rubric_areas() -> None:
    rendered = prompts.review_system_prompt()
    for area in ("contract", "bindings", "safety", "refresh_policy", "sizing"):
        assert area in rendered


def test_review_output_schema_severity_and_area_enums_match_rubric_language() -> None:
    schema = prompts.review_output_schema()
    area_enum = set(schema["properties"]["issues"]["items"]["properties"]["area"]["enum"])
    assert {"contract", "bindings", "safety", "refresh_policy", "sizing", "other"} == area_enum


def test_refresh_policy_prompt_forbids_sub_60s_polling_language() -> None:
    rendered = prompts.spec_system_prompt()
    assert "sub-60" in rendered or "60-second" in rendered or "60 seconds" in rendered.lower()


def test_spec_system_prompt_lists_public_api_directories() -> None:
    rendered = prompts.spec_system_prompt()
    assert "https://github.com/public-apis/public-apis" in rendered
    assert "https://free-apis.github.io/#/" in rendered
    assert "https://github.com/public-api-lists/public-api-lists" in rendered


def test_spec_system_prompt_instructs_web_research_when_available() -> None:
    rendered = prompts.spec_system_prompt()
    lowered = rendered.lower()
    assert "web search" in lowered or "websearch" in lowered
    assert "do not guess endpoints" in lowered


def test_data_source_contract_names_example_free_apis() -> None:
    rendered = prompts.DATA_SOURCE_CONTRACT
    for example in ("Hacker News", "Open-Meteo", "CoinGecko", "football-data.org", "TheSportsDB"):
        assert example in rendered


# ---------------------------------------------------------------------------
# Legacy wrappers still work (ai/providers.py imports these directly).
# ---------------------------------------------------------------------------


def test_legacy_render_idea_to_spec_prompt_embeds_idea() -> None:
    idea = "legacy marker idea QWERTY"
    rendered = prompts.render_idea_to_spec_prompt(idea=idea)
    assert idea in rendered


def test_legacy_render_codegen_prompt_embeds_spec_and_scaffold_files() -> None:
    spec = _sample_spec()
    spec["id"] = "legacy_codegen_marker"
    rendered = prompts.render_codegen_prompt(spec=spec, scaffold_files=["manifest.json", "backend.py"])
    assert "legacy_codegen_marker" in rendered
    assert "manifest.json" in rendered
    assert "backend.py" in rendered


def test_legacy_render_review_prompt_embeds_spec_and_package() -> None:
    spec = _sample_spec()
    spec["id"] = "legacy_review_marker"
    package = _sample_package()
    package["manifest"]["id"] = "legacy_review_marker"
    rendered = prompts.render_review_prompt(spec=spec, package=package)
    assert "legacy_review_marker" in rendered


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_spec() -> dict:
    return {
        "id": "sample_widget",
        "name": "Sample Widget",
        "category": "monitoring",
        "description": "Polls the Sample API for a status metric.",
        "min_size": "1x1",
        "preferred_size": "2x2",
        "refresh_policy": {"mode": "interval", "interval_seconds": 300},
        "source_type": "api",
        "permissions": ["network"],
        "output_schema": {"primary": "status", "secondary": "detail"},
        "renderer_type": "card",
        "lifecycle_policy": {"stateful": False, "expires": False},
    }


def _sample_package() -> dict:
    return {
        "manifest": {"id": "sample_widget", "version": "0.1.0"},
        "files": ["manifest.json", "config.schema.json", "backend.py", "view.blueprint.json"],
    }
