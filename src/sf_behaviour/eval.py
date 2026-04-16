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

import json
import os
import sys
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if sys.version_info >= (3, 10):
    from importlib.metadata import entry_points
else:
    from importlib.metadata import entry_points  # type: ignore[attr-defined]

if TYPE_CHECKING:
    from .yaml_parser import TestCase, TestSuite


# ---------------------------------------------------------------------------
# EvalScorer — abstract base
# ---------------------------------------------------------------------------

class EvalScorer(ABC):
    """Abstract base class for all behaviour scorers.

    Subclasses must:
    - set a unique class-level ``name`` string
    - implement ``score(case, response) -> (float, str)``

    The returned float must be in the range [0.0, 1.0].  The string is a
    human-readable reason that is stored in :class:`EvalResult`.
    """

    name: str = "base"

    @abstractmethod
    def score(self, case: "TestCase", response: str) -> tuple[float, str]:
        """Score the model response for the given test case.

        Parameters
        ----------
        case:
            The :class:`~sf_behaviour.yaml_parser.TestCase` being evaluated.
        response:
            The raw text returned by the model.

        Returns
        -------
        tuple[float, str]
            ``(score, reason)`` where *score* is in [0.0, 1.0] and *reason* is
            a short explanation suitable for CI log output.
        """


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
            eps = entry_points()
            if isinstance(eps, dict):
                scorer_eps = eps.get("sf_behaviour.scorers", [])
            else:
                scorer_eps = eps.select(group="sf_behaviour.scorers")  # Python 3.12+
            for ep in scorer_eps:
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
        url = endpoint.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {"model": model, "messages": messages}
        data = json.dumps(payload).encode("utf-8")
        empty_usage: dict[str, int] = {}

        last_error = ""
        for attempt in range(1 + self._max_retries):
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )

            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                latency_ms = (time.perf_counter() - t0) * 1000.0
            except urllib.error.HTTPError as exc:
                latency_ms = (time.perf_counter() - t0) * 1000.0
                try:
                    detail = exc.read(8192).decode("utf-8")
                except Exception:
                    detail = str(exc)
                last_error = f"HTTP {exc.code}: {detail[:200]}"
                # Retry on 429 or 5xx
                if exc.code in (429, 500, 502, 503, 504) and attempt < self._max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                return "", latency_ms, last_error, empty_usage
            except (OSError, urllib.error.URLError) as exc:  # transient network errors
                latency_ms = (time.perf_counter() - t0) * 1000.0
                last_error = str(exc)
                if attempt < self._max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                return "", latency_ms, last_error, empty_usage

            usage = body.get("usage") or {}

            try:
                text: str = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                return "", latency_ms, f"unexpected response shape: {exc}", empty_usage

            return text, latency_ms, None, usage

        # Should not reach here, but just in case
        return "", 0.0, last_error, empty_usage  # pragma: no cover
