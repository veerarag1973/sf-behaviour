"""Tests for report module — build_report, render_markdown, render_html."""

from __future__ import annotations

from sf_behaviour.eval import EvalResult
from sf_behaviour.report import build_report, render_html, render_markdown


def _make_result(
    case_id: str = "tc-01",
    scorer_name: str = "refusal",
    score: float = 1.0,
    threshold: float = 0.5,
    passed: bool = True,
    latency_ms: float = 100.0,
    tags: list[str] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        case_name=case_id,
        scorer_name=scorer_name,
        score=score,
        threshold=threshold,
        passed=passed,
        reason="ok",
        response_text="resp",
        latency_ms=latency_ms,
        timestamp="2024-01-01T00:00:00Z",
        model="gpt-4o",
        endpoint="https://api.openai.com/v1",
        tags=tags or [],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


class TestBuildReport:
    def test_empty_results(self):
        report = build_report([])
        assert report.total_cases == 0
        assert report.pass_rate == 0.0

    def test_basic_stats(self):
        results = [
            _make_result("tc-01", score=1.0, passed=True, latency_ms=100),
            _make_result("tc-02", score=0.3, passed=False, latency_ms=200),
        ]
        report = build_report(results)
        assert report.total_cases == 2
        assert report.total_passed == 1
        assert report.total_failed == 1
        assert report.pass_rate == 0.5
        assert report.mean_latency_ms == 150.0

    def test_token_tracking(self):
        results = [
            _make_result(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            _make_result(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        ]
        report = build_report(results)
        assert report.total_prompt_tokens == 30
        assert report.total_completion_tokens == 15
        assert report.total_tokens == 45

    def test_scorer_summaries(self):
        results = [
            _make_result(scorer_name="refusal", score=1.0, passed=True),
            _make_result(scorer_name="refusal", score=0.0, passed=False),
            _make_result(scorer_name="pii_leakage", score=1.0, passed=True),
        ]
        report = build_report(results)
        assert len(report.scorer_summaries) == 2
        refusal = [s for s in report.scorer_summaries if s.scorer_name == "refusal"][0]
        assert refusal.count == 2
        assert refusal.pass_rate == 0.5

    def test_tag_pass_rates(self):
        results = [
            _make_result(tags=["safety"], passed=True),
            _make_result(tags=["safety"], passed=False),
            _make_result(tags=["privacy"], passed=True),
        ]
        report = build_report(results)
        assert report.tag_pass_rates["safety"] == 0.5
        assert report.tag_pass_rates["privacy"] == 1.0

    def test_latency_percentiles(self):
        results = [_make_result(latency_ms=float(i)) for i in range(1, 101)]
        report = build_report(results)
        assert 50.0 <= report.p50_latency_ms <= 51.0  # median of 1-100
        assert report.p95_latency_ms >= 95.0


class TestRenderMarkdown:
    def test_contains_headers(self):
        results = [_make_result()]
        report = build_report(results)
        md = render_markdown(report)
        assert "# Evaluation Report" in md
        assert "## Summary" in md
        assert "PASS" in md

    def test_tokens_in_markdown(self):
        results = [_make_result(total_tokens=100, prompt_tokens=60, completion_tokens=40)]
        report = build_report(results)
        md = render_markdown(report)
        assert "100" in md

    def test_empty_report(self):
        md = render_markdown(build_report([]))
        assert "# Evaluation Report" in md


class TestRenderHTML:
    def test_valid_html(self):
        results = [_make_result()]
        report = build_report(results)
        html_str = render_html(report)
        assert "<!DOCTYPE html>" in html_str
        assert "sf-behaviour Evaluation Report" in html_str
        assert "PASS" in html_str

    def test_html_escaping(self):
        result = _make_result(scorer_name="<script>alert('xss')</script>")
        report = build_report([result])
        html_str = render_html(report)
        assert "<script>" not in html_str
        assert "&lt;script&gt;" in html_str
