# Python API reference

This page documents every public class, function, and dataclass in `sf_behaviour`.

---

## Module: `sf_behaviour`

The top-level package re-exports all public symbols.

```python
from sf_behaviour import (
    # Parsing
    parse_yaml, Message, ScorerConfig, TestCase, TestSuite,
    # Core evaluation
    EvalResult, EvalRunner, EvalScorer, RegressionDetector, RegressionReport,
    # Dataset I/O
    save_results, load_results, parse_csv, parse_dataset,
    # Reports
    ScorerSummary, SuiteReport, build_report, render_html, render_markdown,
)
```

---

## Parsing — `sf_behaviour.yaml_parser`

### `parse_yaml(path)`

```python
def parse_yaml(path: str) -> TestSuite
```

Parse a YAML test-case file and return a `TestSuite`.

**Raises** `ValueError` if the file is missing required fields or has no cases.  
**Raises** `yaml.YAMLError` if the file is not valid YAML.

---

### `Message`

```python
@dataclass
class Message:
    role: str     # "system" | "user" | "assistant"
    content: str
```

A single chat message, mirrors the OpenAI messages format.

---

### `ScorerConfig`

```python
@dataclass
class ScorerConfig:
    name: str
    threshold: float = 0.5
    params: dict[str, Any] = field(default_factory=dict)
```

Configuration for one scorer on a test case.  
Extra YAML keys beyond `name` and `threshold` land in `params`.

---

### `TestCase`

```python
@dataclass
class TestCase:
    id: str
    name: str
    messages: list[Message]
    scorers: list[ScorerConfig]
    context: str | None = None
    tags: list[str] = field(default_factory=list)
    skip: bool = False
    model: str | None = None
    endpoint: str | None = None
```

One behaviour test case as parsed from YAML.  
When `skip` is `True`, the case is excluded from the run entirely.

---

### `TestSuite`

```python
@dataclass
class TestSuite:
    version: str
    cases: list[TestCase]
    default_model: str = "gpt-4o"
    default_endpoint: str = "https://api.openai.com/v1"
    default_timeout_seconds: int = 30
```

A collection of test cases with shared defaults.

---

## Core evaluation — `sf_behaviour.eval`

### `EvalScorer`

```python
class EvalScorer(ABC):
    name: str = "base"

    @abstractmethod
    def score(self, case: TestCase, response: str) -> tuple[float, str]:
        ...
```

Abstract base class for all scorers.  Subclass this to write a custom scorer.

| Member | Description |
|---|---|
| `name` | Class-level string identifier — must be unique across scorers used in one runner |
| `score(case, response)` | Return `(score, reason)` where `score ∈ [0.0, 1.0]` |

See [Writing custom scorers](custom-scorers.md).

---

### `EvalResult`

```python
@dataclass(frozen=True)
class EvalResult:
    case_id: str
    case_name: str
    scorer_name: str
    score: float           # 0.0–1.0
    threshold: float
    passed: bool           # score >= threshold
    reason: str
    response_text: str
    latency_ms: float
    timestamp: str         # ISO-8601 UTC, e.g. "2026-04-16T09:00:00+00:00"
    model: str
    endpoint: str
    tags: list[str]        # default []
    error: str | None      # set when HTTP call failed; default None
    prompt_tokens: int     # token count from API usage; default 0
    completion_tokens: int # token count from API usage; default 0
    total_tokens: int      # token count from API usage; default 0
```

Immutable record of one scorer's evaluation of one test case.  
Each `(case × scorer)` pair produces one `EvalResult`.

---

### `EvalRunner`

```python
class EvalRunner:
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
    ) -> None: ...

    def run(self, suite: TestSuite) -> list[EvalResult]: ...
```

Orchestrates HTTP calls and scorer evaluation.

#### Constructor parameters

| Parameter | Default | Description |
|---|---|---|
| `scorers` | `None` | Dict of `{name: scorer}`. When `None`, the six built-in scorers are used |
| `api_key` | `""` | Bearer token. Falls back to `OPENAI_API_KEY` env var |
| `endpoint_override` | `""` | Override endpoint for all cases |
| `model_override` | `""` | Override model for all cases |
| `timeout_seconds` | `30` | HTTP timeout per request |
| `tags` | `None` | When set, only cases with at least one matching tag are run |
| `max_retries` | `0` | Number of retries on transient HTTP errors (429, 5xx) with exponential backoff |
| `jobs` | `1` | Number of parallel workers. Values > 1 use `ThreadPoolExecutor` |

#### `run(suite)`

Iterates every `(case, scorer_config)` pair in `suite`:

1. Skips cases where `skip=True` or where tags don't match the `tags` filter
2. Calls the endpoint via `urllib.request` (stdlib — no extra dependencies)
3. On transient errors, retries up to `max_retries` times with exponential backoff
4. Passes the raw response text to the scorer
5. Appends an `EvalResult` with token usage extracted from the API response

When `jobs > 1`, cases are dispatched to a `ThreadPoolExecutor` for parallel evaluation.

Returns `list[EvalResult]` — one per `(case, scorer)` pair that was not skipped.

---

### `RegressionDetector`

```python
class RegressionDetector:
    def __init__(self, score_drop_threshold: float = 0.1) -> None: ...

    def compare(
        self,
        baseline: list[EvalResult],
        current: list[EvalResult],
    ) -> RegressionReport: ...
```

