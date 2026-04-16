"""Core evaluation classes for sf-behaviour.

Classes
-------
EvalScorer
    Abstract base for all scorers.  Third-party scorers subclass this.
EvalResult
    Immutable record of one scorer's output for one test case.
RegressionReport
    Summary produced by RegressionDetector.compare().
RegressionDetector
    Compares a current run against a baseline; fails CI on regression.
EvalRunner
    Orchestrates HTTP calls to an OpenAI-compatible endpoint and applies
    scorers to produce a list of EvalResult objects.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from spanforge.eval import BehaviourScorer as EvalScorer
from spanforge.http import chat_completion
from spanforge.plugins import discover as _discover_entry_points

if TYPE_CHECKING:
    from .yaml_parser import TestCase, TestSuite


# ---------------------------------------------------------------------------
# EvalResult — immutable record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvalResult:
    """The result of applying one scorer to one test case."""

    case_id: str
    case_name: str
    scorer_name: str
    score: float            # 0.0–1.0
    threshold: float        # from ScorerConfig
    passed: bool            # score >= threshold
    reason: str
    response_text: str
    latency_ms: float
    timestamp: str          # ISO-8601 UTC
    model: str
    endpoint: str
    tags: list[str] = field(default_factory=list)
    error: str | None = None   # set when the HTTP call itself failed
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# ---------------------------------------------------------------------------
# RegressionDetector
# ---------------------------------------------------------------------------

@dataclass
class RegressionReport:
    """Summary of regressions found between two evaluation runs."""

    regressions: list[EvalResult]
    """Cases that passed in the baseline but fail in the current run."""

    score_drops: list[tuple[EvalResult, EvalResult]]
    """(baseline, current) pairs where the score dropped by >= threshold."""

    @property
    def has_regression(self) -> bool:
        return bool(self.regressions or self.score_drops)

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        if self.regressions:
            lines.append(f"  {len(self.regressions)} new failure(s):")
            for r in self.regressions:
                lines.append(
                    f"    [{r.case_id}] {r.scorer_name}: "
                    f"score={r.score:.2f} threshold={r.threshold:.2f} — {r.reason}"
                )
        if self.score_drops:
            lines.append(f"  {len(self.score_drops)} score drop(s):")
            for base, curr in self.score_drops:
                lines.append(
                    f"    [{curr.case_id}] {curr.scorer_name}: "
                    f"{base.score:.2f} → {curr.score:.2f}"
                )
        return lines


class RegressionDetector:
    """Compares a current evaluation run against a saved baseline.

    A *regression* is one of:

    * A ``(case_id, scorer_name)`` pair that **passed** in the baseline but
      **fails** in the current run.
    * A ``(case_id, scorer_name)`` pair whose score dropped by at least
      *score_drop_threshold* (default ``0.1``).

    Parameters
    ----------
    score_drop_threshold:
        Minimum score decrease that constitutes a regression even when the
        current result still passes.  Default is ``0.1``.
    """

    def __init__(self, score_drop_threshold: float = 0.1) -> None:
        self.score_drop_threshold = score_drop_threshold

    def compare(
        self,
        baseline: list[EvalResult],
        current: list[EvalResult],
    ) -> RegressionReport:
        """Return a :class:`RegressionReport` describing regressions.

        Parameters
        ----------
        baseline:
            Results from a previous (known-good) run.
        current:
            Results from the run being checked.
        """
        baseline_map: dict[tuple[str, str], EvalResult] = {
            (r.case_id, r.scorer_name): r for r in baseline
        }
        current_map: dict[tuple[str, str], EvalResult] = {
            (r.case_id, r.scorer_name): r for r in current
        }

        regressions: list[EvalResult] = []
        score_drops: list[tuple[EvalResult, EvalResult]] = []

        for key, curr in current_map.items():
            base = baseline_map.get(key)
            if base is None:
                continue  # new case — not a regression

            if base.passed and not curr.passed:
                regressions.append(curr)
            elif (base.score - curr.score) >= self.score_drop_threshold:
                score_drops.append((base, curr))

        return RegressionReport(regressions=regressions, score_drops=score_drops)


# ---------------------------------------------------------------------------
# EvalRunner
# ---------------------------------------------------------------------------

class EvalRunner:
    """Runs a :class:`~sf_behaviour.yaml_parser.TestSuite` against an endpoint.

    Parameters
    ----------
    scorers:
        Mapping of scorer name → :class:`EvalScorer` instance.  Defaults to
        all three built-in scorers when ``None``.
    api_key:
        Bearer token for the endpoint.  Falls back to ``$OPENAI_API_KEY`` when
        not supplied.
    endpoint_override:
        Override the endpoint for every case in the suite.
    model_override:
        Override the model for every case in the suite.
    timeout_seconds:
        Per-request timeout.
    tags:
        When non-empty, only run cases whose tags intersect with this set.
    max_retries:
        Number of retries on transient HTTP errors (default 0).
    jobs:
        Number of parallel workers for case evaluation (default 1 = sequential).
    """

    def __init__(
        self,
        scorers: dict[str, EvalScorer] | None = None,
        api_key: str = "",
        endpoint_override: str = "",
        model_override: str = "",
        timeout_seconds: int = 30,
        tags: list[str] | None = None,
        max_retries: int = 0,
        jobs: int = 1,
    ) -> None:
        if scorers is None:
            from .scorers import BUILT_IN_SCORERS
            self._scorers: dict[str, EvalScorer] = dict(BUILT_IN_SCORERS)
        else:
            self._scorers = scorers

        # Plugin discovery via entry_points
        self._discover_plugins()

        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._endpoint_override = endpoint_override
        self._model_override = model_override
        self._timeout_seconds = timeout_seconds
        self._tags = set(tags) if tags else set()
        self._max_retries = max(0, max_retries)
        self._jobs = max(1, jobs)

    def _discover_plugins(self) -> None:
        """Auto-discover scorers registered via ``sf_behaviour.scorers`` entry points."""
        try:
            for ep in _discover_entry_points("sf_behaviour.scorers"):
                if ep.name not in self._scorers:
                    scorer = ep.load()
                    if isinstance(scorer, type) and issubclass(scorer, EvalScorer):
                        self._scorers[ep.name] = scorer()
                    elif isinstance(scorer, EvalScorer):
                        self._scorers[ep.name] = scorer
        except Exception:  # noqa: BLE001
            pass  # plugin discovery is best-effort

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self, suite: "TestSuite") -> list[EvalResult]:
        """Execute all cases in *suite* and return :class:`EvalResult` objects."""
        cases = [
            c for c in suite.cases
            if not c.skip and (not self._tags or self._tags & set(c.tags))
        ]

        if self._jobs > 1 and len(cases) > 1:
            return self._run_parallel(cases, suite)
        return self._run_sequential(cases, suite)

    def _run_parallel(
        self, cases: list["TestCase"], suite: "TestSuite"  # type: ignore[name-defined]
    ) -> list[EvalResult]:
        results: list[EvalResult] = []
        with ThreadPoolExecutor(max_workers=self._jobs) as pool:
            futures = {
                pool.submit(self._eval_case, case, suite): i
                for i, case in enumerate(cases)
            }
            # Collect in submission order for deterministic output
            ordered: dict[int, list[EvalResult]] = {}
            for future in as_completed(futures):
                idx = futures[future]
                ordered[idx] = future.result()
            for i in sorted(ordered):
                results.extend(ordered[i])
        return results

    def _run_sequential(
        self, cases: list["TestCase"], suite: "TestSuite"  # type: ignore[name-defined]
    ) -> list[EvalResult]:
        results: list[EvalResult] = []
        for case in cases:
            results.extend(self._eval_case(case, suite))
        return results

    def _eval_case(
        self, case: "TestCase", suite: "TestSuite"  # type: ignore[name-defined]
    ) -> list[EvalResult]:
        results: list[EvalResult] = []
        model = self._model_override or case.model or suite.default_model
        endpoint = self._endpoint_override or case.endpoint or suite.default_endpoint
        timeout = suite.default_timeout_seconds

        response_text, latency_ms, error, usage = self._call_endpoint(
            endpoint=endpoint,
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in case.messages],
            timeout=timeout,
        )

        ts = datetime.now(timezone.utc).isoformat()
        prompt_tok = usage.get("prompt_tokens", 0)
        completion_tok = usage.get("completion_tokens", 0)
        total_tok = usage.get("total_tokens", 0)

        for scorer_cfg in case.scorers:
            scorer = self._scorers.get(scorer_cfg.name)
            if scorer is None:
                results.append(
                    EvalResult(
                        case_id=case.id,
                        case_name=case.name,
                        scorer_name=scorer_cfg.name,
                        score=0.0,
                        threshold=scorer_cfg.threshold,
                        passed=False,
                        reason=f"unknown scorer '{scorer_cfg.name}'",
                        response_text=response_text,
                        latency_ms=latency_ms,
                        timestamp=ts,
                        model=model,
                        endpoint=endpoint,
                        tags=case.tags,
                        error=f"scorer '{scorer_cfg.name}' not registered",
                        prompt_tokens=prompt_tok,
                        completion_tokens=completion_tok,
                        total_tokens=total_tok,
                    )
                )
                continue

            if error:
                results.append(
                    EvalResult(
                        case_id=case.id,
                        case_name=case.name,
                        scorer_name=scorer_cfg.name,
                        score=0.0,
                        threshold=scorer_cfg.threshold,
                        passed=False,
                        reason="endpoint call failed",
                        response_text="",
                        latency_ms=latency_ms,
                        timestamp=ts,
                        model=model,
                        endpoint=endpoint,
                        tags=case.tags,
                        error=error,
                        prompt_tokens=prompt_tok,
                        completion_tokens=completion_tok,
                        total_tokens=total_tok,
                    )
                )
                continue

            try:
                score, reason = scorer.score(case, response_text)
                score = max(0.0, min(1.0, float(score)))
            except Exception as exc:  # noqa: BLE001
                score = 0.0
                reason = f"scorer raised exception: {exc}"

            results.append(
                EvalResult(
                    case_id=case.id,
                    case_name=case.name,
                    scorer_name=scorer_cfg.name,
                    score=score,
                    threshold=scorer_cfg.threshold,
                    passed=score >= scorer_cfg.threshold,
                    reason=reason,
                    response_text=response_text,
                    latency_ms=latency_ms,
                    timestamp=ts,
                    model=model,
                    endpoint=endpoint,
                    tags=case.tags,
                    prompt_tokens=prompt_tok,
                    completion_tokens=completion_tok,
                    total_tokens=total_tok,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_endpoint(
        self,
        endpoint: str,
        model: str,
        messages: list[dict[str, str]],
        timeout: int,
    ) -> tuple[str, float, str | None, dict[str, int]]:
        """Call the OpenAI-compatible /chat/completions endpoint.

        Returns
        -------
        tuple[str, float, str | None, dict[str, int]]
            (response_text, latency_ms, error_message_or_None, usage_dict)
        """
        resp = chat_completion(
            endpoint=endpoint,
            model=model,
            messages=messages,
            api_key=self._api_key,
            timeout=timeout,
            max_retries=self._max_retries,
        )
        usage = {
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "total_tokens": resp.total_tokens,
        }
        return resp.text, resp.latency_ms, resp.error, usage
