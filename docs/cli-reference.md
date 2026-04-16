# CLI reference

`sf-behaviour` exposes four subcommands: `run`, `compare`, `init`, and `watch`.

---

## Global options

```
sf-behaviour [--version] [--help]
```

| Flag | Description |
|---|---|
| `--version`, `-V` | Print the version string and exit |
| `--help`, `-h` | Print help and exit |

---

## `sf-behaviour run`

Run all test cases in a YAML file against an OpenAI-compatible endpoint.

```
sf-behaviour run TEST_FILE [options]
```

### Positional arguments

| Argument | Description |
|---|---|
| `TEST_FILE` | Path to a YAML test-case file (see [YAML format](yaml-format.md)) |

### Options

| Flag | Short | Default | Description |
|---|---|---|---|
| `--endpoint URL` | `-e` | *(from YAML defaults)* | Override the endpoint URL for **every** case in the file |
| `--model NAME` | `-m` | *(from YAML defaults)* | Override the model name for **every** case |
| `--api-key KEY` | `-k` | `$OPENAI_API_KEY` | Bearer token for the endpoint. Reads `OPENAI_API_KEY` env var when omitted |
| `--output FILE` | `-o` | *(not saved)* | Write results to a JSONL file after the run. Use this file as a future `--baseline` |
| `--baseline FILE` | `-b` | *(no regression check)* | Compare current results against a previously saved JSONL. Exits `1` on regression |
| `--score-drop-threshold N` | | `0.1` | Minimum score decrease (0.0–1.0) that counts as a regression when `--baseline` is set |
| `--timeout N` | | `30` | Per-request HTTP timeout in seconds |
| `--verbose` | `-v` | `false` | Print the reason string, latency, and a response preview for every result |
| `--tag TAG` | `-t` | *(no filter)* | Run only cases with this tag. Repeatable: `--tag safety --tag smoke` |
| `--jobs N` | `-j` | `1` | Number of parallel workers for case evaluation |
| `--retry N` | | `0` | Number of retries on transient HTTP errors (429, 5xx) with exponential backoff |
| `--report FILE` | | *(no report)* | Export a summary report. Use `.html` for HTML or `.md` for Markdown |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All cases passed (and no regression vs baseline, if `--baseline` was set) |
| `1` | One or more cases failed, or a regression was detected |

### Examples

```bash
# Basic run — uses $OPENAI_API_KEY
sf-behaviour run cases.yaml

# Override endpoint and model
sf-behaviour run cases.yaml \
  --endpoint https://my-proxy.example.com/v1 \
  --model gpt-4-turbo

# Save results as a baseline
sf-behaviour run cases.yaml --output baseline.jsonl

# Gate on baseline
sf-behaviour run cases.yaml --baseline baseline.jsonl

# Tighten regression sensitivity
sf-behaviour run cases.yaml --baseline baseline.jsonl --score-drop-threshold 0.05

# Verbose output for debugging
sf-behaviour run cases.yaml --verbose

# Combine: save and compare against last run
sf-behaviour run cases.yaml \
  --baseline previous.jsonl \
  --output current.jsonl \
  --verbose

# Run only safety-tagged cases in parallel with retry
sf-behaviour run cases.yaml \
  --tag safety \
  --jobs 4 \
  --retry 2

# Generate an HTML report
sf-behaviour run cases.yaml --report report.html
```

---

## `sf-behaviour compare`

Compare two previously saved JSONL result files and report regressions.  
Useful when you want to compare result snapshots offline without re-running the endpoint.

```
sf-behaviour compare BASELINE CURRENT [options]
```

### Positional arguments

| Argument | Description |
|---|---|
| `BASELINE` | Path to the baseline JSONL (earlier run) |
| `CURRENT` | Path to the current JSONL (later run) |

### Options

| Flag | Default | Description |
|---|---|---|
| `--score-drop-threshold N` | `0.1` | Minimum score decrease that counts as a regression |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | No regression detected |
| `1` | One or more regressions detected, or a file could not be read |

### Examples

```bash
# Compare two saved runs
sf-behaviour compare monday.jsonl friday.jsonl

# Use a stricter threshold
sf-behaviour compare monday.jsonl friday.jsonl --score-drop-threshold 0.05
```

---

## `sf-behaviour init`

Scaffold a starter `tests.yaml` file with example test cases.

```
sf-behaviour init [DIR]
```

### Positional arguments

| Argument | Default | Description |
|---|---|---|
| `DIR` | `.` (current directory) | Directory to create `tests.yaml` in |

### Behaviour

- Creates `tests.yaml` with two example cases (greeting test + safety check)
- **Refuses to overwrite** an existing file — exits `1` if `tests.yaml` already exists

### Example

```bash
sf-behaviour init
# Created starter test file: tests.yaml

sf-behaviour init my-project/
# Created starter test file: my-project/tests.yaml
```

---

## `sf-behaviour watch`

Watch a test file for changes and re-run automatically.  
Accepts all `run` flags.

```
sf-behaviour watch TEST_FILE [run options]
```

### Behaviour

- Polls the file every second for modification-time changes
- On change, re-runs all cases with the same options as `run`
- Press `Ctrl+C` to stop

### Example

```bash
sf-behaviour watch cases.yaml --tag safety --verbose
```

---

## Environment variables

| Variable | Used by | Description |
|---|---|---|
| `OPENAI_API_KEY` | `run`, `watch` | Default API key when `--api-key` is not provided |
| `NO_COLOR` | all | When set, disables ANSI colour output |

---

## Output format

### Normal output (non-verbose)

```
sf-behaviour 1.0.0  3 case(s) — model=gpt-4o  endpoint=https://api.openai.com/v1
Running...

  [PASS] refusal-weapons / refusal          score=1.00 (threshold=0.50)
  [PASS] pii-customer-lookup / pii_leakage  score=1.00 (threshold=1.00)
  [FAIL] faithfulness-product / faithfulness score=0.41 (threshold=0.60)

  2 passed, 1 failed  (total 3)
```

### Verbose output (`--verbose`)

```
  [PASS] refusal-weapons / refusal  score=1.00 (threshold=0.50)
         reason  : refusal phrase detected: "i can't help with that"
         latency : 834 ms
         response: I'm sorry, but I can't help with providing instructions ...
```

### Regression report

```
REGRESSION DETECTED:
  1 new failure(s):
    [refusal-weapons] refusal: score=0.00 threshold=0.50 — no refusal phrase detected
  1 score drop(s):
    [faithfulness-product] faithfulness: 0.83 → 0.41
```

### Colour support

ANSI colours are used when stdout is a TTY (green = PASS, red = FAIL/REGRESSION).  
Colours are automatically disabled when output is piped or redirected.
