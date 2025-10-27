#!/usr/bin/env bash
set -euo pipefail

# This script builds the Phoenix Docker image, pushes it to ECR, and deploys it
# to an existing EC2 instance via Docker Compose. It assumes AWS credentials are
# configured locally and that you can SSH into the target instance.
#
# Required flags:
#   --aws-region=<region>
#   --aws-account-id=<account id>
#   --ec2-host=<user@ip-or-dns>
#   --env-file=<path to env file with Phoenix secrets>
#
# Optional flags:
#   --ecr-repo=<repo name>              (default: phoenix)
#   --image-tag=<tag>                   (default: git SHA or timestamp)
#   --ec2-port=<ssh port>               (default: 22)
#   --remote-dir=<remote deploy dir>    (default: /opt/phoenix)
#   --compose-version=<docker compose release> (default: v2.27.0)
#
# Example usage:
#   ./scripts/deploy/deploy_phoenix_ec2.sh \
#     --aws-region=us-west-2 \
#     --aws-account-id=123456789012 \
#     --ec2-host=ec2-user@1.2.3.4 \
#     --env-file=deploy/phoenix.ec2.env

usage() {
  cat <<'EOF'
Usage: deploy_phoenix_ec2.sh --aws-region=REGION --aws-account-id=ACCOUNT \
       --ec2-host=USER@HOST --env-file=/path/to/env [options]

Required flags:
  --aws-region         AWS region for ECR and EC2 (e.g. us-west-2)
  --aws-account-id     AWS account ID that owns the ECR repository
  --ec2-host           SSH target in user@host form
  --env-file           Local env file with Phoenix settings (not committed)

Optional flags:
  --ecr-repo           ECR repository name (default: phoenix)
  --image-tag          Image tag to push (default: git SHA or timestamp)
  --ec2-port           SSH port for the EC2 host (default: 22)
  --remote-dir         Remote directory for deployment (default: /opt/phoenix)
  --compose-version    Docker Compose plugin version (default: v2.27.0)
EOF
}

AWS_REGION=""
AWS_ACCOUNT_ID=""
ECR_REPO_NAME="phoenix"
IMAGE_TAG=""
EC2_SSH_HOST=""
EC2_SSH_PORT="22"
REMOTE_DIR="/opt/phoenix"
ENV_FILE=""
COMPOSE_VERSION="v2.27.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

for arg in "$@"; do
  case "$arg" in
    --aws-region=*) AWS_REGION="${arg#*=}" ;;
    --aws-account-id=*) AWS_ACCOUNT_ID="${arg#*=}" ;;
    --ecr-repo=*) ECR_REPO_NAME="${arg#*=}" ;;
    --image-tag=*) IMAGE_TAG="${arg#*=}" ;;
    --ec2-host=*) EC2_SSH_HOST="${arg#*=}" ;;
    --ec2-port=*) EC2_SSH_PORT="${arg#*=}" ;;
    --remote-dir=*) REMOTE_DIR="${arg#*=}" ;;
    --env-file=*) ENV_FILE="${arg#*=}" ;;
    --compose-version=*) COMPOSE_VERSION="${arg#*=}" ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$AWS_REGION" || -z "$AWS_ACCOUNT_ID" || -z "$EC2_SSH_HOST" || -z "$ENV_FILE" ]]; then
  echo "Missing required arguments." >&2
  usage
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file '$ENV_FILE' not found." >&2
  exit 1
fi

if [[ -z "$IMAGE_TAG" ]]; then
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    IMAGE_TAG="$(git rev-parse --short HEAD)"
  else
    IMAGE_TAG="$(date +%Y%m%d%H%M%S)"
  fi
fi

for dep in aws docker ssh scp; do
  if ! command -v "$dep" >/dev/null 2>&1; then
    echo "Required command '$dep' not found in PATH." >&2
    exit 1
  fi
done

AWS_ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_IMAGE_URI="${AWS_ECR_REGISTRY}/${ECR_REPO_NAME}:${IMAGE_TAG}"

echo ">>> Ensuring ECR repository ${ECR_REPO_NAME} exists in ${AWS_REGION}"
if ! aws ecr describe-repositories --region "$AWS_REGION" --repository-names "$ECR_REPO_NAME" >/dev/null 2>&1; then
  aws ecr create-repository --region "$AWS_REGION" --repository-name "$ECR_REPO_NAME" >/dev/null
  echo "Created repository ${ECR_REPO_NAME}"
fi

echo ">>> Building Phoenix image ${ECR_IMAGE_URI}"
docker build -t "$ECR_IMAGE_URI" .

