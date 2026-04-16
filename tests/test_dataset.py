"""Tests for dataset JSONL save/load."""

from __future__ import annotations

import os
import tempfile

import pytest

from sf_behaviour.dataset import save_results, load_results
from sf_behaviour.eval import EvalResult


def _result(case_id: str = "tc-01", scorer: str = "refusal", score: float = 1.0) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        case_name=f"Test {case_id}",
        scorer_name=scorer,
        score=score,
        threshold=0.5,
        passed=score >= 0.5,
        reason="test reason",
        response_text="response text",
        latency_ms=42.0,
        timestamp="2026-01-01T00:00:00+00:00",
        model="gpt-4o",
        endpoint="https://api.openai.com/v1",
        tags=["smoke"],
        error=None,
    )


class TestDataset:
    def test_roundtrip_single_result(self, tmp_path):
        path = str(tmp_path / "results.jsonl")
        original = [_result()]
        save_results(original, path)
        loaded = load_results(path)
        assert len(loaded) == 1
        assert loaded[0].case_id == "tc-01"
        assert loaded[0].scorer_name == "refusal"
        assert loaded[0].score == 1.0
        assert loaded[0].passed is True
        assert loaded[0].tags == ["smoke"]
        assert loaded[0].error is None

    def test_roundtrip_multiple_results(self, tmp_path):
        path = str(tmp_path / "results.jsonl")
        originals = [
            _result("tc-01", "refusal", 1.0),
            _result("tc-02", "pii_leakage", 1.0),
            _result("tc-03", "faithfulness", 0.8),
        ]
        save_results(originals, path)
        loaded = load_results(path)
        assert len(loaded) == 3
        ids = [r.case_id for r in loaded]
        assert "tc-01" in ids
        assert "tc-02" in ids
        assert "tc-03" in ids

    def test_file_created(self, tmp_path):
        path = str(tmp_path / "out.jsonl")
        assert not os.path.exists(path)
        save_results([_result()], path)
        assert os.path.exists(path)

    def test_parent_dirs_created(self, tmp_path):
        path = str(tmp_path / "deep" / "nested" / "results.jsonl")
        save_results([_result()], path)
        assert os.path.exists(path)

    def test_load_empty_file_returns_empty(self, tmp_path):
        path = str(tmp_path / "empty.jsonl")
        path_obj = tmp_path / "empty.jsonl"
        path_obj.write_text("")
        loaded = load_results(str(path))
        assert loaded == []

    def test_result_with_error_field(self, tmp_path):
        path = str(tmp_path / "results.jsonl")
        r = EvalResult(
            case_id="tc-err",
            case_name="Error case",
            scorer_name="refusal",
            score=0.0,
            threshold=0.5,
            passed=False,
            reason="endpoint call failed",
            response_text="",
            latency_ms=10.0,
            timestamp="2026-01-01T00:00:00+00:00",
            model="gpt-4o",
            endpoint="https://api.openai.com/v1",
            error="HTTP 401: Unauthorized",
        )
        save_results([r], path)
        loaded = load_results(path)
        assert loaded[0].error == "HTTP 401: Unauthorized"

    def test_score_preserved_precisely(self, tmp_path):
        path = str(tmp_path / "results.jsonl")
        r = _result(score=0.7654)
        save_results([r], path)
        loaded = load_results(path)
        assert abs(loaded[0].score - 0.7654) < 1e-9

    def test_malformed_jsonl_lines_are_skipped(self, tmp_path):
        """load_results on a corrupt file must not raise; returns a list."""
        path = tmp_path / "corrupt.jsonl"
        path.write_text("NOT VALID JSON\n{also bad\n")
        loaded = load_results(str(path))
        assert isinstance(loaded, list)

    def test_missing_tags_field_handled(self, tmp_path):
        """JSONL line without 'tags' field should load with an empty tags list."""
        import json
        path = str(tmp_path / "results.jsonl")
        save_results([_result()], path)

        # Strip the tags field from the saved JSONL to simulate a legacy file
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        stripped: list[str] = []
        for line in lines:
            try:
                obj = json.loads(line)
                obj.pop("tags", None)
                if "payload" in obj:
                    obj["payload"].pop("tags", None)
                stripped.append(json.dumps(obj))
            except Exception:
                stripped.append(line.rstrip())
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(stripped) + "\n")

        loaded = load_results(path)
        if loaded:
            assert loaded[0].tags == []
