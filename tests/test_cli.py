"""Tests for the CLI entry points (sf-behaviour run / compare)."""

from __future__ import annotations

import json
import os
import sys
import textwrap
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from sf_behaviour.cli import _build_parser, _cmd_run, _cmd_compare, _print_results
from sf_behaviour.eval import EvalResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(case_id: str = "tc-01", passed: bool = True, score: float = 1.0,
            scorer: str = "refusal", error: str | None = None) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        case_name=case_id,
        scorer_name=scorer,
        score=score,
        threshold=0.5,
        passed=passed,
        reason="test",
        response_text="some response",
        latency_ms=42.0,
        timestamp="2026-01-01T00:00:00+00:00",
        model="gpt-4o",
        endpoint="https://api.openai.com/v1",
        error=error,
    )


def _mock_openai_response(content: str) -> MagicMock:
    body = json.dumps({
        "choices": [{"message": {"content": content}}]
    }).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _yaml_file(tmp_path, content: str) -> str:
    p = tmp_path / "cases.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# _print_results
# ---------------------------------------------------------------------------

class TestPrintResults:
    def test_prints_pass_and_fail(self, capsys):
        results = [_result("tc-01", passed=True), _result("tc-02", passed=False, score=0.0)]
        _print_results(results)
        out = capsys.readouterr().out
        assert "tc-01" in out
        assert "tc-02" in out

    def test_verbose_shows_reason_latency(self, capsys):
        _print_results([_result()], verbose=True)
        out = capsys.readouterr().out
        assert "reason" in out
        assert "latency" in out

    def test_error_printed(self, capsys):
        _print_results([_result(error="HTTP 401: Unauthorized")])
        out = capsys.readouterr().out
        assert "error=" in out


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_run_subcommand(self):
        p = _build_parser()
        args = p.parse_args(["run", "cases.yaml"])
        assert args.command == "run"
        assert args.test_file == "cases.yaml"

    def test_run_flags(self):
        p = _build_parser()
        args = p.parse_args([
            "run", "cases.yaml",
            "--endpoint", "http://x.com",
            "--model", "gpt-4",
            "--api-key", "sk-test",
            "--output", "out.jsonl",
            "--baseline", "base.jsonl",
            "--score-drop-threshold", "0.2",
            "--timeout", "60",
            "--verbose",
        ])
        assert args.endpoint == "http://x.com"
        assert args.model == "gpt-4"
        assert args.api_key == "sk-test"
        assert args.output == "out.jsonl"
        assert args.baseline == "base.jsonl"
        assert args.score_drop_threshold == 0.2
        assert args.timeout == 60
        assert args.verbose is True

    def test_compare_subcommand(self):
        p = _build_parser()
        args = p.parse_args(["compare", "base.jsonl", "curr.jsonl"])
        assert args.command == "compare"
        assert args.baseline == "base.jsonl"
        assert args.current == "curr.jsonl"


# ---------------------------------------------------------------------------
# _cmd_run
# ---------------------------------------------------------------------------

