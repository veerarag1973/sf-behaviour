"""Tests for ExactMatchScorer, LLMJudgeScorer, JSONSchemaScorer."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from sf_behaviour.scorers.exact_match import ExactMatchScorer
from sf_behaviour.scorers.llm_judge import LLMJudgeScorer, _extract_score
from sf_behaviour.scorers.json_schema import JSONSchemaScorer, _validate
from sf_behaviour.yaml_parser import Message, ScorerConfig, TestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _case(scorer_name: str, **params) -> TestCase:
    return TestCase(
        id="tc-new",
        name="tc-new",
        messages=[Message(role="user", content="test")],
        scorers=[ScorerConfig(name=scorer_name, threshold=0.5, params=params)],
    )


# ===========================================================================
# ExactMatchScorer
# ===========================================================================

class TestExactMatchScorer:
    def test_contains_match(self):
        scorer = ExactMatchScorer()
        case = _case("exact_match", expected="42")
        score, reason = scorer.score(case, "The answer is 42 indeed")
        assert score == 1.0
        assert "contains match" in reason

    def test_contains_no_match(self):
        scorer = ExactMatchScorer()
        case = _case("exact_match", expected="42")
        score, reason = scorer.score(case, "The answer is unknown")
        assert score == 0.0

    def test_equals_match(self):
        scorer = ExactMatchScorer()
        case = _case("exact_match", expected="hello world", mode="equals")
        score, _ = scorer.score(case, "  hello world  ")
        assert score == 1.0

    def test_equals_no_match(self):
        scorer = ExactMatchScorer()
        case = _case("exact_match", expected="hello", mode="equals")
        score, _ = scorer.score(case, "hello world")
        assert score == 0.0

    def test_regex_match(self):
        scorer = ExactMatchScorer()
        case = _case("exact_match", pattern=r"\d{3}-\d{4}", mode="regex")
        score, _ = scorer.score(case, "Call 555-1234 now")
        assert score == 1.0

    def test_regex_no_match(self):
        scorer = ExactMatchScorer()
        case = _case("exact_match", pattern=r"\d{3}-\d{4}", mode="regex")
        score, _ = scorer.score(case, "No phone number here")
        assert score == 0.0

    def test_missing_expected_contains(self):
        scorer = ExactMatchScorer()
        case = _case("exact_match")
        score, reason = scorer.score(case, "anything")
        assert score == 0.0
        assert "no 'expected' value" in reason

    def test_missing_expected_equals(self):
        scorer = ExactMatchScorer()
        case = _case("exact_match", mode="equals")
        score, _ = scorer.score(case, "anything")
        assert score == 0.0

    def test_missing_pattern_regex(self):
        scorer = ExactMatchScorer()
        case = _case("exact_match", mode="regex")
        score, reason = scorer.score(case, "anything")
        assert score == 0.0
        assert "no 'pattern'" in reason


# ===========================================================================
# LLMJudgeScorer — _extract_score helper
# ===========================================================================

class TestExtractScore:
    def test_score_out_of_10(self):
        assert _extract_score("I give this a 7/10") == 0.7

    def test_score_colon(self):
        assert _extract_score("Score: 8") == 0.8

    def test_bare_number(self):
        assert _extract_score("The quality is 9") == 0.9

    def test_no_score(self):
        assert _extract_score("This is great") is None

    def test_zero(self):
        assert _extract_score("0/10") == 0.0

    def test_ten(self):
        assert _extract_score("10/10") == 1.0

    def test_decimal_score(self):
        result = _extract_score("7.5/10")
        assert result == 0.75


class TestLLMJudgeScorer:
    def test_no_endpoint_configured(self):
        scorer = LLMJudgeScorer()
        case = _case("llm_judge")
        score, reason = scorer.score(case, "response")
        assert score == 0.0
        assert "no judge_endpoint" in reason

    def test_successful_judge_call(self):
        scorer = LLMJudgeScorer()
        case = TestCase(
            id="tc-judge",
            name="tc-judge",
            messages=[Message(role="user", content="Hi")],
            scorers=[ScorerConfig(
                name="llm_judge",
                threshold=0.5,
                params={
                    "judge_endpoint": "http://judge.test/v1",
                    "judge_model": "gpt-4o-mini",
                    "rubric": "Rate helpfulness 0-10",
                },
            )],
            endpoint="http://model.test/v1",
        )
        body = json.dumps({"choices": [{"message": {"content": "8/10"}}]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            score, reason = scorer.score(case, "helpful response")
        assert score == 0.8
        assert "judge score" in reason

    def test_judge_call_fails(self):
        scorer = LLMJudgeScorer()
        case = TestCase(
            id="tc-judge-err",
            name="tc-judge-err",
            messages=[Message(role="user", content="Hi")],
            scorers=[ScorerConfig(
                name="llm_judge",
                threshold=0.5,
                params={"judge_endpoint": "http://judge.test/v1"},
            )],
            endpoint="http://model.test/v1",
        )
        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            score, reason = scorer.score(case, "response")
        assert score == 0.0
        assert "judge call failed" in reason


# ===========================================================================
# JSONSchemaScorer
# ===========================================================================

class TestJSONSchemaValidate:
    def test_valid_object(self):
        schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
        assert _validate({"name": "Alice"}, schema) == []

    def test_missing_required(self):
        schema = {"type": "object", "required": ["name"]}
        errors = _validate({}, schema)
        assert any("missing required property 'name'" in e for e in errors)

    def test_wrong_type(self):
        schema = {"type": "string"}
        errors = _validate(42, schema)
        assert any("expected type string" in e for e in errors)

    def test_enum_valid(self):
        schema = {"enum": ["red", "green", "blue"]}
        assert _validate("red", schema) == []

    def test_enum_invalid(self):
        schema = {"enum": ["red", "green", "blue"]}
        errors = _validate("yellow", schema)
        assert len(errors) == 1

    def test_array_items(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        assert _validate([1, 2, 3], schema) == []
        errors = _validate([1, "two"], schema)
        assert len(errors) == 1


class TestJSONSchemaScorer:
    def test_valid_json_response(self):
        scorer = JSONSchemaScorer()
        case = _case(
            "json_schema",
            schema={"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}},
        )
        score, reason = scorer.score(case, '{"answer": "42"}')
        assert score == 1.0
        assert "conforms" in reason

    def test_invalid_json(self):
        scorer = JSONSchemaScorer()
        case = _case("json_schema", schema={"type": "object"})
        score, reason = scorer.score(case, "not json at all")
        assert score == 0.0
        assert "not valid JSON" in reason

    def test_schema_violation(self):
        scorer = JSONSchemaScorer()
        case = _case(
            "json_schema",
            schema={"type": "object", "required": ["answer"]},
        )
        score, reason = scorer.score(case, '{"other": "value"}')
        assert score == 0.0
        assert "missing required" in reason

    def test_no_schema_configured(self):
        scorer = JSONSchemaScorer()
        case = _case("json_schema")
        score, reason = scorer.score(case, '{}')
        assert score == 0.0
        assert "no 'schema'" in reason

    def test_code_fenced_json(self):
        scorer = JSONSchemaScorer()
        case = _case("json_schema", schema={"type": "object"})
        response = '```json\n{"key": "value"}\n```'
        score, _ = scorer.score(case, response)
        assert score == 1.0
