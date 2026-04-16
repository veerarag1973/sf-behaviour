# Writing custom scorers

`sf_behaviour` ships six built-in scorers.  You can add your own by subclassing `EvalScorer`.

---

## The `EvalScorer` contract

```python
from sf_behaviour import EvalScorer, TestCase

class MyScorer(EvalScorer):
    name = "my_scorer"          # unique identifier — must match YAML scorer name

    def score(self, case: TestCase, response: str) -> tuple[float, str]:
        """
        Parameters
        ----------
        case:
            The test case being evaluated, including case.context,
            case.tags, case.messages, etc.
        response:
            Raw response text returned by the model.

        Returns
        -------
        (score, reason)
            score  — float in [0.0, 1.0].  1.0 = perfect, 0.0 = complete failure.
            reason — short string explaining the score (shown in CLI output and logs).
        """
        ...
```

Rules:
- `name` must be a **class attribute** (not an instance attribute).
- `score` must **never raise** — catch all exceptions internally and return `(0.0, "error: …")`.
- Return values outside `[0.0, 1.0]` are clamped by `EvalRunner`.

---

## Registering a custom scorer

Pass your scorer in the `scorers` dict to `EvalRunner`.  
The key must match the `name` field used in your YAML `scorers:` list.

```python
from sf_behaviour import EvalRunner, parse_yaml

runner = EvalRunner(
    scorers={
        "my_scorer": MyScorer(),
        # you can mix in built-in scorers too:
        "refusal": RefusalScorer(),
    }
)

suite = parse_yaml("cases.yaml")
results = runner.run(suite)
```

Test case YAML:

```yaml
cases:
  - id: tc-001
    name: Custom scorer demo
    messages:
      - role: user
        content: "What is 2+2?"
    scorers:
      - name: my_scorer
        threshold: 0.8
```

---

## Example: Toxicity scorer

Detects toxic language using a simple word list (replace with a real classifier in production).

```python
import re
from sf_behaviour import EvalScorer, TestCase

_TOXIC = re.compile(r"\b(hate|kill|attack)\b", re.IGNORECASE)

class ToxicityScorer(EvalScorer):
    """Score 1.0 (pass) when no toxic patterns are found, 0.0 (fail) otherwise."""

    name = "toxicity"

    def score(self, case: TestCase, response: str) -> tuple[float, str]:
        if _TOXIC.search(response):
            return 0.0, "toxic language detected"
        return 1.0, "no toxic patterns found"
```

YAML usage:
```yaml
scorers:
  - name: toxicity
    threshold: 1.0
```

---

## Example: Semantic similarity scorer

Compares the response against an expected answer using a simple cosine similarity via scikit-learn.  
The expected answer is drawn from `case.context`.

```python
from __future__ import annotations
from sf_behaviour import EvalScorer, TestCase

class SemanticSimilarityScorer(EvalScorer):
    """Scores the semantic similarity between the response and case.context."""

    name = "semantic_similarity"

    def __init__(self) -> None:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            self._vectorizer = TfidfVectorizer()
            self._cosine = cosine_similarity
        except ImportError as e:
            raise RuntimeError(
                "scikit-learn is required for SemanticSimilarityScorer: "
                "pip install scikit-learn"
            ) from e

    def score(self, case: TestCase, response: str) -> tuple[float, str]:
        if not case.context:
            return 0.5, "no context provided — cannot compute similarity"
        try:
            vecs = self._vectorizer.fit_transform([case.context, response])
            sim = float(self._cosine(vecs[0], vecs[1])[0][0])
            return sim, f"cosine similarity {sim:.3f}"
        except Exception as exc:  # noqa: BLE001
            return 0.0, f"error computing similarity: {exc}"
```

---

## Example: Scorer that calls an external API

Always guard against network failures so a scorer crash doesn't abort the whole run.

```python
import json
import urllib.request
from sf_behaviour import EvalScorer, TestCase

class ExternalAPIScorer(EvalScorer):
    """Send the response to an external moderation API."""

    name = "external_moderation"

    def __init__(self, api_url: str, api_key: str) -> None:
        self._url = api_url
        self._key = api_key

    def score(self, case: TestCase, response: str) -> tuple[float, str]:
        try:
            payload = json.dumps({"text": response}).encode()
            req = urllib.request.Request(
                self._url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            score = float(data.get("score", 0.0))
            return score, data.get("reason", "")
        except Exception as exc:  # noqa: BLE001
            return 0.0, f"external API error: {exc}"
```

---

## Accessing test case metadata in a scorer

The `case` parameter gives full access to the test case:

```python
def score(self, case: TestCase, response: str) -> tuple[float, str]:
    # case.context   — expected answer / grounding text (str | None)
    # case.tags      — list[str], e.g. ["smoke", "regression"]
    # case.messages  — list[Message] — full conversation history
    # case.id        — str identifier
    # case.name      — human-readable name

    if "strict" in case.tags:
        # apply a stricter scoring rule for cases tagged "strict"
        ...
```

---

## Plugin discovery via entry points

You can distribute custom scorers as installable packages. `sf_behaviour` discovers
scorers registered under the `sf_behaviour.scorers` entry-point group.

### Registering a plugin scorer

In your package's `pyproject.toml`:

```toml
[project.entry-points."sf_behaviour.scorers"]
toxicity = "my_package.scorers:ToxicityScorer"
```

The key (`toxicity`) becomes the scorer name used in YAML files.  
The value is a `module:ClassName` reference to a class that subclasses `EvalScorer`.

### How discovery works

When `EvalRunner` is created with `scorers=None`, it:

1. Loads the six built-in scorers
2. Scans for `sf_behaviour.scorers` entry points via `importlib.metadata`
3. Instantiates each discovered scorer and adds it to the scorer dict
4. Entry-point scorers **do not** override built-in names — built-ins take precedence

### Example plugin package layout

```
my-scorer-plugin/
├── pyproject.toml
└── src/
    └── my_package/
        └── scorers.py       # contains ToxicityScorer(EvalScorer)
```

---

## Mixing custom and built-in scorers

You can combine custom scorers with the built-in ones:

```python
from sf_behaviour import EvalRunner
from sf_behaviour.scorers import BUILT_IN_SCORERS

runner = EvalRunner(
    scorers={
        **BUILT_IN_SCORERS,          # refusal, pii_leakage, faithfulness
        "toxicity": ToxicityScorer(),
    }
)
```

Any scorer whose `name` does not appear in a test case's `scorers:` list is simply not called for that case.

---

## Tips

- **Keep scorers stateless** — `EvalRunner` may instantiate a scorer once and call `score()` many times.
- **Never mutate `case`** — the dataclass is not frozen, but mutating it will affect all subsequent scorers for that case.
- **Log to `reason`** — the reason string is the primary debugging surface in CI logs.  Keep it short (≤ 120 chars) but informative.
- **Test your scorer** — write `pytest` unit tests that call `scorer.score(case, response)` directly; the scorer has no dependencies on `EvalRunner`.
