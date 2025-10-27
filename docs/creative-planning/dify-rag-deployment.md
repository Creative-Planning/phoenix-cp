# Dify RAG Evaluation & Deployment Playbook

> Audience: Platform/DevOps engineers responsible for running Phoenix + Dify infrastructure. For analyst-facing experiment instructions, point stakeholders to `docs/creative-planning/how-to-guide.md`.

This guide documents the pieces we’ve added on top of upstream Phoenix so the team can run evaluations and deploy the stack on EC2 in a consistent way.

## 1. Environment Configuration

All local Docker Compose runs and EC2 deployments share the same environment file schema. Start by copying `deploy/env/phoenix.env.example` to a secrets file (e.g. `.env` for local usage and `deploy/phoenix.ec2.env` for production) and fill in every placeholder.

> The deploy script now enforces `chmod 600` on the remote `.env` so only the deploying user can read it. Keep the file permissions equally strict on your laptop (or store the values in a secrets vault) to prevent accidental disclosure.
>
> Leave `PHOENIX_API_KEY` set to `replace-with-phoenix-api-key` (or blank) if you want the deployment script to mint a fresh system API key automatically. The script will log in with the seeded admin account, create the key, and replace the placeholder in `/opt/phoenix/.env`.

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

- **Local machine:** AWS CLI configured with permission to describe/create ECR repos, push images, and start SSM/EC2 actions; Docker CLI able to build the Phoenix image; SSH key with access to the target instance.
- **EC2 baseline:** Launch Ubuntu 22.04 LTS or Amazon Linux 2023 (recommend `t3.large` or `t3a.large`, 2 vCPU / 8 GB RAM minimum) with a 40–60 GB gp3 volume. Update packages (`sudo apt-get update && sudo apt-get upgrade -y` or equivalent) and ensure the user you deploy with has passwordless sudo. The script can install Docker/Compose, but outbound HTTPS (ports 443/80) must be allowed so it can download packages.
- **IAM:** Attach an instance profile that can pull from the Phoenix ECR repo and, if you later migrate secrets to AWS Secrets Manager or Parameter Store, grant `secretsmanager:GetSecretValue` / `ssm:GetParameter`.
- **Networking:** Create or reuse a security group that allows inbound 22/80/443/6006/4317 from your office/VPC ranges only. Allow all outbound traffic so the containers can reach OpenAI, Bedrock, or Dify endpoints. Optionally allocate an Elastic IP so DNS remains stable.
- **Secrets:** Populate the env file from Section 1. For production, plan to store the raw values in your secret manager and generate the `.env` during deployment; the simple approach keeps the file locally but the remote copy ends up at `/opt/phoenix/.env` with mode `600`.

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
4. Logs the host into ECR, pulls the latest image, and starts the Phoenix service by itself so it can serve API requests.
5. If the env file contains the placeholder value for `PHOENIX_API_KEY`, the script waits for Phoenix to become healthy, logs in with the seeded admin credentials, creates a new system API key via GraphQL, and rewrites `/opt/phoenix/.env` with the generated key (file permissions stay `600`).
6. Finally, it runs `docker compose up -d` to start or recreate the remaining services (nginx proxy, eval runner, experiment runner) with the updated env vars.

### 4.4 Post-Deploy Steps

- Reconnect to the EC2 machine (new SSH session required for Docker group membership). Confirm the `.env` permissions with `ls -l /opt/phoenix/.env` (should read `-rw-------`).
- Visit `https://<public-ip>` or `https://<ec2-dns-name>`, accept the self-signed certificate warning in your browser, then log in with the seeded admin credentials and change the password immediately.
- The deployment script already minted a system API key if you left the placeholder in the env file; view or rotate it in the Phoenix UI under **Settings → API Keys** as needed, and sync any downstream consumers if you change it later.
- Adjust security groups to allow inbound traffic:
  - Port 443 (HTTPS) - for web UI access
  - Port 80 (HTTP) - automatically redirects to HTTPS
  - Port 6006 (HTTP) - for Phoenix API and trace ingestion (DIFY uses this)
  - Port 4317 (gRPC) - for OTLP trace ingestion (optional, DIFY uses HTTP)
  - Port 22 (SSH) - for deployment and management
- Optional hardening:
  - Scope inbound traffic to trusted CIDRs or front the host with an ALB + ACM certificate.
  - Enable automatic security updates (Ubuntu `unattended-upgrades`, Amazon Linux `dnf-automatic`).
  - Configure CloudWatch/CloudTrail or another log sink for Docker and system logs.

**Note on HTTPS:** The deployment uses a self-signed SSL certificate for UI access. Browsers will show a security warning on first access. Click "Advanced" and "Proceed" to accept the certificate. The certificate is valid for 365 days and persists across redeployments.

**Architecture Overview:**
```
End Users (Browser)
    |
    | HTTPS (port 443)
    v
┌─────────────────────┐
│  Nginx Reverse Proxy│
│  (self-signed cert) │
└─────────────────────┘
    |
    | HTTP
    v
┌─────────────────────┐      ┌──────────────────┐
│  Phoenix Container  │◄─────┤  PostgreSQL DB   │
│  - UI (port 6006)   │      └──────────────────┘
│  - API (/v1/traces) │
│  - OTLP (port 4317) │
└─────────────────────┘
    ^
    | HTTP (port 6006)
    |
DIFY (Trace Ingestion)
```

**Access Patterns:**
- **End users:** Access the Phoenix UI via `https://<ec2-ip>` (HTTPS through Nginx reverse proxy)
- **DIFY trace ingestion:** Configure DIFY to send traces to `http://<ec2-ip>:6006` with your Phoenix project name and API key
- The architecture provides both secure UI access and direct HTTP API access for trace ingestion

### 4.5 Configuring DIFY to Send Traces to EC2 Phoenix

Once Phoenix is deployed on EC2, configure your DIFY instance to send traces:

1. **In DIFY UI:** Navigate to your app → Settings → Tracing
2. **Select Phoenix/Arize as provider**
3. **Configure the endpoint:**
   - Endpoint: `http://<ec2-public-ip>:6006` (use the public IP or DNS name of your EC2 instance)
   - Project: Your Phoenix project name (e.g., `default`)
   - API Key: The Phoenix API key you generated in the Phoenix UI
4. **Test the connection** - DIFY will send a test span to verify connectivity
5. **Save the configuration**

DIFY uses the HTTP OTLP exporter and will send traces to `http://<ec2-ip>:6006/v1/traces`. The traces will appear in the Phoenix UI under the configured project name.

**Note:** DIFY sends traces via HTTP (not HTTPS), which is why port 6006 is exposed directly. This is standard for OpenTelemetry trace ingestion between internal services.

### 4.6 Ongoing Operations

- Redeploy with the same command whenever the code changes—provide `--image-tag` to roll back.
- Rotate secrets by editing the env file locally and re-running the deploy script (it re-syncs `.env`).
- For longer-lived environments, migrate the env variables to AWS Secrets Manager or SSM Parameter Store and modify the deploy script or a systemd unit to render `.env` from those sources during boot.
- Experiment execution and dataset uploads can be initiated on the EC2 box via the copied script or via Phoenix APIs using the shared env file.

## 5. Keeping Docs Organized

Custom documentation for our deployment lives in `docs/creative-planning/`. Add future guides or updates here so teammates can quickly spot the pieces that differ from upstream Phoenix.
