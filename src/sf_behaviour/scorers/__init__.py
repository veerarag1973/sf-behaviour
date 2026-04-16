"""Built-in scorers for sf-behaviour.

Available scorers
-----------------
- ``refusal``       — detects correct model refusals
- ``pii_leakage``   — detects PII in model output (uses spanforge.redact)
- ``faithfulness``  — measures response faithfulness to a provided context
- ``exact_match``   — checks if response contains/equals/regex-matches expected text
- ``llm_judge``     — uses a second LLM as a judge with a configurable rubric
- ``json_schema``   — validates response JSON against a JSON schema
"""

from .refusal import RefusalScorer
from .pii_leakage import PIILeakageScorer
from .faithfulness import FaithfulnessScorer
from .exact_match import ExactMatchScorer
from .llm_judge import LLMJudgeScorer
from .json_schema import JSONSchemaScorer
from ..eval import EvalScorer

BUILT_IN_SCORERS: dict[str, EvalScorer] = {
    "refusal": RefusalScorer(),
    "pii_leakage": PIILeakageScorer(),
    "faithfulness": FaithfulnessScorer(),
    "exact_match": ExactMatchScorer(),
    "llm_judge": LLMJudgeScorer(),
    "json_schema": JSONSchemaScorer(),
}

__all__ = [
    "RefusalScorer",
    "PIILeakageScorer",
    "FaithfulnessScorer",
    "ExactMatchScorer",
    "LLMJudgeScorer",
    "JSONSchemaScorer",
    "BUILT_IN_SCORERS",
]
