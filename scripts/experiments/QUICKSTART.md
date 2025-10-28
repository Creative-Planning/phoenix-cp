# Experiment Runner - Quick Start

## TL;DR

```bash
# From phoenix repo root
cd /home/acb/WSL2-Client-Work/InTheBox/phoenix

# Ensure phoenix is running
docker compose up -d phoenix

# Run a dry-run test (3 examples)
./scripts/experiments/run_experiment_docker.sh --dry-run

# Run full experiment
./scripts/experiments/run_experiment_docker.sh "baseline-v1"

# View results
open http://localhost:6006/datasets
```

## How It Works

```
┌─────────────┐
│   Phoenix   │  ← Stores experiment results
│ (container) │
└─────────────┘
       ↑
       │
┌──────────────────┐
│ experiment-runner│  ← Calls DIFY and runs evals
│   (container)    │
└──────────────────┘
       ↓
┌─────────────┐
│    DIFY     │  ← Your workflow on host
│   (host)    │
└─────────────┘
```

**Network Configuration:**
- Phoenix: `http://phoenix:6006` (Docker service name)
- DIFY: `http://host.docker.internal:7788` (via `extra_hosts` in docker-compose)

## Commands

### Using the Wrapper Script (Recommended)

```bash
# Basic run
./scripts/experiments/run_experiment_docker.sh "my-experiment-name"

# Dry run (test with 3 examples)
./scripts/experiments/run_experiment_docker.sh --dry-run

# With options
./scripts/experiments/run_experiment_docker.sh \
  --dataset "Good 2025-10-20T14:32:32.450Z" \
  --skip-qa \
  --verbose \
  "improved-v2"
```

### Using Docker Compose Directly

```bash
# Basic run
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "baseline-v1"

# Dry run
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --dry-run 3 \
  --verbose
```

## Common Options

| Flag | Description | Example |
|------|-------------|---------|
| `--dry-run N` | Test with N examples | `--dry-run 3` |
| `--verbose` | Show debug logs | `--verbose` |
| `--skip-qa` | Skip Q&A evaluator (faster) | `--skip-qa` |
| `--explain` | Get evaluator explanations | `--explain` |
| `--dataset NAME` | Use specific dataset | `--dataset "My Dataset"` |

## Troubleshooting

### Can't reach DIFY

```bash
# Test DIFY connectivity from container
docker compose run --rm experiment-runner \
  python -c "import httpx; print(httpx.get('http://host.docker.internal:7788/health', timeout=5))"
```

**If that fails:**
1. Check DIFY is running: `curl http://localhost:7788/health`
2. Verify `.env` has `DIFY_BASE_URL=http://host.docker.internal:7788`
3. Check `docker-compose.yml` has `extra_hosts: - "host.docker.internal:host-gateway"`

### Phoenix not ready

```bash
# Check phoenix status
docker compose ps phoenix

# View logs
docker compose logs phoenix

# Restart if needed
docker compose restart phoenix
```

### Dataset not found

```bash
# List available datasets
docker compose run --rm experiment-runner \
  python -c "from phoenix.client import Client; [print(d.name) for d in Client().datasets.list_datasets()]"
```

## File Locations

```
phoenix/
├── docker-compose.yml              # Service definitions
├── .env                            # Environment variables
├── scripts/experiments/
│   ├── run_dify_experiment.py      # Main experiment script
│   ├── run_experiment_docker.sh    # Docker wrapper (use this!)
│   ├── QUICKSTART.md               # This file
│   └── README.md                   # Full documentation
└── docs/creative-planning/
    ├── experiments-docker.md       # Detailed Docker guide
    ├── experiments-guide.md        # Comprehensive workflow tutorial
    └── dify-api-reference.md       # DIFY API documentation
```

## Next Steps

1. **Create a dataset** from Phoenix UI traces
2. **Run baseline experiment**: `./scripts/experiments/run_experiment_docker.sh "baseline"`
3. **Make DIFY changes**: Adjust retrieval, prompts, etc.
4. **Run new experiment**: `./scripts/experiments/run_experiment_docker.sh "improved-v2"`
5. **Compare in Phoenix UI**: http://localhost:6006/datasets

## Full Documentation

- [Experiments Guide](../../docs/creative-planning/experiments-guide.md)
- [Docker-Specific Guide](../../docs/creative-planning/experiments-docker.md)
- [Experiment Script README](./README.md)
- [Deployment Guide](../../docs/creative-planning/deployment.md)
