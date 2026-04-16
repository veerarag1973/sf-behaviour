"""sf_behaviour — Behaviour test runner for OpenAI-compatible endpoints."""

from .eval import EvalResult, EvalRunner, EvalScorer, RegressionDetector, RegressionReport
from .yaml_parser import TestCase, TestSuite, ScorerConfig, Message, parse_yaml, parse_csv, parse_dataset
from .dataset import save_results, load_results
from .report import ScorerSummary, SuiteReport, build_report, render_html, render_markdown

__version__ = "1.0.1"
__all__ = [
    "EvalResult",
    "EvalRunner",
    "EvalScorer",
    "RegressionDetector",
    "RegressionReport",
    "TestCase",
    "TestSuite",
    "ScorerConfig",
    "Message",
    "parse_yaml",
    "parse_csv",
    "parse_dataset",
    "save_results",
    "load_results",
    "ScorerSummary",
    "SuiteReport",
    "build_report",
    "render_html",
    "render_markdown",
]
