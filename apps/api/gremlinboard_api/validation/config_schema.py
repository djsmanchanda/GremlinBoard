from __future__ import annotations

from copy import deepcopy
from typing import Any


class ConfigValidationError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__("widget config validation failed")
        self.errors = errors


def normalize_config(schema: dict[str, Any], raw_config: dict[str, Any] | None) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    value = _validate_node(schema, raw_config or {}, "$", errors, missing=False)
    if errors:
        raise ConfigValidationError(errors)
    if not isinstance(value, dict):
        raise ConfigValidationError([{"path": "$", "message": "widget config root must be an object"}])
    return value


def _validate_node(
    schema: dict[str, Any],
    value: Any,
    path: str,
    errors: list[dict[str, Any]],
    *,
    missing: bool,
):
    if missing:
        if "default" in schema:
            value = deepcopy(schema["default"])
        elif path == "$":
            value = {}
        else:
            return None

    schema_type = schema.get("type")
    if schema_type == "object" or (schema_type is None and "properties" in schema):
        return _validate_object(schema, value, path, errors)
    if schema_type == "array":
        return _validate_array(schema, value, path, errors)
    if schema_type == "string":
        return _validate_string(schema, value, path, errors)
    if schema_type == "integer":
        return _validate_integer(schema, value, path, errors)
    if schema_type == "number":
        return _validate_number(schema, value, path, errors)
    if schema_type == "boolean":
        return _validate_boolean(schema, value, path, errors)
    return value


def _validate_object(schema: dict[str, Any], value: Any, path: str, errors: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append({"path": path, "message": "expected object"})
        return {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    normalized: dict[str, Any] = {}

    if schema.get("additionalProperties") is False:
        for key in value:
            if key not in properties:
                errors.append({"path": f"{path}.{key}", "message": "unexpected property"})

    for key, child_schema in properties.items():
        child_missing = key not in value
        if child_missing and key in required and "default" not in child_schema:
            errors.append({"path": f"{path}.{key}", "message": "missing required property"})
        child_value = _validate_node(
            child_schema,
            value.get(key),
            f"{path}.{key}",
            errors,
            missing=child_missing,
        )
        if child_value is not None:
            normalized[key] = child_value

    for key, child_value in value.items():
        if key not in properties and schema.get("additionalProperties") is not False:
            normalized[key] = child_value

    return normalized


def _validate_array(schema: dict[str, Any], value: Any, path: str, errors: list[dict[str, Any]]) -> list[Any]:
    if not isinstance(value, list):
        errors.append({"path": path, "message": "expected array"})
        return []
    item_schema = schema.get("items", {})
    normalized = [
        _validate_node(item_schema, item, f"{path}[{index}]", errors, missing=False)
        for index, item in enumerate(value)
    ]
    min_items = schema.get("minItems")
    max_items = schema.get("maxItems")
    if min_items is not None and len(normalized) < int(min_items):
        errors.append({"path": path, "message": f"expected at least {min_items} items"})
    if max_items is not None and len(normalized) > int(max_items):
        errors.append({"path": path, "message": f"expected at most {max_items} items"})
    return normalized


def _validate_string(schema: dict[str, Any], value: Any, path: str, errors: list[dict[str, Any]]) -> str:
    if not isinstance(value, str):
        errors.append({"path": path, "message": "expected string"})
        return ""
    enum = schema.get("enum")
    if enum is not None and value not in enum:
        errors.append({"path": path, "message": f"expected one of {enum}"})
    return value


def _validate_integer(schema: dict[str, Any], value: Any, path: str, errors: list[dict[str, Any]]) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append({"path": path, "message": "expected integer"})
        return 0
    return _check_numeric_bounds(schema, value, path, errors)


def _validate_number(schema: dict[str, Any], value: Any, path: str, errors: list[dict[str, Any]]) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append({"path": path, "message": "expected number"})
        return 0
    return _check_numeric_bounds(schema, value, path, errors)


def _validate_boolean(schema: dict[str, Any], value: Any, path: str, errors: list[dict[str, Any]]) -> bool:
    if not isinstance(value, bool):
        errors.append({"path": path, "message": "expected boolean"})
        return False
    return value


def _check_numeric_bounds(schema: dict[str, Any], value: int | float, path: str, errors: list[dict[str, Any]]):
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if minimum is not None and value < minimum:
        errors.append({"path": path, "message": f"must be >= {minimum}"})
    if maximum is not None and value > maximum:
        errors.append({"path": path, "message": f"must be <= {maximum}"})
    return value
