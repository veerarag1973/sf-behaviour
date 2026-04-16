"""FaithfulnessScorer — measures whether the response is faithful to a context.

Algorithm
---------
Tokenise both ``context`` and ``response`` into lowercase alphabetic words,
remove a compact set of English stopwords, then compute the fraction of
non-trivial *context* terms that appear in the response:

    faithfulness = |response_terms ∩ context_terms| / |context_terms|

This is a recall-oriented word-overlap metric — it penalises responses that
omit key facts from the context, but does not penalise the model for adding
information that was not in the context.  It is fast, zero-dependency, and
works well as a CI gate for hallucination regression.

Score semantics
---------------
1.0   Every non-trivial context term is present in the response.
0.0   No non-trivial context terms appear in the response.

A ``context`` field is required in the test-case.  When ``context`` is absent
the scorer returns 1.0 with a note.

.. code-block:: yaml

    cases:
      - id: tc-faithfulness
        messages:
          - role: user
            content: "Summarise: The product costs $50 and ships in 3 days."
        context: "The product costs $50 and ships in 3 days."
        scorers:
          - name: faithfulness
            threshold: 0.6
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..eval import EvalScorer

if TYPE_CHECKING:
    from ..yaml_parser import TestCase


_STOPWORDS: frozenset[str] = frozenset(
    """a an the is are was were be been being have has had do does did
    will would could should may might shall can of to in on at for by
    with as from that this these those it its i we you he she they them
    their our your my his her our its and or but not no nor so yet both
    either neither just also only even than then when where how what who
    whom which while if though although because since after before until
    about above below between through into out over under again further
    once here there all each few more most other some such up down""".split()
)

_TOKEN_RE = re.compile(r"[a-zA-Z]+")


def _tokenize(text: str) -> set[str]:
    tokens = {t.lower() for t in _TOKEN_RE.findall(text)}
    return tokens - _STOPWORDS


class FaithfulnessScorer(EvalScorer):
    """Scores response faithfulness against a grounding context using word overlap."""

    name: str = "faithfulness"

    def score(self, case: "TestCase", response: str) -> tuple[float, str]:
        if not case.context:
            return 1.0, "no context provided — faithfulness check skipped"

        context_terms = _tokenize(case.context)
        if not context_terms:
            return 1.0, "context contains no scoreable terms after stopword removal"

        response_terms = _tokenize(response)
        matched = context_terms & response_terms
        score = len(matched) / len(context_terms)

        missing = sorted(context_terms - response_terms)
        if missing:
            reason = (
                f"faithfulness {score:.2f} — "
                f"{len(matched)}/{len(context_terms)} context terms present; "
                f"missing: {', '.join(missing[:10])}"
                + (" …" if len(missing) > 10 else "")
            )
        else:
            reason = (
                f"faithfulness 1.00 — all {len(context_terms)} context terms present"
            )

        return round(score, 4), reason