Compares two result sets.  Matching is keyed on `(case_id, scorer_name)`.

A regression is detected when:
- A case **passed** in baseline but **fails** in current (pass→fail transition), **or**
- The score dropped by ≥ `score_drop_threshold` regardless of pass/fail status

Cases that appear only in `current` (new cases) are **not** counted as regressions.

---

### `RegressionReport`

```python
@dataclass
class RegressionReport:
    regressions: list[EvalResult]
    score_drops: list[tuple[EvalResult, EvalResult]]

    @property
    def has_regression(self) -> bool: ...

    def summary_lines(self) -> list[str]: ...
```

| Member | Description |
|---|---|
| `regressions` | `EvalResult` objects from *current* that represent a pass→fail transition |
| `score_drops` | `(baseline_result, current_result)` pairs with a score drop ≥ threshold |
| `has_regression` | `True` if either list is non-empty |
| `summary_lines()` | Human-readable lines suitable for printing to CI logs |

---

## Dataset I/O — `sf_behaviour.dataset`

### `save_results(results, path)`

```python
def save_results(results: list[EvalResult], path: str) -> None
```

Write `results` to a JSONL file.

- Uses `spanforge.exporters.jsonl.SyncJSONLExporter`; each result is wrapped in a `spanforge.event.Event` with `event_type = "llm.eval.scenario.completed"`.
- Creates parent directories automatically.
- Falls back to plain JSON-lines if spanforge is unavailable.

---

### `load_results(path)`

```python
def load_results(path: str) -> list[EvalResult]
```

Read a JSONL file previously written by `save_results`.

- Uses `spanforge.stream.EventStream.from_file()`.
- Falls back to plain JSON-line reading if spanforge is unavailable.
- Returns `[]` for an empty file.

---

### `parse_csv(path, ...)`

```python
def parse_csv(
    path: str,
    scorer_name: str = "exact_match",
    threshold: float = 0.5,
    model: str = "gpt-4o",
    endpoint: str = "https://api.openai.com/v1",
) -> TestSuite
```

Parse a CSV/TSV file into a `TestSuite`.  
Expected columns: `id`, `prompt`, `expected` (optional), `tags` (optional, comma-separated).

| Parameter | Default | Description |
|---|---|---|
| `path` | *(required)* | Path to the CSV or TSV file |
| `scorer_name` | `"exact_match"` | Default scorer name for all cases |
| `threshold` | `0.5` | Default pass threshold for all cases |
| `model` | `"gpt-4o"` | Default model for the suite |
| `endpoint` | `"https://api.openai.com/v1"` | Default endpoint for the suite |

---

### `parse_dataset(path, ...)`

```python
def parse_dataset(
    path: str,
    scorer_name: str = "exact_match",
    threshold: float = 0.5,
    model: str = "gpt-4o",
    endpoint: str = "https://api.openai.com/v1",
) -> TestSuite
```

Parse a JSONL dataset file into a `TestSuite`.  
Each line is a JSON object with `id`, `messages` (list of `{role, content}`), and optionally `expected`, `tags`.

| Parameter | Default | Description |
|---|---|---|
| `path` | *(required)* | Path to the JSONL file |
| `scorer_name` | `"exact_match"` | Default scorer name for all cases |
| `threshold` | `0.5` | Default pass threshold for all cases |
| `model` | `"gpt-4o"` | Default model for the suite |
| `endpoint` | `"https://api.openai.com/v1"` | Default endpoint for the suite |

---

## Reports — `sf_behaviour.report`

### `ScorerSummary`

```python
@dataclass
class ScorerSummary:
    name: str
    total: int
    passed: int
    failed: int
    avg_score: float
```

Aggregated statistics for one scorer across all results.

---

### `SuiteReport`

```python
@dataclass
class SuiteReport:
    total: int
    passed: int
    failed: int
    scorers: list[ScorerSummary]
    results: list[EvalResult]
```

Full report containing aggregate stats and per-scorer breakdowns.

---

### `build_report(results)`

```python
def build_report(results: list[EvalResult]) -> SuiteReport
```

Aggregate a flat list of `EvalResult` objects into a structured `SuiteReport`.

---

### `render_html(report)`

```python
def render_html(report: SuiteReport) -> str
```

Render a `SuiteReport` as a self-contained HTML document.

---

### `render_markdown(report)`

```python
def render_markdown(report: SuiteReport) -> str
```

Render a `SuiteReport` as Markdown text.

---

## Built-in scorers — `sf_behaviour.scorers`

```python
from sf_behaviour.scorers import BUILT_IN_SCORERS
# {'refusal': RefusalScorer(), 'pii_leakage': PIILeakageScorer(),
#  'faithfulness': FaithfulnessScorer(), 'exact_match': ExactMatchScorer(),
#  'llm_judge': LLMJudgeScorer(), 'json_schema': JSONSchemaScorer()}

from sf_behaviour.scorers.refusal import RefusalScorer
from sf_behaviour.scorers.pii_leakage import PIILeakageScorer
from sf_behaviour.scorers.faithfulness import FaithfulnessScorer
from sf_behaviour.scorers.exact_match import ExactMatchScorer
from sf_behaviour.scorers.llm_judge import LLMJudgeScorer
from sf_behaviour.scorers.json_schema import JSONSchemaScorer
```

See [Built-in scorers](scorers.md) for detailed behaviour documentation.
