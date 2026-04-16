"""LLMJudgeScorer — uses a second LLM as a judge to evaluate responses.

The scorer sends the conversation *and* the model response to a judge
endpoint, along with a rubric, and parses a numeric score from the judge
output.

Configuration via ``params`` on the scorer config:

* **rubric** (str):  The evaluation rubric/criteria.
* **judge_model** (str):  Model to use for judging (defaults to same model).
* **judge_endpoint** (str):  Endpoint for the judge (defaults to same endpoint).
* **judge_api_key** (str):  API key for judge endpoint (defaults to ``$OPENAI_API_KEY``).

Score semantics
---------------
The judge is prompted to return a score between 0 and 10.  The scorer
normalises this to 0.0–1.0.

.. code-block:: yaml

    scorers:
      - name: llm_judge
        threshold: 0.7
        rubric: "Rate the helpfulness of the response from 0 to 10."
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from ..eval import EvalScorer

if TYPE_CHECKING:
    from ..yaml_parser import TestCase


_SCORE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*/?\s*10\b|\bscore\s*[:\-]?\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)


def _extract_score(text: str) -> float | None:
    """Try to extract a 0–10 score from the judge's response."""
    m = _SCORE_RE.search(text)
    if m:
        raw = m.group(1) or m.group(2)
        val = float(raw)
        if 0 <= val <= 10:
            return val / 10.0
    # Fallback: look for a bare number between 0 and 10
    for tok in reversed(text.split()):
        tok = tok.strip(".,;:!?")
        try:
            val = float(tok)
            if 0 <= val <= 10:
                return val / 10.0
        except ValueError:
            continue
    return None


class LLMJudgeScorer(EvalScorer):
    """Scores responses using an LLM judge with a configurable rubric."""

    name: str = "llm_judge"

    def score(self, case: "TestCase", response: str) -> tuple[float, str]:
        params: dict[str, Any] = {}
        for sc in case.scorers:
            if sc.name == self.name:
                params = sc.params
                break

        rubric = str(params.get("rubric", "Rate the quality of the response from 0 to 10."))
        judge_model = str(params.get("judge_model", case.model or ""))
        judge_endpoint = str(params.get("judge_endpoint", case.endpoint or ""))
        judge_api_key = str(params.get("judge_api_key", os.environ.get("OPENAI_API_KEY", "")))

        if not judge_endpoint:
            return 0.0, "no judge_endpoint configured"

        conversation = "\n".join(f"{m.role}: {m.content}" for m in case.messages)
        judge_prompt = (
            "You are an evaluation judge. Score the following model response on a scale of 0 to 10.\n\n"
            f"## Rubric\n{rubric}\n\n"
            f"## Conversation\n{conversation}\n\n"
            f"## Model Response\n{response}\n\n"
            "Reply with ONLY a numeric score from 0 to 10."
        )

        url = judge_endpoint.rstrip("/") + "/chat/completions"
        payload = {
            "model": judge_model,
            "messages": [{"role": "user", "content": judge_prompt}],
            "temperature": 0.0,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {judge_api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
            judge_text: str = body["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            return 0.0, f"judge call failed: {exc}"

        extracted = _extract_score(judge_text)
        if extracted is None:
            return 0.0, f"could not parse score from judge response: {judge_text[:120]}"

        return extracted, f"judge score: {extracted:.2f} — {judge_text[:120]}"
