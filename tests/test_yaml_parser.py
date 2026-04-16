"""Tests for the YAML parser."""

from __future__ import annotations

import textwrap
import tempfile
import os
import pytest

from sf_behaviour.yaml_parser import parse_yaml, TestSuite, TestCase, Message, ScorerConfig


def _write(content: str) -> str:
    fh = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    fh.write(textwrap.dedent(content))
    fh.close()
    return fh.name


class TestParseYaml:
    def test_minimal_suite(self):
        path = _write("""
            version: "1.0"
            cases:
              - id: tc-01
                name: Basic test
                messages:
                  - role: user
                    content: Hello
                scorers:
                  - refusal
        """)
        try:
            suite = parse_yaml(path)
            assert isinstance(suite, TestSuite)
            assert suite.version == "1.0"
            assert len(suite.cases) == 1
            case = suite.cases[0]
            assert case.id == "tc-01"
            assert case.name == "Basic test"
            assert len(case.messages) == 1
            assert case.messages[0].role == "user"
            assert case.messages[0].content == "Hello"
            assert len(case.scorers) == 1
            assert case.scorers[0].name == "refusal"
            assert case.scorers[0].threshold == 0.5
        finally:
            os.unlink(path)

    def test_defaults_applied(self):
        path = _write("""
            version: "1.0"
            defaults:
              model: gpt-3.5-turbo
              endpoint: https://custom.example.com/v1
              timeout_seconds: 60
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: Hi
                scorers:
                  - pii_leakage
        """)
        try:
            suite = parse_yaml(path)
            assert suite.default_model == "gpt-3.5-turbo"
            assert suite.default_endpoint == "https://custom.example.com/v1"
            assert suite.default_timeout_seconds == 60
        finally:
            os.unlink(path)

    def test_scorer_as_mapping(self):
        path = _write("""
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: Summarize this.
                context: Short context.
                scorers:
                  - name: faithfulness
                    threshold: 0.7
        """)
        try:
            suite = parse_yaml(path)
            sc = suite.cases[0].scorers[0]
            assert sc.name == "faithfulness"
            assert sc.threshold == 0.7
            assert suite.cases[0].context == "Short context."
        finally:
            os.unlink(path)

    def test_tags_and_per_case_overrides(self):
        path = _write("""
            version: "1.0"
            cases:
              - id: tc-01
                name: Override case
                model: gpt-4-turbo
                endpoint: https://other.com/v1
                messages:
                  - role: user
                    content: Hi
                scorers:
                  - refusal
                tags:
                  - safety
                  - smoke
        """)
        try:
            case = parse_yaml(path).cases[0]
            assert case.model == "gpt-4-turbo"
            assert case.endpoint == "https://other.com/v1"
            assert case.tags == ["safety", "smoke"]
        finally:
            os.unlink(path)

    def test_missing_id_raises(self):
        path = _write("""
            version: "1.0"
            cases:
              - messages:
                  - role: user
                    content: Hi
                scorers:
                  - refusal
        """)
        try:
            with pytest.raises(ValueError, match="missing 'id'"):
                parse_yaml(path)
        finally:
            os.unlink(path)

    def test_missing_messages_raises(self):
        path = _write("""
            version: "1.0"
            cases:
              - id: tc-01
                scorers:
                  - refusal
        """)
        try:
            with pytest.raises(ValueError, match="messages"):
                parse_yaml(path)
        finally:
            os.unlink(path)

    def test_empty_cases_raises(self):
        path = _write("""
            version: "1.0"
            cases: []
        """)
        try:
            with pytest.raises(ValueError, match="cases"):
                parse_yaml(path)
        finally:
            os.unlink(path)

    def test_multiple_messages(self):
        path = _write("""
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: system
                    content: You are a helpful assistant.
                  - role: user
                    content: Hello!
                scorers:
                  - refusal
        """)
        try:
            case = parse_yaml(path).cases[0]
            assert len(case.messages) == 2
            assert case.messages[0].role == "system"
        finally:
            os.unlink(path)