class TestCmdRun:
    def _args(self, test_file: str, **kw):
        p = _build_parser()
        argv = ["run", test_file]
        for k, v in kw.items():
            argv += [f"--{k.replace('_', '-')}", str(v)]
        return p.parse_args(argv)

    def test_all_pass_returns_0(self, tmp_path):
        yaml = _yaml_file(tmp_path, """
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: hi
                scorers:
                  - refusal
        """)
        args = self._args(yaml)
        with patch("urllib.request.urlopen", return_value=_mock_openai_response("I can't help.")):
            code = _cmd_run(args)
        assert code == 0

    def test_failure_returns_1(self, tmp_path):
        yaml = _yaml_file(tmp_path, """
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: hi
                scorers:
                  - refusal
        """)
        args = self._args(yaml)
        with patch("urllib.request.urlopen", return_value=_mock_openai_response("Sure, here you go!")):
            code = _cmd_run(args)
        assert code == 1

    def test_bad_yaml_returns_1(self, tmp_path, capsys):
        yaml = str(tmp_path / "missing.yaml")
        args = self._args(yaml)
        code = _cmd_run(args)
        assert code == 1
        assert "Error parsing" in capsys.readouterr().err

    def test_saves_output(self, tmp_path):
        yaml = _yaml_file(tmp_path, """
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: hi
                scorers:
                  - refusal
        """)
        out_file = str(tmp_path / "results.jsonl")
        args = self._args(yaml, output=out_file)
        with patch("urllib.request.urlopen", return_value=_mock_openai_response("I can't.")):
            _cmd_run(args)
        assert os.path.exists(out_file)

    def test_baseline_no_regression_returns_0(self, tmp_path):
        yaml = _yaml_file(tmp_path, """
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: hi
                scorers:
                  - refusal
        """)
        from sf_behaviour.dataset import save_results
        baseline_file = str(tmp_path / "base.jsonl")
        save_results([_result("tc-01", passed=True, score=1.0)], baseline_file)
        p = _build_parser()
        args = p.parse_args(["run", yaml, "--baseline", baseline_file])
        with patch("urllib.request.urlopen", return_value=_mock_openai_response("I can't.")):
            code = _cmd_run(args)
        assert code == 0

    def test_baseline_regression_returns_1(self, tmp_path):
        yaml = _yaml_file(tmp_path, """
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: hi
                scorers:
                  - refusal
        """)
        from sf_behaviour.dataset import save_results
        baseline_file = str(tmp_path / "base.jsonl")
        save_results([_result("tc-01", passed=True, score=1.0)], baseline_file)
        p = _build_parser()
        args = p.parse_args(["run", yaml, "--baseline", baseline_file])
        with patch("urllib.request.urlopen", return_value=_mock_openai_response("Sure!")):
            code = _cmd_run(args)
        assert code == 1

    def test_bad_baseline_returns_1(self, tmp_path, capsys):
        yaml = _yaml_file(tmp_path, """
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: hi
                scorers:
                  - refusal
        """)
        p = _build_parser()
        args = p.parse_args(["run", yaml, "--baseline", "nonexistent.jsonl"])
        with patch("urllib.request.urlopen", return_value=_mock_openai_response("I can't.")):
            code = _cmd_run(args)
        assert code == 1
        assert "Error loading baseline" in capsys.readouterr().err

    def test_verbose_flag(self, tmp_path, capsys):
        yaml = _yaml_file(tmp_path, """
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: hi
                scorers:
                  - refusal
        """)
        p = _build_parser()
        args = p.parse_args(["run", yaml, "--verbose"])
        with patch("urllib.request.urlopen", return_value=_mock_openai_response("I can't.")):
            _cmd_run(args)
        out = capsys.readouterr().out
        assert "reason" in out


# ---------------------------------------------------------------------------
# _cmd_compare
# ---------------------------------------------------------------------------

class TestCmdCompare:
    def test_no_regression_returns_0(self, tmp_path):
        from sf_behaviour.dataset import save_results
        base = str(tmp_path / "base.jsonl")
        curr = str(tmp_path / "curr.jsonl")
        save_results([_result("tc-01", score=1.0)], base)
        save_results([_result("tc-01", score=1.0)], curr)
        p = _build_parser()
        args = p.parse_args(["compare", base, curr])
        code = _cmd_compare(args)
        assert code == 0

    def test_regression_returns_1(self, tmp_path):
        from sf_behaviour.dataset import save_results
        base = str(tmp_path / "base.jsonl")
        curr = str(tmp_path / "curr.jsonl")
        save_results([_result("tc-01", passed=True, score=1.0)], base)
        save_results([_result("tc-01", passed=False, score=0.0)], curr)
        p = _build_parser()
        args = p.parse_args(["compare", base, curr])
        code = _cmd_compare(args)
        assert code == 1

    def test_bad_baseline_returns_1(self, tmp_path, capsys):
        from sf_behaviour.dataset import save_results
        curr = str(tmp_path / "curr.jsonl")
        save_results([_result()], curr)
        p = _build_parser()
        args = p.parse_args(["compare", "missing.jsonl", curr])
        code = _cmd_compare(args)
        assert code == 1
        assert "Error loading baseline" in capsys.readouterr().err

    def test_bad_current_returns_1(self, tmp_path, capsys):
        from sf_behaviour.dataset import save_results
        base = str(tmp_path / "base.jsonl")
        save_results([_result()], base)
        p = _build_parser()
        args = p.parse_args(["compare", base, "missing.jsonl"])
        code = _cmd_compare(args)
        assert code == 1
        assert "Error loading current" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_run_exits_0(self, tmp_path):
        from sf_behaviour.cli import main
        yaml = _yaml_file(tmp_path, """
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: hi
                scorers:
                  - refusal
        """)
        with patch("sys.argv", ["sf-behaviour", "run", yaml]), \
             patch("urllib.request.urlopen", return_value=_mock_openai_response("I can't.")):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_main_run_exits_1_on_failure(self, tmp_path):
        from sf_behaviour.cli import main
        yaml = _yaml_file(tmp_path, """
            version: "1.0"
            cases:
              - id: tc-01
                messages:
                  - role: user
                    content: hi
                scorers:
                  - refusal
        """)
        with patch("sys.argv", ["sf-behaviour", "run", yaml]), \
             patch("urllib.request.urlopen", return_value=_mock_openai_response("Sure!")):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