echo ">>> Logging into ECR locally"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ECR_REGISTRY"

echo ">>> Pushing image ${ECR_IMAGE_URI}"
docker push "$ECR_IMAGE_URI"

echo ">>> Bootstrapping remote host ${EC2_SSH_HOST}"
ssh -p "$EC2_SSH_PORT" "$EC2_SSH_HOST" "REMOTE_DIR='$REMOTE_DIR' COMPOSE_VERSION='$COMPOSE_VERSION' bash -s" <<'EOF'
set -euo pipefail

ensure_pkg_mgr() {
  if command -v apt-get >/dev/null 2>&1; then
    PKG_MGR="apt-get"
  elif command -v dnf >/dev/null 2>&1; then
    PKG_MGR="dnf"
  elif command -v yum >/dev/null 2>&1; then
    PKG_MGR="yum"
  else
    PKG_MGR=""
  fi
}

install_packages() {
  local packages=("$@")
  ensure_pkg_mgr
  if [[ -z "$PKG_MGR" ]]; then
    echo "No supported package manager detected. Install packages manually: ${packages[*]}" >&2
    exit 1
  fi
  case "$PKG_MGR" in
    apt-get)
      sudo apt-get update -y
      sudo apt-get install -y "${packages[@]}"
      ;;
    dnf|yum)
      sudo "$PKG_MGR" install -y "${packages[@]}"
      ;;
  esac
}

if ! command -v docker >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    install_packages docker.io curl openssl
  else
    install_packages docker curl openssl
  fi
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$(id -un)" || true
fi

if ! command -v curl >/dev/null 2>&1; then
  install_packages curl
fi

if ! command -v openssl >/dev/null 2>&1; then
  install_packages openssl
fi

if ! docker compose version >/dev/null 2>&1; then
  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  sudo curl -sSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

sudo mkdir -p "$REMOTE_DIR"
sudo chown "$(id -un):$(id -gn)" "$REMOTE_DIR"
EOF

tmp_compose="$(mktemp)"
tmp_nginx_conf="$(mktemp)"
cleanup() {
  rm -f "$tmp_compose" "$tmp_nginx_conf"
}
trap cleanup EXIT

cat >"$tmp_compose" <<EOF
services:
  nginx:
    image: nginx:alpine
    restart: unless-stopped
    depends_on:
      - phoenix
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
  phoenix:
    image: ${ECR_IMAGE_URI}
    restart: unless-stopped
    depends_on:
      - db
    env_file:
      - .env
    environment:
      PHOENIX_SQL_DATABASE_URL: postgresql://\${POSTGRES_USER}:\${POSTGRES_PASSWORD}@db:5432/\${POSTGRES_DB}
    ports:
      - "6006:6006"
      - "4317:4317"
  eval-runner:
    image: ${ECR_IMAGE_URI}
    restart: unless-stopped
    depends_on:
      phoenix:
        condition: service_started
    env_file:
      - .env
    environment:
      PHOENIX_PROJECT: \${PHOENIX_PROJECT}
      EVAL_WINDOW_MINUTES: \${EVAL_WINDOW_MINUTES}
      EVAL_INTERVAL_SECONDS: \${EVAL_INTERVAL_SECONDS}
      EVAL_MODEL: \${EVAL_MODEL}
      EVAL_SKIP_QA: \${EVAL_SKIP_QA}
      EVAL_EXPLAIN: \${EVAL_EXPLAIN}
      OPENAI_API_KEY: \${OPENAI_API_KEY}
      PHOENIX_API_KEY: \${PHOENIX_API_KEY}
      PHOENIX_COLLECTOR_ENDPOINT: \${PHOENIX_COLLECTOR_ENDPOINT}
    command:
      - -m
      - scripts.evals.run_dify_rag_evals
      - --loop
  experiment-runner:
    image: ${ECR_IMAGE_URI}
    depends_on:
      phoenix:
        condition: service_started
    profiles:
      - manual
    env_file:
      - .env
    environment:
      PHOENIX_BASE_URL: http://phoenix:6006
      DIFY_BASE_URL: \${DIFY_BASE_URL}
      DIFY_API_KEY: \${DIFY_API_KEY}
      OPENAI_API_KEY: \${OPENAI_API_KEY}
      EVAL_MODEL: \${EVAL_MODEL}
    command:
      - -m
      - scripts.experiments.run_dify_experiment
      - --help
  db:
    image: postgres:16
    restart: unless-stopped
    env_file:
      - .env
    environment:
      POSTGRES_USER: \${POSTGRES_USER}
      POSTGRES_PASSWORD: \${POSTGRES_PASSWORD}
      POSTGRES_DB: \${POSTGRES_DB}
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - db-data:/var/lib/postgresql/data
volumes:
  db-data:
