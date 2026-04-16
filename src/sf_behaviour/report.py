"""Report generation — summary statistics, HTML and Markdown export."""

from __future__ import annotations

import html
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spanforge.stats import percentile as _sf_percentile

if TYPE_CHECKING:
    from .eval import EvalResult


@dataclass
class ScorerSummary:
    """Aggregate statistics for a single scorer across all cases."""

    scorer_name: str
    count: int = 0
    passed: int = 0
    mean_score: float = 0.0
    min_score: float = 0.0
    max_score: float = 0.0
    pass_rate: float = 0.0


@dataclass
class SuiteReport:
    """Full evaluation report with per-scorer and per-tag summaries."""

    total_cases: int = 0
    total_passed: int = 0
    total_failed: int = 0
    pass_rate: float = 0.0
    mean_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    scorer_summaries: list[ScorerSummary] = field(default_factory=list)
    tag_pass_rates: dict[str, float] = field(default_factory=dict)
    results: list["EvalResult"] = field(default_factory=list)


def build_report(results: list["EvalResult"]) -> SuiteReport:
    """Build a :class:`SuiteReport` from a list of :class:`EvalResult`."""
    if not results:
        return SuiteReport()

    report = SuiteReport(
        total_cases=len(results),
        total_passed=sum(1 for r in results if r.passed),
        total_failed=sum(1 for r in results if not r.passed),
        results=results,
    )
    report.pass_rate = report.total_passed / report.total_cases if report.total_cases else 0.0

    latencies = [r.latency_ms for r in results]
    report.mean_latency_ms = statistics.mean(latencies)
    report.p50_latency_ms = _sf_percentile(latencies, 50)
    report.p95_latency_ms = _sf_percentile(latencies, 95)
    report.p99_latency_ms = _sf_percentile(latencies, 99)

    report.total_prompt_tokens = sum(r.prompt_tokens for r in results)
    report.total_completion_tokens = sum(r.completion_tokens for r in results)
    report.total_tokens = sum(r.total_tokens for r in results)

    # Per-scorer
    scorer_groups: dict[str, list["EvalResult"]] = {}
    for r in results:
        scorer_groups.setdefault(r.scorer_name, []).append(r)
    for sname, sresults in sorted(scorer_groups.items()):
        scores = [r.score for r in sresults]
        summary = ScorerSummary(
            scorer_name=sname,
            count=len(sresults),
            passed=sum(1 for r in sresults if r.passed),
            mean_score=statistics.mean(scores),
            min_score=min(scores),
            max_score=max(scores),
            pass_rate=sum(1 for r in sresults if r.passed) / len(sresults),
        )
        report.scorer_summaries.append(summary)

    # Per-tag
    tag_groups: dict[str, list["EvalResult"]] = {}
    for r in results:
        for tag in r.tags:
            tag_groups.setdefault(tag, []).append(r)
    for tag, tresults in sorted(tag_groups.items()):
        report.tag_pass_rates[tag] = sum(1 for r in tresults if r.passed) / len(tresults)

    return report


def render_markdown(report: SuiteReport) -> str:
    """Render a :class:`SuiteReport` as a Markdown string."""
    lines: list[str] = []
    lines.append("# Evaluation Report\n")

    lines.append("## Summary\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total cases | {report.total_cases} |")
    lines.append(f"| Passed | {report.total_passed} |")
    lines.append(f"| Failed | {report.total_failed} |")
    lines.append(f"| Pass rate | {report.pass_rate:.1%} |")
    lines.append(f"| Mean latency | {report.mean_latency_ms:.0f} ms |")
    lines.append(f"| p50 latency | {report.p50_latency_ms:.0f} ms |")
    lines.append(f"| p95 latency | {report.p95_latency_ms:.0f} ms |")
    lines.append(f"| p99 latency | {report.p99_latency_ms:.0f} ms |")
    if report.total_tokens:
        lines.append(f"| Total tokens | {report.total_tokens:,} |")
        lines.append(f"| Prompt tokens | {report.total_prompt_tokens:,} |")
        lines.append(f"| Completion tokens | {report.total_completion_tokens:,} |")
    lines.append("")

    if report.scorer_summaries:
        lines.append("## Scorer Breakdown\n")
        lines.append("| Scorer | Count | Pass rate | Mean score | Min | Max |")
        lines.append("|--------|-------|-----------|------------|-----|-----|")
        for s in report.scorer_summaries:
            lines.append(
                f"| {s.scorer_name} | {s.count} | {s.pass_rate:.1%} | "
                f"{s.mean_score:.3f} | {s.min_score:.3f} | {s.max_score:.3f} |"
            )
        lines.append("")

    if report.tag_pass_rates:
        lines.append("## Pass Rate by Tag\n")
        lines.append("| Tag | Pass rate |")
        lines.append("|-----|-----------|")
        for tag, rate in report.tag_pass_rates.items():
            lines.append(f"| {tag} | {rate:.1%} |")
        lines.append("")

    if report.results:
        lines.append("## Detailed Results\n")
        lines.append("| Case | Scorer | Score | Threshold | Passed | Latency (ms) |")
        lines.append("|------|--------|-------|-----------|--------|-------------|")
        for r in report.results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(
                f"| {r.case_name} | {r.scorer_name} | {r.score:.3f} | "
                f"{r.threshold:.2f} | {status} | {r.latency_ms:.0f} |"
            )
        lines.append("")

    return "\n".join(lines)


