# Phoenix Evals & Experiments How-To

> Audience: Analysts and workflow owners who need to run experiments or review eval scores. For deployment / infrastructure steps, see `docs/creative-planning/dify-rag-deployment.md`.

This guide explains how to run retrieval-quality evaluations for the Dify knowledge workflow using the custom tooling we added on the `gba-poc` branch. It covers dataset expectations, when to use each runner, and how the different evaluators behave with and without gold answers.

---

## 1. Components We Maintain

- `scripts/experiments/run_dify_experiment.py` — core experiment runner that pulls a Phoenix dataset, calls the Dify workflow for every row, and logs evaluator scores back to Phoenix.
- `scripts/experiments/run_experiment.sh` — local convenience wrapper for the Python script.
- `scripts/experiments/run_experiment_docker.sh` + `docs/cp-docs/running-experiments-docker.md` — wrappers and docs for running the experiment inside the Docker Compose sidecar (`experiment-runner`).
- `scripts/evals/run_dify_rag_evals.py` — background eval runner that re-scores recent traces pulled directly from Phoenix (no new workflow calls).
- Supporting references: `scripts/experiments/DATASET_FORMATS.md`, `docs/cp-docs/dify-experiments-quickstart.md`, and `docs/creative-planning/dify-rag-deployment.md`.

Keep these pieces together when onboarding teammates; everything else in the OSS repo is upstream documentation.

---

## 2. Dataset Expectations

`run_dify_experiment.py` understands two dataset shapes. Both are created/stored inside Phoenix so we can compare experiments in the UI.

### 2.1 Input-Only Datasets (pulled from traces)

Use this when you collect prompts via Phoenix tracing (e.g., select “Add to dataset” on trace rows). Those datasets usually contain only the user request and the original workflow answer.

- **Input column names supported:** `question`, `query`, `input`, or Phoenix trace exports’ `sys.query`.
- **Expected/Output column:** not required. The script sees that `expected` is missing and automatically disables QA correctness.
- **Evaluators that run:** custom code checks (`has_answer`, `no_error`, `has_retrieval`, `retrieval_count`) plus LLM-based **relevance** and **hallucination**. `qa_correctness` short-circuits with the explanation “No expected answer...” so the experiment still succeeds.
- **Typical creation flow:** collect traces → select rows in Phoenix UI → “Add to dataset” → name it (e.g., `Good 2025-10-20T14:32:32.450Z`).

This format is perfect for quick regressions when you only care about retrieval quality and hallucination risk.

### 2.2 Input + Gold Answer Datasets (curated CSV upload)

Upload a CSV (or create via the Python client) when you have authoritative answers.

- **Input column names:** same as above.
- **Gold answer column names:** `expected_answer` (preferred), or `answer`, `expected`, `output`, or `reference` (our FAQ export uses this).
- **Evaluator coverage:** everything from the input-only case **plus** the LLM `qa_correctness` check, because `run_dify_experiment.py` finds the gold answer and feeds it to the Phoenix QA evaluator.
- **Import reminder:** make sure `input_keys=["question"]` and `output_keys=["expected_answer"]` (matching actual column names) when creating the dataset through the Phoenix UI or SDK. See examples in `scripts/experiments/DATASET_FORMATS.md`.

Use this format when you need an objective pass/fail on the workflow’s final answer in addition to retrieval metrics.

---

## 3. Running Experiments (new workflow executions)

Experiments ask Dify to re-run the workflow, so you need valid API credentials and your Phoenix dataset name.

### 3.1 Environment prerequisites

- `DIFY_API_KEY` — from the Dify app’s API section (starts with `app-`).
- `DIFY_BASE_URL` — `http://localhost/v1` locally, or `http://host.docker.internal:7788` inside the Docker sidecar.
- `OPENAI_API_KEY` — used by the Phoenix LLM evaluators (`Hallucination`, `Relevance`, `QA`).
- `EVAL_MODEL` — judge model (default `gpt-4o`, overridable per run).
- Phoenix must be reachable (`PHOENIX_BASE_URL` defaults to `http://localhost:6006` outside Docker and `http://phoenix:6006` inside).

### 3.2 Local CLI wrapper (`run_experiment.sh`)

```bash
# Smoke test with three rows
./scripts/experiments/run_experiment.sh --dry-run

# Full run with a custom name
./scripts/experiments/run_experiment.sh "baseline-v1"

# Target a different dataset and skip QA (if you know it lacks gold answers)
./scripts/experiments/run_experiment.sh \
  --dataset "Good 2025-10-24T10:00:00.000Z" \
  --skip-qa \
  "retrieval-tuning-rc1"
```

The script validates `DIFY_API_KEY`, warns if `OPENAI_API_KEY` is missing, and then invokes `run_dify_experiment.py` with the right flags. Use `--dry-run N` to limit the row count, `--verbose` for debug logs, `--explain` for evaluator rationales.

### 3.3 Docker sidecar (`run_experiment_docker.sh`)

