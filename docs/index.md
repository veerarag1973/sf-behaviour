# sf-behaviour documentation

**sf-behaviour** is a behaviour test runner for OpenAI-compatible LLM endpoints.  
Describe expected model behaviour in YAML, run it against any endpoint, score results, and gate CI on regression.

---

## Contents

| Document | Description |
|---|---|
| [Getting started](getting-started.md) | Install, write your first test file, and run it |
| [YAML test-case format](yaml-format.md) | Complete reference for the `cases.yaml` schema, env var interpolation |
| [Built-in scorers](scorers.md) | Six scorers: `refusal`, `pii_leakage`, `faithfulness`, `exact_match`, `llm_judge`, `json_schema` |
| [CLI reference](cli-reference.md) | All flags for `run`, `compare`, `init`, and `watch` |
| [Python API reference](api-reference.md) | `EvalRunner`, `EvalScorer`, `RegressionDetector`, dataset I/O, reports |
| [CI integration](ci-integration.md) | GitHub Actions, GitLab CI, and other pipelines |
| [Writing custom scorers](custom-scorers.md) | Extend sf-behaviour with your own scoring logic and plugin entry points |

---

## Architecture in one diagram

```
cases.yaml / CSV / JSONL
    │
    ▼
parse_yaml() / parse_csv() / parse_dataset()
    │
    ▼
TestSuite
    │
    ▼
EvalRunner.run(suite)
│   ├── tag filtering + skip
│   ├── parallel (ThreadPoolExecutor)
│   └── retry with backoff
│         │
│         ▼
│   HTTP call    apply scorers
│   (stdlib)     (EvalScorer.score)
│         │         │
│         └────┬────┘
│              ▼
│        list[EvalResult]
│              │
│    ┌─────────┼──────────────┐
│    ▼         ▼              ▼
│ save_results()  RegressionDetector  build_report()
│ (JSONL/spanforge) .compare()       │
│                      │        ┌────┴────┐
│                      ▼        ▼         ▼
│              RegressionReport render_html() render_markdown()
│              .has_regression
│                → exit code
```

---

## Design principles

- **Zero surprise dependencies** — HTTP calls use `spanforge.http.chat_completion()`; only `spanforge` and `PyYAML` are runtime deps.
- **Scorer composability** — each scorer is independent; a single test case can have multiple scorers. Six built-in plus plugin discovery via entry points.
- **Baseline-gated CI** — results are serialised to JSONL (via `spanforge.io.write_jsonl`) so any future run can be compared against any past run.
- **Extensible** — `EvalScorer` is an ABC; drop in a custom scorer with two lines of code. Distribute via entry points.
- **Parallel & resilient** — run cases concurrently with `--jobs`, retry transient errors with `--retry`, filter with `--tag`.