def render_html(report: SuiteReport) -> str:
    """Render a :class:`SuiteReport` as a standalone HTML page."""
    esc = html.escape

    rows_summary = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>"
        for k, v in [
            ("Total cases", str(report.total_cases)),
            ("Passed", str(report.total_passed)),
            ("Failed", str(report.total_failed)),
            ("Pass rate", f"{report.pass_rate:.1%}"),
            ("Mean latency", f"{report.mean_latency_ms:.0f} ms"),
            ("p50 latency", f"{report.p50_latency_ms:.0f} ms"),
            ("p95 latency", f"{report.p95_latency_ms:.0f} ms"),
            ("p99 latency", f"{report.p99_latency_ms:.0f} ms"),
        ]
    )
    if report.total_tokens:
        rows_summary += "".join(
            f"<tr><td>{k}</td><td>{v:,}</td></tr>"
            for k, v in [
                ("Total tokens", report.total_tokens),
                ("Prompt tokens", report.total_prompt_tokens),
                ("Completion tokens", report.total_completion_tokens),
            ]
        )

    rows_scorers = ""
    for s in report.scorer_summaries:
        rows_scorers += (
            f"<tr><td>{esc(s.scorer_name)}</td><td>{s.count}</td>"
            f"<td>{s.pass_rate:.1%}</td><td>{s.mean_score:.3f}</td>"
            f"<td>{s.min_score:.3f}</td><td>{s.max_score:.3f}</td></tr>\n"
        )

    rows_tags = ""
    for tag, rate in report.tag_pass_rates.items():
        rows_tags += f"<tr><td>{esc(tag)}</td><td>{rate:.1%}</td></tr>\n"

    rows_detail = ""
    for r in report.results:
        cls = "pass" if r.passed else "fail"
        rows_detail += (
            f'<tr class="{cls}"><td>{esc(r.case_name)}</td><td>{esc(r.scorer_name)}</td>'
            f"<td>{r.score:.3f}</td><td>{r.threshold:.2f}</td>"
            f'<td>{"PASS" if r.passed else "FAIL"}</td><td>{r.latency_ms:.0f}</td></tr>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>sf-behaviour Evaluation Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 2rem; color: #333; }}
  h1 {{ color: #1a1a2e; }}
  h2 {{ color: #16213e; margin-top: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f4f4f4; font-weight: 600; }}
  tr:nth-child(even) {{ background: #fafafa; }}
  tr.pass td:nth-child(5) {{ color: #27ae60; font-weight: bold; }}
  tr.fail td:nth-child(5) {{ color: #e74c3c; font-weight: bold; }}
</style>
</head>
<body>
<h1>sf-behaviour Evaluation Report</h1>
<h2>Summary</h2>
<table><tr><th>Metric</th><th>Value</th></tr>{rows_summary}</table>
<h2>Scorer Breakdown</h2>
<table><tr><th>Scorer</th><th>Count</th><th>Pass rate</th><th>Mean</th><th>Min</th><th>Max</th></tr>
{rows_scorers}</table>
{"<h2>Pass Rate by Tag</h2><table><tr><th>Tag</th><th>Pass rate</th></tr>" + rows_tags + "</table>" if rows_tags else ""}
<h2>Detailed Results</h2>
<table><tr><th>Case</th><th>Scorer</th><th>Score</th><th>Threshold</th><th>Passed</th><th>Latency (ms)</th></tr>
{rows_detail}</table>
</body>
</html>"""