When Phoenix runs via Docker Compose, trigger experiments with the helper script (documented in `docs/cp-docs/running-experiments-docker.md`):

```bash
# Ensure phoenix service is up
docker compose up -d phoenix

# Run experiment in the sidecar container
./scripts/experiments/run_experiment_docker.sh "baseline-v1"
```

The wrapper will:
1. Check Phoenix health.
2. Invoke `docker compose run --rm experiment-runner -m scripts.experiments.run_dify_experiment ...`.
3. Forward any options you supply (`--dry-run`, `--skip-qa`, `--explain`, `--dataset`, etc.).

Inside Docker we map `host.docker.internal` so the sidecar can contact a host‑running Dify instance. Adjust `DIFY_BASE_URL` accordingly.

### 3.4 Reading the output

`run_dify_experiment.py` logs:
- Which dataset was used and how many examples were loaded.
- Any API errors from Dify per row.
- Evaluator counts (custom code + LLM judges).
- The Phoenix experiment ID and a UI link: `http://<phoenix>/datasets/<dataset_id>/compare?experimentId=<id>`.

Use the Phoenix UI **Experiments** tab to compare runs (baseline vs. new workflow version) across the relevance, hallucination, QA, and custom metrics we defined.

---

## 4. Continuous Trace Evals (`run_dify_rag_evals.py`)

Use this when you want to score live traffic without re-triggering the workflow.

- Runs in the `eval-runner` sidecar (see `docs/creative-planning/dify-rag-deployment.md`).
- Pulls recent Phoenix traces (`SpanQuery`) for the configured project (`PHOENIX_PROJECT`, default `default`).
- Extracts the user question and retrieved documents from span payloads, normalizes the text, and hands them to Phoenix’s Relevance, Hallucination, and optional QA evaluators.
- Flags:
  - `--since-minutes` — lookback window (overridden by `EVAL_WINDOW_MINUTES`).
  - `--loop` + `--interval-seconds` — continuous mode (used by the Docker service).
  - `--skip-qa`, `--explain`, `--dry-run`, `--verbose`.
- For local manual execution:

```bash
python -m scripts.evals.run_dify_rag_evals \
  --project default \
  --since-minutes 120 \
  --verbose \
  --dry-run
```

Because this path relies on existing traces, it naturally handles datasets that only have user inputs and generated answers; gold answers are optional here as well.

---

## 5. End-to-End Workflow

1. **Collect questions**  
   - Through live tracing (input-only dataset), or  
   - Via CSV/Python upload with curated answers.

2. **Run baseline experiment**  
   - `./scripts/experiments/run_experiment.sh "baseline"` or the Docker wrapper.
   - Confirm scores appear in Phoenix UI.

3. **Iterate on the Dify workflow**  
   - Adjust retrieval settings, prompt, model config, or knowledge base.

4. **Re-run experiment with a new name**  
   - Compare runs in Phoenix. Look for improvements on relevance, hallucination, and QA (if applicable).

5. **Monitor live traffic**  
   - Keep `eval-runner` running via Docker Compose to score traces continuously and spot regressions quickly.

6. **Need it on EC2?**  
   - Hand off to the platform team with a link to `docs/creative-planning/dify-rag-deployment.md`; they manage container builds, env files, and remote script copies.

---

## 6. FAQ & Tips

- **Why do experiments work with trace-derived datasets?**  
  `run_dify_experiment.py` looks for multiple field aliases (`question`, `query`, `input`, `sys.query`) so Phoenix exports from traces plug in directly. Missing gold answers only disables `qa_correctness`; all other evaluators still run.

- **How are retrieved documents passed to evaluators?**  
  The Dify API response contains `metadata.retriever_resources`. The task runner flattens that list into a newline separated string (`reference`). Hallucination and relevance evaluators consume that string as contextual evidence.

- **What happens if Dify errors?**  
  The task runner records the error message and sets `output=""`. The `no_error` evaluator fails, while LLM evaluators return zero with explanatory text so the experiment makes the failure visible.

- **Can I change the judge model?**  
  Yes. Set `EVAL_MODEL` or pass `--eval-model` when calling the script/wrapper. Any OpenAI-compatible model supported by Phoenix (e.g., `gpt-4o-mini`) will work, as long as the API key has access.

- **Where to look for log files?**  
  In verbose Docker runs, `run_experiment_docker.sh` prints container logs directly. For the eval sidecar, use `docker compose logs eval-runner`. If you pass `--log-dir` to `run_dify_rag_evals.py`, it writes detailed logs and DataFrames under that directory.

---

## 7. Related References

- Dataset examples and evaluator matrix — `scripts/experiments/DATASET_FORMATS.md`
- Quick commands cheat sheet — `scripts/experiments/QUICKSTART.md`
- Docker-specific instructions — `docs/cp-docs/running-experiments-docker.md`
- Full experiment README — `scripts/experiments/README.md`
- Deployment playbook — `docs/creative-planning/dify-rag-deployment.md`

Use this guide as the entry point for teammates; the linked files dive deeper into specific setup details when needed.
