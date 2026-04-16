"""Tests for new yaml_parser features — env var interpolation, skip, parse_csv, parse_dataset."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

from sf_behaviour.yaml_parser import (
    parse_csv,
    parse_dataset,
    parse_yaml,
    _interpolate_env,
    _interpolate_data,
)


# ===========================================================================
# Environment variable interpolation
# ===========================================================================

class TestEnvVarInterpolation:
    def test_simple_var(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        assert _interpolate_env("prefix-${MY_VAR}-suffix") == "prefix-hello-suffix"

    def test_default_value_used(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        assert _interpolate_env("${MISSING_VAR:fallback}") == "fallback"

    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "real")
        assert _interpolate_env("${MY_VAR:default}") == "real"

    def test_unresolved_no_default(self, monkeypatch):
        monkeypatch.delenv("NOPE", raising=False)
        assert _interpolate_env("${NOPE}") == "${NOPE}"

    def test_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("A", "1")
        monkeypatch.setenv("B", "2")
        assert _interpolate_env("${A}+${B}") == "1+2"

    def test_interpolate_data_dict(self, monkeypatch):
        monkeypatch.setenv("X", "val")
        data = {"key": "${X}", "nested": {"k2": "${X}"}}
        result = _interpolate_data(data)
        assert result == {"key": "val", "nested": {"k2": "val"}}

    def test_interpolate_data_list(self, monkeypatch):
        monkeypatch.setenv("X", "val")
        data = ["${X}", "plain"]
        result = _interpolate_data(data)
        assert result == ["val", "plain"]

    def test_interpolate_data_non_string(self):
        assert _interpolate_data(42) == 42
        assert _interpolate_data(None) is None


class TestInterpolationInYaml:
    def test_yaml_env_var_in_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_MODEL", "gpt-4o-mini")
        yaml_content = textwrap.dedent("""\
            version: "1.0"
            defaults:
              model: "${MY_MODEL}"
              endpoint: "https://api.openai.com/v1"
            cases:
              - id: tc-01
                name: test
                messages:
                  - role: user
                    content: "Hello"
                scorers:
                  - refusal
        """)
        p = tmp_path / "test.yaml"
        p.write_text(yaml_content, encoding="utf-8")
        suite = parse_yaml(str(p))
        assert suite.default_model == "gpt-4o-mini"


# ===========================================================================
# Skip field
# ===========================================================================

class TestSkipField:
    def test_skip_parsed_from_yaml(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            version: "1.0"
            cases:
              - id: tc-run
                name: run
                messages:
                  - role: user
                    content: "Hi"
                scorers:
                  - refusal
              - id: tc-skip
                name: skip
                skip: true
                messages:
                  - role: user
                    content: "Hi"
                scorers:
                  - refusal
        """)
        p = tmp_path / "test.yaml"
        p.write_text(yaml_content, encoding="utf-8")
        suite = parse_yaml(str(p))
        assert suite.cases[0].skip is False
        assert suite.cases[1].skip is True


# ===========================================================================
# parse_csv
# ===========================================================================

class TestParseCSV:
    def test_basic_csv(self, tmp_path):
        csv_content = "id,prompt,expected,tags\ntc-1,What is 2+2?,4,math\ntc-2,Say hi,hello,greeting\n"
        p = tmp_path / "data.csv"
        p.write_text(csv_content, encoding="utf-8")
        suite = parse_csv(str(p))
        assert len(suite.cases) == 2
        assert suite.cases[0].id == "tc-1"
        assert suite.cases[0].messages[0].content == "What is 2+2?"
        assert suite.cases[0].scorers[0].params.get("expected") == "4"
        assert suite.cases[0].tags == ["math"]

    def test_csv_auto_ids(self, tmp_path):
        csv_content = "prompt\nHello\nWorld\n"
        p = tmp_path / "data.csv"
        p.write_text(csv_content, encoding="utf-8")
        suite = parse_csv(str(p))
        assert suite.cases[0].id == "row-1"
        assert suite.cases[1].id == "row-2"

    def test_tsv_file(self, tmp_path):
        tsv_content = "id\tprompt\ntc-1\tHello\n"
        p = tmp_path / "data.tsv"
        p.write_text(tsv_content, encoding="utf-8")
        suite = parse_csv(str(p))
        assert len(suite.cases) == 1

    def test_empty_csv_raises(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("id,prompt\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no data rows"):
            parse_csv(str(p))


# ===========================================================================
# parse_dataset (JSONL)
# ===========================================================================

class TestParseDataset:
    def test_basic_jsonl(self, tmp_path):
        lines = [
            json.dumps({"id": "tc-1", "messages": [{"role": "user", "content": "Hi"}], "expected": "Hello"}),
            json.dumps({"id": "tc-2", "messages": [{"role": "user", "content": "Bye"}]}),
        ]
        p = tmp_path / "data.jsonl"
        p.write_text("\n".join(lines), encoding="utf-8")
        suite = parse_dataset(str(p))
        assert len(suite.cases) == 2
        assert suite.cases[0].scorers[0].params.get("expected") == "Hello"
        assert suite.cases[1].scorers[0].params == {}

    def test_jsonl_with_prompt_field(self, tmp_path):
        line = json.dumps({"id": "tc-1", "prompt": "What is AI?"})
        p = tmp_path / "data.jsonl"
        p.write_text(line, encoding="utf-8")
        suite = parse_dataset(str(p))
        assert suite.cases[0].messages[0].content == "What is AI?"

    def test_empty_jsonl_raises(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="no data rows"):
            parse_dataset(str(p))

    def test_jsonl_tags(self, tmp_path):
        line = json.dumps({"id": "tc-1", "prompt": "Hi", "tags": ["a", "b"]})
        p = tmp_path / "data.jsonl"
        p.write_text(line, encoding="utf-8")
        suite = parse_dataset(str(p))
        assert suite.cases[0].tags == ["a", "b"]
