# Changelog

All notable changes to **sf-behaviour** are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.1] — 2026-04-16

### Changed

- **Upgraded spanforge dependency** from 2.0.2 to 2.0.3
- **Replaced local HTTP client** (`urllib.request` with retry/backoff) in `EvalRunner._call_endpoint()` and `LLMJudgeScorer` with `spanforge.http.chat_completion()`
- **Replaced local env-var interpolation** engine (`_ENV_VAR_RE`, `_interpolate_env`, `_interpolate_data`) in `yaml_parser.py` with `spanforge.config.interpolate_env()`
- **Replaced local JSON Schema validator** (`_validate()` in `json_schema.py`) with `spanforge.schema.validate()`
- **Replaced local plugin discovery** (`importlib.metadata` cross-version shim) in `EvalRunner._discover_plugins()` with `spanforge.plugins.discover()`
- **Replaced local `EvalScorer` ABC** with `spanforge.eval.BehaviourScorer` (re-exported as `EvalScorer`)
- **Retained local ANSI color utility** (`_color()` in `cli.py`) — `spanforge.cli` does not exist
- **Replaced inline percentile calculation** in `report.py` with `spanforge.stats.percentile()`
- **Replaced JSONL persistence** (3-layer `SyncJSONLExporter`/`EventStream`/plain-JSON fallback) in `dataset.py` with `spanforge.io.write_jsonl()` / `read_jsonl()`
- **Simplified PII scanner** in `pii_leakage.py` — removed fallback regex patterns, uses `spanforge.redact.scan_payload()` directly

### Removed

- Local `urllib.request`-based HTTP client with retry logic (now in spanforge)
- Local `_ENV_VAR_RE` regex and interpolation functions (now in spanforge)
- Local JSON Schema `_validate()` implementation (now in spanforge)
- Local `importlib.metadata` cross-version `entry_points()` shim (now in spanforge)
- Local `EvalScorer(ABC)` abstract base class definition (now `BehaviourScorer` in spanforge)
- Fallback PII regex patterns in `pii_leakage.py` (spanforge 2.0.3 is stable)
- `SyncJSONLExporter` / `EventStream` imports and 3-layer fallback in `dataset.py`
- Local ANSI `_color()` helper retained — `spanforge.cli` module does not exist

---

## [1.0.0] — 2026-04-16

### Added

#### Core
- `EvalScorer` — abstract base class for all scorers; subclass and implement `score(case, response) -> (float, str)` to build custom scorers
- `EvalResult` — frozen dataclass capturing score, threshold, pass/fail, reason, latency, model, endpoint, tags, token usage, and optional error per (case × scorer) pair
- `EvalRunner` — orchestrates HTTP calls to any OpenAI-compatible `/chat/completions` endpoint; applies all configured scorers; records latency and timestamps
- `EvalRunner(jobs=N)` — run test cases across *N* threads using `concurrent.futures.ThreadPoolExecutor`
- `EvalRunner(max_retries=N)` — retry transient HTTP errors (429, 5xx, network errors) with exponential backoff
- `EvalRunner(tags=[...])` — run only cases whose tags intersect with the filter set
- `RegressionDetector` — compares two result sets (baseline vs current) and reports pass→fail transitions and score drops above a configurable threshold
- `RegressionReport` — dataclass returned by `RegressionDetector.compare()`; `has_regression` property enables one-line CI gating

#### YAML test-case format
- `parse_yaml(path)` — parses a YAML file into a typed `TestSuite`
- Supports `version`, `defaults` (model / endpoint / timeout), and a `cases` list
- Per-case overrides for `model`, `endpoint`, `context`, and `tags`
- Per-case `skip: true` to exclude individual cases without deleting them
- Scorers declared as bare strings (`- refusal`) or full mappings (`{name, threshold, ...params}`)
- Environment variable interpolation in YAML: `${VAR}` and `${VAR:default}` syntax in any string value

#### Built-in scorers
- `RefusalScorer` — 16 regex patterns covering common model-refusal phrases; `1.0` = refusal detected (pass), `0.0` = no refusal (fail)
- `PIILeakageScorer` — delegates to `spanforge.redact.scan_payload()` for SSN, credit-card (Luhn), Aadhaar (Verhoeff), email, phone, date-of-birth, and IP detection; `1.0` = clean (pass), `0.0` = PII found (fail)
- `FaithfulnessScorer` — word-overlap metric between `context` and response; removes stopwords; score = fraction of context terms appearing in response
- `ExactMatchScorer` — three modes: `contains` (default), `equals`, `regex`; configure via `expected`, `pattern`, `mode` params
- `LLMJudgeScorer` — sends prompt + response to a judge model with a rubric; extracts a 0–10 score and normalises to 0.0–1.0; configurable `rubric`, `judge_model`, `judge_endpoint`, `judge_api_key`
- `JSONSchemaScorer` — validates response JSON against a JSON Schema; built-in validator supports `type`, `required`, `properties`, `items`, `enum`; handles code-fenced responses

#### Token / cost tracking
- `EvalResult.prompt_tokens`, `EvalResult.completion_tokens`, `EvalResult.total_tokens` — populated from the OpenAI `usage` response field

#### Report generation
- `build_report(results)` → `SuiteReport` with pass rate, latency percentiles (p50/p95/p99), token totals, per-scorer and per-tag breakdowns
- `render_markdown(report)` → Markdown string
- `render_html(report)` → standalone HTML page with embedded CSS

#### Dataset I/O
- `save_results(results, path)` — persists results to JSONL using `spanforge.exporters.jsonl.SyncJSONLExporter`; event type `llm.eval.scenario.completed`
- `load_results(path)` — reads JSONL back into `list[EvalResult]` via `spanforge.stream.EventStream.from_file()`; plain-JSON fallback included
- `parse_csv(path)` — load test cases from CSV or TSV files (columns: `id`, `prompt`, `expected`, `tags`)
- `parse_dataset(path)` — load test cases from JSONL files (fields: `id`, `messages`/`prompt`, `expected`, `tags`)

#### CLI
- `sf-behaviour run TEST_FILE` — run all cases in a YAML file; optional `--endpoint`, `--model`, `--api-key`, `--output`, `--baseline`, `--score-drop-threshold`, `--timeout`, `--verbose`, `--tag`, `--jobs`, `--retry`, `--report`
- `sf-behaviour compare BASELINE CURRENT` — compare two saved JSONL files; exits `1` on regression
- `sf-behaviour init [DIR]` — scaffold a starter `tests.yaml` with two example cases
- `sf-behaviour watch TEST_FILE [options]` — poll a test file and re-run on change
- Exit code `0` = all pass / no regression; `1` = any failure or regression detected
- ANSI colour output (auto-disabled when stdout is not a TTY or `NO_COLOR` is set)
- Summary output includes mean/p50/p95/p99 latency, token totals, per-scorer breakdown, and per-tag pass rates

#### Plugin system
- Auto-discover scorers via `sf_behaviour.scorers` entry points using `importlib.metadata`

#### Package
- `src`-layout Python package; distribution name `sf-behaviour`; import name `sf_behaviour`
- Hatchling build backend
- Dependencies: `spanforge==2.0.3`, `PyYAML>=6.0`
- Dev extras: `pytest`, `pytest-cov`, `ruff`, `mypy`
- 177 tests; 92 % line coverage

---

[1.0.1]: https://github.com/viswanathanstartup/sf-behaviour/releases/tag/v1.0.1
[1.0.0]: https://github.com/viswanathanstartup/sf-behaviour/releases/tag/v1.0.0
