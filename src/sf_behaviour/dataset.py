"""Dataset persistence — save/load EvalResult objects as JSONL.

Uses spanforge's ``SyncJSONLExporter`` and ``EventStream.from_file()`` to
store results as ``llm.eval.scenario.completed`` events, keeping the data
inside the spanforge event envelope for auditability.

Public API
----------
save_results(results, path)
    Append (or create) a JSONL file with one spanforge event per result.
load_results(path)
    Read a JSONL file and return the list of EvalResult objects it contains.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from .eval import EvalResult

# Spanforge event type used for every eval record.
_EVENT_TYPE = "llm.eval.scenario.completed"
_SOURCE = "sf-behaviour@1.0.0"


# ---------------------------------------------------------------------------
# Spanforge integration helpers
# ---------------------------------------------------------------------------

def _make_event(result: EvalResult) -> Any:
    """Wrap *result* in a spanforge Event."""
    try:
        from spanforge.event import Event

        return Event(
            event_type=_EVENT_TYPE,
            source=_SOURCE,
            payload=_result_to_dict(result),
        )
    except Exception:  # noqa: BLE001 — spanforge unavailable, fall back to plain dict
        return None


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

    try:
        from spanforge.exporters.jsonl import SyncJSONLExporter

        exporter = SyncJSONLExporter(path)
        fallback_results: list[EvalResult] = []
        try:
            for result in results:
                event = _make_event(result)
                if event is not None:
                    exporter.export(event)
                else:
                    fallback_results.append(result)
        finally:
            exporter.close()

        # Write any results whose events couldn't be created *after* exporter
        # has released the file handle.
        if fallback_results:
            with open(path, "a", encoding="utf-8") as fh:
                for result in fallback_results:
                    fh.write(
                        json.dumps(
                            {"event_type": _EVENT_TYPE, "payload": _result_to_dict(result)}
                        )
                        + "\n"
                    )

    except ImportError:  # pragma: no cover — spanforge not installed
        with open(path, "w", encoding="utf-8") as fh:
            for result in results:
                fh.write(
                    json.dumps(
                        {"event_type": _EVENT_TYPE, "payload": _result_to_dict(result)}
                    )
                    + "\n"
                )


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
    results: list[EvalResult] = []

    try:
        from spanforge.stream import EventStream

        try:
            for event in EventStream.from_file(path):
                if getattr(event, "event_type", None) == _EVENT_TYPE:
                    try:
                        results.append(_dict_to_result(dict(event.payload)))
                    except Exception:  # noqa: BLE001
                        pass  # skip malformed payload
            return results
        except Exception:  # noqa: BLE001 — spanforge failed to parse file; fall through
            results.clear()

    except ImportError:
        pass  # spanforge not installed — fall back to plain JSON

    # Plain-JSON fallback
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("event_type") == _EVENT_TYPE:
                    results.append(_dict_to_result(obj["payload"]))
            except Exception:  # noqa: BLE001
                pass  # skip malformed lines

    return results
