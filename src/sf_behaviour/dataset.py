"""Dataset persistence — save/load EvalResult objects as JSONL.

Uses spanforge's ``spanforge.io`` module to store results as
``llm.eval.scenario.completed`` events, keeping the data inside the
spanforge event envelope for auditability.

Public API
----------
save_results(results, path)
    Append (or create) a JSONL file with one spanforge event per result.
load_results(path)
    Read a JSONL file and return the list of EvalResult objects it contains.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from spanforge.io import read_jsonl, write_jsonl

from .eval import EvalResult

# Spanforge event type used for every eval record.
_EVENT_TYPE = "llm.eval.scenario.completed"
_SOURCE = "sf-behaviour@1.0.1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result_to_dict(result: EvalResult) -> dict[str, Any]:
    return dataclasses.asdict(result)


def _dict_to_result(payload: dict[str, Any]) -> EvalResult:
    # tags may be stored as a list or missing
    payload.setdefault("tags", [])
    payload.setdefault("error", None)
    return EvalResult(**payload)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_results(results: list[EvalResult], path: str) -> None:
    """Persist *results* to *path* as a JSONL file.

    Each line is a spanforge ``llm.eval.scenario.completed`` JSON event.
    The file is **overwritten** if it already exists.

    Parameters
    ----------
    results:
        List of :class:`~sf_behaviour.eval.EvalResult` objects to persist.
    path:
        Destination file path.  Parent directories are created automatically.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    records = [_result_to_dict(r) for r in results]
    write_jsonl(records, path)


def load_results(path: str) -> list[EvalResult]:
    """Load :class:`~sf_behaviour.eval.EvalResult` objects from a JSONL file.

    Only lines with ``event_type == "llm.eval.scenario.completed"`` are
    returned; other event types are silently ignored.

    Parameters
    ----------
    path:
        JSONL file previously written by :func:`save_results`.

    Returns
    -------
    list[EvalResult]
    """
    payloads = read_jsonl(path)
    results: list[EvalResult] = []
    for payload in payloads:
        try:
            results.append(_dict_to_result(payload))
        except Exception:  # noqa: BLE001
            pass  # skip malformed payloads
    return results
