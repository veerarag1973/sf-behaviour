# CI integration

sf-behaviour is designed to run in CI pipelines.  
Exit codes are the primary integration mechanism:

| Exit code | Meaning |
|---|---|
| `0` | All cases passed / no regression |
| `1` | One or more failures, or a regression detected |

---

## Strategy: baseline file in version control

The recommended approach is to commit a `baseline.jsonl` alongside your test cases.  
Update it deliberately when you intentionally change model behaviour.

```
repo/
  cases.yaml          ← test cases
  baseline.jsonl      ← committed baseline (updated manually after intentional changes)
```

**Day-to-day CI:**
```bash
sf-behaviour run cases.yaml --baseline baseline.jsonl
```

**After an intentional model change:**
```bash
sf-behaviour run cases.yaml --output baseline.jsonl
git add baseline.jsonl
git commit -m "chore: update behaviour baseline after gpt-4o upgrade"
```

---

## GitHub Actions

### Basic — fail on any case failure

```yaml
# .github/workflows/behaviour.yml
name: Behaviour tests

on:
  push:
  pull_request:

jobs:
  behaviour:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install sf-behaviour
        run: pip install sf-behaviour

      - name: Run behaviour tests
        run: sf-behaviour run cases.yaml
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

### With regression gating (recommended)

```yaml
      - name: Run behaviour tests with regression gate
        run: sf-behaviour run cases.yaml --baseline baseline.jsonl
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

### Save results as a workflow artifact

```yaml
      - name: Run and save results
        run: |
          sf-behaviour run cases.yaml \
            --baseline baseline.jsonl \
            --output results-${{ github.run_id }}.jsonl
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

      - name: Upload results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: behaviour-results
          path: results-*.jsonl
```

### Scheduled regression check (nightly)

```yaml
on:
  schedule:
    - cron: "0 2 * * *"   # 02:00 UTC every night

jobs:
  nightly-behaviour:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install sf-behaviour
      - run: sf-behaviour run cases.yaml --baseline baseline.jsonl --verbose
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

---

## GitLab CI

```yaml
# .gitlab-ci.yml
behaviour-tests:
  image: python:3.12-slim
  stage: test
  script:
    - pip install sf-behaviour
    - sf-behaviour run cases.yaml --baseline baseline.jsonl
  variables:
    OPENAI_API_KEY: $OPENAI_API_KEY   # set in GitLab CI/CD Variables
  artifacts:
    when: always
    paths:
      - "*.jsonl"
    expire_in: 30 days
```

---

## Azure Pipelines

```yaml
# azure-pipelines.yml
trigger:
  - main

pool:
  vmImage: ubuntu-latest

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: "3.12"

  - script: pip install sf-behaviour
    displayName: Install sf-behaviour

  - script: sf-behaviour run cases.yaml --baseline baseline.jsonl
    displayName: Run behaviour tests
    env:
      OPENAI_API_KEY: $(OPENAI_API_KEY)
```

---

## Jenkins

```groovy
pipeline {
    agent any
    environment {
        OPENAI_API_KEY = credentials('openai-api-key')
    }
    stages {
        stage('Behaviour tests') {
            steps {
                sh 'pip install sf-behaviour'
                sh 'sf-behaviour run cases.yaml --baseline baseline.jsonl'
            }
        }
    }
    post {
        always {
            archiveArtifacts artifacts: '*.jsonl', allowEmptyArchive: true
        }
    }
}
```

---

## Targeting a non-production endpoint

Override the endpoint at CI time to test a staging or shadow model without changing your YAML:

```bash
sf-behaviour run cases.yaml \
  --endpoint https://staging.example.com/v1 \
  --model gpt-4o-mini \
  --baseline staging-baseline.jsonl
```

---

## Tips

**Keep baseline.jsonl small.**  
Only commit the baseline for the `main` branch.  Use `--output` to generate and archive per-PR baselines as artefacts rather than committing them.

**Use tags to run a fast smoke subset.**  
sf-behaviour runs all cases in the file.  Maintain separate `cases-smoke.yaml` and `cases-full.yaml` files and run the smoke file on every push and the full file on schedule.

**Tighten `--score-drop-threshold` as you gain confidence.**  
Start with `0.1` (default). Once your baseline is stable, drop to `0.05` to catch subtler regressions.

**Rotate your baseline deliberately.**  
When upgrading a model, generate a new baseline and review the diff with `sf-behaviour compare old-baseline.jsonl new-baseline.jsonl` before committing it.
