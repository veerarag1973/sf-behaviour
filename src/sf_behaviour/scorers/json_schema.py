"""JSONSchemaScorer — validates the model response against a JSON schema.

Scores 1.0 when the response is valid JSON that conforms to the schema,
0.0 otherwise.  Uses ``spanforge.schema.validate`` for lightweight
JSON Schema validation.

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

from spanforge.schema import validate as _sf_validate

from ..eval import EvalScorer

if TYPE_CHECKING:
    from ..yaml_parser import TestCase


def _validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Validate *instance* against *schema* using spanforge."""
    return _sf_validate(instance, schema, path=path)


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
