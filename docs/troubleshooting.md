# Troubleshooting

## HTTP 401 Unauthorized

**Symptom:** Results show `error=HTTP 401: Unauthorized` and all cases fail.

**Cause:** The API key is missing or invalid.

**Fix:**
```bash
export OPENAI_API_KEY=sk-...
sf-behaviour run cases.yaml
```

Or pass it directly:
```bash
sf-behaviour run cases.yaml --api-key sk-...
```

---

## Connection refused / Could not connect

**Symptom:** `error=<urlopen error [Errno 111] Connection refused>` or similar.

**Cause:** The endpoint is not reachable. Common causes:
- Local dev server not running
- Wrong port in the endpoint URL
- Firewall or VPN blocking the connection

**Fix:** Verify the endpoint is up and reachable:
```bash
curl https://your-endpoint/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"
```

To override the endpoint for a test run:
```bash
sf-behaviour run cases.yaml --endpoint https://correct-endpoint.com/v1
```

---

## Request timeout

**Symptom:** `error=<urlopen error timed out>` — cases fail slowly.

**Cause:** The endpoint is too slow or unresponsive within the default 30-second timeout.

**Fix:** Increase the timeout:
```bash
sf-behaviour run cases.yaml --timeout 120
```

---

## Regression detected unexpectedly

**Symptom:** `sf-behaviour run` exits 1 with a regression report, but you didn't change anything.

**Cause:** Model non-determinism — the same prompt scores slightly differently on each call.

**Options:**

1. Widen the score-drop threshold (accept more variance):
   ```bash
   sf-behaviour run cases.yaml --baseline baseline.jsonl --score-drop-threshold 0.15
   ```

2. Regenerate the baseline from the current run:
   ```bash
   sf-behaviour run cases.yaml --output baseline.jsonl
   ```

3. Use a lower-temperature model or set `temperature: 0` in your endpoint configuration.

---

## YAML parse error: `missing required field 'id'`

**Symptom:** `Error parsing 'cases.yaml': case #1 missing required field 'id'`

**Fix:** Every test case must have a unique string `id` field:
```yaml
cases:
  - id: tc-001       # required
    name: My test    # required
    messages:
      - role: user
        content: "..."
    scorers:
      - name: refusal
```

See [docs/yaml-format.md](yaml-format.md) for the full schema.

---

## `sf-behaviour: command not found`

**Symptom:** Shell reports the command is not found after installation.

**Fix:** Make sure the package is installed into the active Python environment:
```bash
pip install sf-behaviour
which sf-behaviour   # should resolve
```

If using a virtual environment:
```bash
source .venv/bin/activate
sf-behaviour --version
```

---

## All scores are 0.0 with `error=unexpected response shape`

**Symptom:** Every result has `score=0.0` and the error mentions "unexpected response shape".

**Cause:** The endpoint does not return an OpenAI-compatible response. The runner expects:
```json
{"choices": [{"message": {"content": "..."}}]}
```

**Fix:** Ensure the endpoint is OpenAI-compatible. If you control the endpoint, verify the response format. If using Azure OpenAI, ensure the deployment name and API version are correct.

---

## Colors not showing in CI

**Symptom:** CLI output contains raw ANSI escape codes (e.g., `\033[32m`) instead of colored text.

**Cause:** Your CI environment does not report as a TTY, or the `NO_COLOR` environment variable is set.

**Fix:** Most CI systems strip ANSI automatically. If you're seeing raw codes, ensure the terminal emulator or log viewer supports ANSI, or disable colors entirely by setting `NO_COLOR=1`.
