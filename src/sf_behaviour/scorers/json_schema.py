"""JSONSchemaScorer — validates the model response against a JSON schema.

Scores 1.0 when the response is valid JSON that conforms to the schema,
0.0 otherwise.  Uses a lightweight built-in validator (no external
dependencies beyond the standard library).

Configuration via ``params`` on the scorer config:

* **schema** (dict):  The JSON Schema to validate against.

.. code-block:: yaml

    scorers:
      - name: json_schema
        threshold: 1.0
        schema:
          type: object
          required: [answer]
          properties:
            answer:
              type: string
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ..eval import EvalScorer

if TYPE_CHECKING:
    from ..yaml_parser import TestCase


def _validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Minimal JSON Schema validator (type, required, properties, items, enum)."""
    errors: list[str] = []
    stype = schema.get("type")
    if stype:
        type_map = {
            "string": str, "number": (int, float), "integer": int,
            "boolean": bool, "array": list, "object": dict, "null": type(None),
        }
        expected = type_map.get(stype)
        if expected and not isinstance(instance, expected):
            errors.append(f"{path}: expected type {stype}, got {type(instance).__name__}")
            return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} not in enum {schema['enum']}")

    if stype == "object" and isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property '{key}'")
        props = schema.get("properties", {})
        for key, sub_schema in props.items():
            if key in instance:
                errors.extend(_validate(instance[key], sub_schema, f"{path}.{key}"))

    if stype == "array" and isinstance(instance, list):
        items_schema = schema.get("items")
        if items_schema:
            for i, item in enumerate(instance):
                errors.extend(_validate(item, items_schema, f"{path}[{i}]"))

    return errors


class JSONSchemaScorer(EvalScorer):
    """Scores 1.0 when the response is valid JSON conforming to the schema."""

    name: str = "json_schema"

    def score(self, case: "TestCase", response: str) -> tuple[float, str]:
        params: dict[str, Any] = {}
        for sc in case.scorers:
            if sc.name == self.name:
                params = sc.params
                break

        schema = params.get("schema")
        if not schema or not isinstance(schema, dict):
            return 0.0, "no 'schema' dict configured for json_schema scorer"

        text = response.strip()
        # Try to extract JSON from code-fenced responses
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return 0.0, f"response is not valid JSON: {exc}"

        errors = _validate(data, schema)
        if errors:
            return 0.0, f"schema validation failed: {'; '.join(errors[:5])}"
        return 1.0, "response conforms to JSON schema"