EOF

cat >"$tmp_nginx_conf" <<'NGINX_EOF'
events {
    worker_connections 1024;
}

http {
    upstream phoenix {
        server phoenix:6006;
    }

    # Redirect HTTP to HTTPS
    server {
        listen 80;
        server_name _;
        return 301 https://$host$request_uri;
    }

    # HTTPS server
    server {
        listen 443 ssl;
        server_name _;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        client_max_body_size 100M;

        location / {
            proxy_pass http://phoenix;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_read_timeout 86400;
        }
    }
}
NGINX_EOF

echo ">>> Copying docker-compose.yml, nginx.conf, and env file to remote host"
scp -P "$EC2_SSH_PORT" "$tmp_compose" "${EC2_SSH_HOST}:${REMOTE_DIR}/docker-compose.yml"
scp -P "$EC2_SSH_PORT" "$tmp_nginx_conf" "${EC2_SSH_HOST}:${REMOTE_DIR}/nginx.conf"
scp -P "$EC2_SSH_PORT" "$ENV_FILE" "${EC2_SSH_HOST}:${REMOTE_DIR}/.env"

echo ">>> Syncing experiment helper scripts"
ssh -p "$EC2_SSH_PORT" "$EC2_SSH_HOST" "mkdir -p '${REMOTE_DIR}/scripts/experiments'"
scp -P "$EC2_SSH_PORT" "$REPO_ROOT/scripts/experiments/run_experiment_docker.sh" "${EC2_SSH_HOST}:${REMOTE_DIR}/scripts/experiments/run_experiment_docker.sh"
ssh -p "$EC2_SSH_PORT" "$EC2_SSH_HOST" "chmod +x '${REMOTE_DIR}/scripts/experiments/run_experiment_docker.sh'"

echo ">>> Generating self-signed SSL certificate on remote host"
ssh -p "$EC2_SSH_PORT" "$EC2_SSH_HOST" "REMOTE_DIR='$REMOTE_DIR' bash -s" <<'EOF'
set -euo pipefail
mkdir -p "$REMOTE_DIR/ssl"
if [[ ! -f "$REMOTE_DIR/ssl/cert.pem" ]] || [[ ! -f "$REMOTE_DIR/ssl/key.pem" ]]; then
  echo "Generating new self-signed certificate (valid for 365 days)..."
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$REMOTE_DIR/ssl/key.pem" \
    -out "$REMOTE_DIR/ssl/cert.pem" \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=phoenix.local" \
    2>/dev/null
  echo "Certificate generated successfully"
else
  echo "Existing SSL certificate found, reusing"
fi
EOF

echo ">>> Logging into ECR from remote host"
aws ecr get-login-password --region "$AWS_REGION" \
  | ssh -p "$EC2_SSH_PORT" "$EC2_SSH_HOST" "sudo docker login --username AWS --password-stdin ${AWS_ECR_REGISTRY}"

echo ">>> Pulling and starting containers on remote host"
ssh -p "$EC2_SSH_PORT" "$EC2_SSH_HOST" "REMOTE_DIR='$REMOTE_DIR' bash -s" <<'EOF'
set -euo pipefail
cd "$REMOTE_DIR"
sudo docker compose pull
sudo docker compose up -d
EOF

echo "Deployment complete."
echo ""
echo "Phoenix is now accessible via HTTPS with a self-signed certificate."
echo ""
echo "UI Access (for end users):"
echo "  https://<ec2-public-ip> or https://<ec2-dns-name>"
echo ""
echo "API/Trace Ingestion (for DIFY and other applications):"
echo "  HTTP endpoint: http://<ec2-public-ip>:6006"
echo "  OTLP/gRPC endpoint: http://<ec2-public-ip>:4317"
echo ""
echo "Note: Your browser will show a security warning for HTTPS because the certificate is self-signed."
echo "      This is expected. Click 'Advanced' and 'Proceed' to access the application."
echo ""
echo "Security group requirements:"
echo "  - Port 443 (HTTPS) - for web UI access"
echo "  - Port 80 (HTTP) - automatically redirects to HTTPS"
echo "  - Port 6006 (HTTP) - for Phoenix API and trace ingestion (DIFY uses this)"
echo "  - Port 4317 (gRPC) - for OTLP trace ingestion"
echo "  - Port 22 (SSH) - for deployment and management"
