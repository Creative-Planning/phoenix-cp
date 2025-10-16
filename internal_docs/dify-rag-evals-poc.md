# Dify RAG Evals PoC

Run relevance, hallucination, and QA correctness evaluators locally (and prepare for cloud deployment) using Phoenix traces generated from a Dify knowledge-retrieval workflow.

## Prerequisites

- Phoenix running locally via Docker Compose (collector accessible at `http://localhost:6006`).
- Dify workflow instrumented with `openinference` so retriever and root LLM spans appear in Phoenix.
- Phoenix image built from this repo (Dockerfile already installs Phoenix + eval modules).
- Any extra LLM SDKs (e.g., `openai`, `anthropic`, `litellm`) available to the container. Add them to `pyproject.toml` or a requirements file referenced by the Docker build if you need more providers.
- Environment secrets:
  - `OPENAI_API_KEY` (or equivalent provider key).
  - `PHOENIX_API_KEY` (if using authenticated Phoenix).
  - `PHOENIX_COLLECTOR_ENDPOINT` and `PHOENIX_PROJECT` (defaults to `default`).
  - Database settings (`POSTGRES_*`) and Phoenix auth flags as already defined in `.env`.

## Run the Eval Script Locally

1. Update `.env` (or a separate `.env.local` ignored by git) with your secrets (see “Environment Variables”).
2. Build/start the stack:
   ```bash
   docker compose up -d --build
   ```
3. Capture a few workflow runs in Phoenix so retriever + answer spans exist.
4. Execute a one-off eval run (optional if the sidecar loop is already running):
   ```bash
   docker compose exec eval-runner \
     python scripts/evals/run_dify_rag_evals.py --since-minutes 120 --explain
   ```
   (The container already exports defaults from `.env`; you can also run the script directly on the host.)
5. Check eval logs:
   ```bash
   docker compose logs -f eval-runner
   ```
6. Open Phoenix UI → Evaluations/Annotations to review scores. Each run logs:
   - `Hallucination` (span-level)
   - `Retrieval Relevance` (document-level)
   - `QA Correctness` (span-level, optional)

## Scheduling / Automation

- **Docker Compose sidecar**: `eval-runner` service (added to `docker-compose.yml`) runs `python -m scripts.evals.run_dify_rag_evals --loop`, sleeping `EVAL_INTERVAL_SECONDS` between runs. Disable the service if you only want manual runs.
- **Local cron/systemd**: Comment out the sidecar service and invoke the script on your own schedule (e.g., `docker compose exec phoenix python scripts/evals/run_dify_rag_evals.py`).
- **Metrics comparison**: Persist eval outputs (e.g., store CSV copies) alongside build artifacts for regression tracking.

## Path to Cloud (ECS or Similar)

1. Build/push the Phoenix image (same Dockerfile). Ensure any extra eval dependencies are included.
2. Create ECS task definitions that reference that image:
   - Phoenix server container: command `-m phoenix.server.main serve`.
   - Eval runner container: command `-m scripts.evals.run_dify_rag_evals --loop`.
   (Alternatively use separate services/tasks if you prefer.)
3. Inject secrets via AWS Secrets Manager or SSM (map them to the same environment variables listed below).
4. Provide the Phoenix collector URL appropriate to your hosted deployment.
5. Schedule the eval task with EventBridge, Step Functions, or keep it running continuously (Fargate service) just like the local loop.
6. Logged annotations appear in the hosted Phoenix UI; configure dashboards/alerts accordingly.

## Troubleshooting

- **No spans found**: Increase `--since-minutes` or confirm Dify instrumentation emits retriever spans with `retrieval_documents`.
- **Model auth errors**: Verify provider API key environment variable inside the container.
- **Evaluator schema errors**: Ensure Phoenix container version matches repo code; mismatched versions can cause schema validation failures.
- **Missing dependencies**: If the eval runner complains about imports (e.g., `openai`), add the package to the build (update `pyproject.toml` or extend the Dockerfile install step).

## Environment Variables (local `.env`)

```
OPENAI_API_KEY=replace-with-openai-key
PHOENIX_PROJECT=default
PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:6006
# Optional auth
# PHOENIX_API_KEY=...
# PHOENIX_CLIENT_HEADERS=api_key=...

POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postgres
PHOENIX_ENABLE_AUTH=true
PHOENIX_SECRET=replace-with-secure-32-char-value

EVAL_MODEL=gpt-4o
EVAL_WINDOW_MINUTES=60
EVAL_INTERVAL_SECONDS=900
EVAL_SKIP_QA=false
EVAL_EXPLAIN=false
```

Keep real secrets out of source control—store them in `.env.local`, shell exports, or a secret manager, and only commit safe defaults.
