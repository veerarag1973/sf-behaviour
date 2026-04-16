# Contributing

## Development setup

```bash
git clone https://github.com/veerarag1973/sf-behaviour
cd sf-behaviour
pip install -e ".[dev]"
pre-commit install
```

## Running tests

```bash
pytest tests/
```

With coverage:

```bash
pytest tests/ --cov=sf_behaviour --cov-report=term-missing
```

## Linting and type checking

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/sf_behaviour
```

Or run all checks in one step via pre-commit:

```bash
pre-commit run --all-files
```

## Project layout

```
src/sf_behaviour/
  __init__.py          Public API re-exports
  yaml_parser.py       YAML test-case parsing + env var interpolation
  eval.py              EvalRunner, EvalScorer ABC, RegressionDetector
  dataset.py           JSONL persistence (save/load)
  report.py            SuiteReport, build_report(), render_html(), render_markdown()
  scorers/
    refusal.py         RefusalScorer
    pii_leakage.py     PIILeakageScorer
    faithfulness.py    FaithfulnessScorer
    exact_match.py     ExactMatchScorer
    llm_judge.py       LLMJudgeScorer
    json_schema.py     JSONSchemaScorer
  cli.py               CLI entry point (run, compare, init, watch)
tests/
docs/
examples/
```

## Adding a scorer

1. Create `src/sf_behaviour/scorers/my_scorer.py` — subclass `EvalScorer`, set `name`, implement `score()`.
2. Add it to `BUILT_IN_SCORERS` in `src/sf_behaviour/scorers/__init__.py` if it should be available by name in YAML files.
3. Add tests under `tests/test_scorers.py`.
4. Document it in `docs/scorers.md`.

See [docs/custom-scorers.md](docs/custom-scorers.md) for a full guide.

## Submitting a PR

1. Fork the repo and create a feature branch.
2. Make your changes with tests — coverage must remain ≥ 90%.
3. Run `pre-commit run --all-files` and fix any issues.
4. Open a pull request against `main` with a clear description of the change.
