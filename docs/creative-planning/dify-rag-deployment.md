# Dify RAG Evaluation & Deployment Playbook

> Audience: Platform/DevOps engineers responsible for running Phoenix + Dify infrastructure. For analyst-facing experiment instructions, point stakeholders to `docs/creative-planning/how-to-guide.md`.

This guide documents the pieces we’ve added on top of upstream Phoenix so the team can run evaluations and deploy the stack on EC2 in a consistent way.

## 1. Environment Configuration

All local Docker Compose runs and EC2 deployments share the same environment file schema. Start by copying `deploy/env/phoenix.env.example` to a secrets file (e.g. `.env` for local usage and `deploy/phoenix.ec2.env` for production) and fill in every placeholder.

Key sections in the env template:

- **Phoenix auth:** enable login (`PHOENIX_ENABLE_AUTH=true`), set long `PHOENIX_SECRET`, `PHOENIX_ADMIN_SECRET`, and rotate the default admin password.
- **Database:** Postgres runs as a sidecar; change the user/password as needed.
- **Phoenix API access:** `PHOENIX_API_KEY` is generated from the Phoenix UI and is consumed by our runners.
- **LLM/Evaluator settings:** `OPENAI_API_KEY`, `EVAL_MODEL`, and the knobs that control cadence/explanations.
- **Dify integration:** `DIFY_BASE_URL` and `DIFY_API_KEY` feed both the eval runner and experiment runner.

Keep these files out of Git and store them in a password vault.

## 2. Eval Runner Sidecar

Service definition: `docker-compose.yml` (local) and the generated compose in `deploy_phoenix_ec2.sh`.

- Image: same Phoenix image we build for the server.
- Entrypoint: `python -m scripts.evals.run_dify_rag_evals --loop`.
- Responsibilities:
  - Polls Phoenix for the latest traces from the Dify retrieval workflow.
  - Runs relevance & hallucination checks using the configured `EVAL_MODEL`.
  - Writes scores back to Phoenix so the UI shows objective quality metrics over time.
- Important env vars:
  - `PHOENIX_PROJECT`, `PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_API_KEY` so it can fetch traces and write results.
  - `EVAL_WINDOW_MINUTES`, `EVAL_INTERVAL_SECONDS` control the cadence.
  - `EVAL_SKIP_QA`, `EVAL_EXPLAIN` toggle additional evaluators.

To run locally: `docker compose up eval-runner`. It will stay alive as long as Phoenix is healthy.

## 3. Experiment Runner

Script: `scripts/experiments/run_experiment_docker.sh`.

Purpose: Trigger an on-demand experiment run from your shell, either locally or on an EC2 host.

What it does (operators make this available; analysts follow the user how-to guide for day-to-day usage):

1. Ensures the Phoenix service is up (`docker compose up -d phoenix` if necessary).
2. Executes `docker compose run --rm experiment-runner` with the arguments you pass.
3. The container launches `python -m scripts.experiments.run_dify_experiment` which:
   - Pulls a Dify dataset (`DATASET_NAME`) via `DIFY_API_KEY`.
   - Executes the workflow, logging messages and traces to Phoenix (`PHOENIX_BASE_URL`, `PHOENIX_API_KEY`).
   - Optionally limits the run (`--dry-run`) or skips QA scoring.

Common flags:

- `--dataset <name>`: Dify dataset to use (`DATASET_NAME` env default is `phoenix-dataset`).
- `--dry-run [N]`: limit to N examples for smoke-tests.
- `--skip-qa`, `--explain`: opt-in/opt-out of extra evaluators.
- `--host-network`: needed if Dify runs on `localhost` outside Docker.

Remote usage: the deploy script copies this helper to `/opt/phoenix/scripts/experiments/run_experiment_docker.sh` on the EC2 instance. SSH in, ensure you re-login so you’re in the `docker` group, then invoke the script just like you would locally (or provide these instructions to analysts once the host is ready).

## 4. EC2 Deployment Workflow

Script: `scripts/deploy/deploy_phoenix_ec2.sh`.

### 4.1 Prerequisites

- AWS CLI configured with permission to create/use ECR and SSH access to the EC2 host.
- EC2 instance running a modern Debian/Ubuntu/RHEL/Amazon Linux derivative.
- The secrets file populated (see Section 1).

### 4.2 Running the Deploy Script

Example:

```bash
./scripts/deploy/deploy_phoenix_ec2.sh \
  --aws-region=us-west-2 \
  --aws-account-id=123456789012 \
  --ec2-host=ubuntu@ec2-xx-yy-zz.us-west-2.compute.amazonaws.com \
  --env-file=deploy/phoenix.ec2.env
```

Optional flags include `--image-tag` (override tag), `--ecr-repo` (default `phoenix`), `--remote-dir` (default `/opt/phoenix`).

### 4.3 What the Script Does

1. Builds the Phoenix Docker image locally and pushes it to ECR.
2. Bootstraps the EC2 host:
   - Installs Docker & curl if missing; enables the service and adds the user to the `docker` group.
   - Installs the Docker Compose CLI plugin.
3. Uploads the environment file, a generated `docker-compose.yml` (Phoenix, Postgres, eval runner, experiment runner), and the experiment helper script.
4. Logs the host into ECR, pulls the latest image, and runs `docker compose up -d`.

### 4.4 Post-Deploy Steps

- Reconnect to the EC2 machine (new SSH session required for Docker group membership).
- Visit `http://<public-ip>:6006`, log in with the seeded admin credentials, and change the password immediately.
- Mint a system API key for production ingestion.
- Adjust security groups / load balancer rules to restrict access to port 6006.

### 4.5 Ongoing Operations

- Redeploy with the same command whenever the code changes—provide `--image-tag` to roll back.
- Rotate secrets by editing the env file locally and re-running the deploy script (it re-syncs `.env`).
- Experiment execution and dataset uploads can be initiated on the EC2 box via the copied script or via Phoenix APIs using the shared env file.

## 5. Keeping Docs Organized

Custom documentation for our “InTheBox” deployment lives in `docs/inthebox/`. Add future guides or updates here so teammates can quickly spot the pieces that differ from upstream Phoenix.
