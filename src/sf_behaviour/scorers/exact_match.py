"""ExactMatchScorer — checks if the response contains or exactly matches expected text.

Supports three modes controlled via ``params``:

* **contains** (default): ``expected`` substring appears in the response.
* **equals**: response text exactly equals ``expected`` (after strip).
* **regex**: response matches a regex ``pattern``.

Score semantics
---------------
1.0  Match found.
0.0  No match.

.. code-block:: yaml

    scorers:
      - name: exact_match
        threshold: 1.0
        expected: "42"
        mode: contains        # contains | equals | regex
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..eval import EvalScorer

if TYPE_CHECKING:
    from ..yaml_parser import TestCase


class ExactMatchScorer(EvalScorer):
    """Scores 1.0 when the response matches the expected text."""

    name: str = "exact_match"

    def score(self, case: "TestCase", response: str) -> tuple[float, str]:
        params = {}
        for sc in case.scorers:
            if sc.name == self.name:
                params = sc.params
                break

        mode = str(params.get("mode", "contains")).lower()
        expected = str(params.get("expected", ""))
        pattern = str(params.get("pattern", ""))

        text = response.strip()

        if mode == "equals":
            if not expected:
                return 0.0, "no 'expected' value configured for equals mode"
            if text == expected.strip():
                return 1.0, f"exact match: response equals expected"
            return 0.0, f"no match: expected {expected!r}, got {text[:80]!r}"

        if mode == "regex":
            if not pattern:
                return 0.0, "no 'pattern' configured for regex mode"
            if re.search(pattern, text, re.IGNORECASE):
                return 1.0, f"regex match: pattern {pattern!r} found"
            return 0.0, f"no regex match for pattern {pattern!r}"

        # Default: contains
        if not expected:
            return 0.0, "no 'expected' value configured for contains mode"
        if expected in text:
            return 1.0, f"contains match: {expected!r} found in response"
        return 0.0, f"no match: {expected!r} not found in response"
