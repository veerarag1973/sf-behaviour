"""Tests for new CLI features — init, watch, --tag, --jobs, --retry, --report."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sf_behaviour.cli import _build_parser, _cmd_init, _STARTER_YAML


class TestInit:
    def test_creates_starter_yaml(self, tmp_path):
        args = argparse.Namespace(dir=str(tmp_path))
        code = _cmd_init(args)
        assert code == 0
        target = tmp_path / "tests.yaml"
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "version:" in content
        assert "cases:" in content

    def test_init_refuses_overwrite(self, tmp_path):
        (tmp_path / "tests.yaml").write_text("existing", encoding="utf-8")
        args = argparse.Namespace(dir=str(tmp_path))
        code = _cmd_init(args)
        assert code == 1

    def test_init_default_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(dir=".")
        code = _cmd_init(args)
        assert code == 0
        assert (tmp_path / "tests.yaml").exists()

    def test_starter_yaml_is_parseable(self, tmp_path):
        """Verify _STARTER_YAML produces a valid TestSuite via parse_yaml."""
        from sf_behaviour.yaml_parser import parse_yaml

        target = tmp_path / "tests.yaml"
        target.write_text(_STARTER_YAML, encoding="utf-8")
        suite = parse_yaml(str(target))
        assert len(suite.cases) >= 1
        assert suite.version == "1.0"


class TestBuildParserNewFlags:
    def test_tag_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["run", "test.yaml", "--tag", "safety", "--tag", "privacy"])
        assert args.tag == ["safety", "privacy"]

    def test_jobs_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["run", "test.yaml", "--jobs", "4"])
        assert args.jobs == 4

    def test_retry_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["run", "test.yaml", "--retry", "3"])
        assert args.retry == 3

    def test_report_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["run", "test.yaml", "--report", "report.html"])
        assert args.report == "report.html"

    def test_init_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["init", "/tmp/mydir"])
        assert args.command == "init"
        assert args.dir == "/tmp/mydir"

    def test_watch_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["watch", "test.yaml"])
        assert args.command == "watch"
        assert args.test_file == "test.yaml"

    def test_defaults(self):
        parser = _build_parser()
        args = parser.parse_args(["run", "test.yaml"])
        assert args.tag == []
        assert args.jobs == 1
        assert args.retry == 0
        assert args.report == ""


class TestReportIntegration:
    """Verify that --report actually writes a file."""

    def test_report_html_written(self, tmp_path):
        from sf_behaviour.eval import EvalResult
        from sf_behaviour.report import build_report, render_html

        result = EvalResult(
            case_id="tc-1",
            case_name="demo",
            scorer_name="refusal",
            score=1.0,
            threshold=0.5,
            passed=True,
            reason="refusal phrase detected",
            response_text="I can't help with that",
            latency_ms=100.0,
            timestamp="2026-04-16T00:00:00+00:00",
            model="gpt-4o",
            endpoint="https://api.openai.com/v1",
            tags=[],
            error=None,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )
        report = build_report([result])
        html = render_html(report)
        out = tmp_path / "report.html"
        out.write_text(html, encoding="utf-8")
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "<html" in content
        assert "demo" in content

    def test_report_markdown_written(self, tmp_path):
        from sf_behaviour.eval import EvalResult
        from sf_behaviour.report import build_report, render_markdown

        result = EvalResult(
            case_id="tc-1",
            case_name="demo",
            scorer_name="refusal",
            score=1.0,
            threshold=0.5,
            passed=True,
            reason="ok",
            response_text="response",
            latency_ms=50.0,
            timestamp="2026-04-16T00:00:00+00:00",
            model="gpt-4o",
            endpoint="https://api.openai.com/v1",
            tags=["safety"],
            error=None,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )
        report = build_report([result])
        md = render_markdown(report)
        out = tmp_path / "report.md"
        out.write_text(md, encoding="utf-8")
        assert out.exists()
        assert "demo" in md
