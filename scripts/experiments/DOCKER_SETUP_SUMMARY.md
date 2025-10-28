# Docker Setup Summary - Experiment Runner

## What Changed

We've integrated the experiment runner into your Docker Compose setup, following the same pattern as your `eval-runner` sidecar.

## Files Modified

### 1. `docker-compose.yml`

**Added:** `experiment-runner` service

```yaml
experiment-runner:
  build:
    dockerfile: ./Dockerfile
    context: .
  depends_on:
    phoenix:
      condition: service_healthy
  env_file:
    - .env
  environment:
    - DIFY_BASE_URL=${DIFY_BASE_URL}
    - DIFY_API_KEY=${DIFY_API_KEY}
    - OPENAI_API_KEY=${OPENAI_API_KEY}
    - PHOENIX_BASE_URL=http://phoenix:6006
    - EVAL_MODEL=${EVAL_MODEL}
  extra_hosts:
    - "host.docker.internal:host-gateway"
  profiles:
    - manual
  command:
    - -m
    - scripts.experiments.run_dify_experiment
    - --help
```

**Key features:**
- Uses same `Dockerfile` as `phoenix` and `eval-runner`
- Waits for Phoenix to be healthy before running
- Uses `profiles: [manual]` so it doesn't auto-start
- Includes `extra_hosts` to access DIFY on host via `host.docker.internal`
- Invoked on-demand with `docker compose run`

### 2. `.env`

**Changed:** `DIFY_BASE_URL`

```bash
# Before
DIFY_BASE_URL=http://localhost:7788

# After
DIFY_BASE_URL=http://host.docker.internal:7788
```

**Why:** When running inside Docker containers, `localhost` refers to the container itself, not the host machine. Using `host.docker.internal` (enabled via `extra_hosts`) allows containers to reach services on the host.

## Files Created

### 3. `scripts/experiments/run_experiment_docker.sh` ⭐

**Purpose:** Convenience wrapper that simplifies running experiments

**Usage:**
```bash
./scripts/experiments/run_experiment_docker.sh "experiment-name"
./scripts/experiments/run_experiment_docker.sh --dry-run
./scripts/experiments/run_experiment_docker.sh --help
```

**Features:**
- Colored output
- Checks if Phoenix is running
- Smart defaults
- Option to use host network mode
- Helpful error messages

### 4. `scripts/experiments/QUICKSTART.md`

Quick reference card for common commands and troubleshooting.

### 5. `docs/creative-planning/experiments-docker.md`

Comprehensive guide covering:
- Architecture and networking
- All usage patterns
- Troubleshooting
- Performance considerations
- Best practices

## Architecture

### Before (What We Considered)

❌ Local venv approach:
- Requires Python setup on host
- Environment inconsistency across team members
- Doesn't match your Docker-first architecture

### After (What We Built) ✅

Containerized approach:
```
┌─────────────────────┐
│   phoenix           │  ← Main Phoenix service (port 6006)
│   (always running)  │
└─────────────────────┘
          ↑
          │ stores results
          │
┌─────────────────────┐
│ eval-runner         │  ← Continuous evaluator (--loop)
│ (always running)    │     Evaluates existing traces
└─────────────────────┘

┌─────────────────────┐
│ experiment-runner   │  ← On-demand experiment runner
│ (manual profile)    │     Runs new queries through DIFY
└─────────────────────┘
          ↓
          │ calls API
          ↓
┌─────────────────────┐
│   DIFY (host)       │  ← Your workflow (port 7788)
│   host.docker.      │     Accessible via host.docker.internal
│   internal:7788     │
└─────────────────────┘
```

## How to Use

### Quick Test (Dry Run)

```bash
cd /home/acb/WSL2-Client-Work/InTheBox/phoenix

# Ensure Phoenix is running
docker compose up -d phoenix

# Run dry-run with 3 examples
./scripts/experiments/run_experiment_docker.sh --dry-run
```

### Full Experiment

```bash
# Run experiment with all examples
./scripts/experiments/run_experiment_docker.sh "baseline-v1"

# View results
open http://localhost:6006/datasets
```

### Iterative Development Workflow

```bash
# 1. Run baseline
./scripts/experiments/run_experiment_docker.sh "baseline"

# 2. Make changes to DIFY workflow
#    (adjust retrieval, modify prompts, etc.)

# 3. Run new experiment
./scripts/experiments/run_experiment_docker.sh "improved-retrieval-v2"

# 4. Compare in Phoenix UI
#    http://localhost:6006/datasets → Experiments tab

# 5. Repeat steps 2-4 until quality improves
```

## Network Configuration Explained

### Why `host.docker.internal`?

**Problem:** Docker containers have their own network namespace
- `localhost` inside a container ≠ `localhost` on the host
- DIFY runs on host at `localhost:7788`
- `experiment-runner` container can't reach it via `localhost:7788`

**Solution:** Use `host.docker.internal`
- Added `extra_hosts: - "host.docker.internal:host-gateway"` in docker-compose.yml
- Maps `host.docker.internal` to the host's IP
- Containers can now reach host services via `host.docker.internal:7788`

**Alternative solutions we considered:**
1. ❌ `--network host` - Works but loses container isolation
2. ❌ Move DIFY into docker-compose - More complex, changes your setup
3. ✅ `extra_hosts` - Clean, standard Docker practice

## Comparison: eval-runner vs. experiment-runner

| Feature | eval-runner | experiment-runner |
|---------|-------------|-------------------|
| **Purpose** | Evaluate existing traces | Run new queries and evaluate |
| **Mode** | Continuous (`--loop`) | On-demand |
| **Auto-start** | Yes (always running) | No (`profiles: manual`) |
| **Input** | Phoenix traces | Phoenix datasets |
| **Output** | Evaluations logged to Phoenix | Experiments logged to Phoenix |
| **When to use** | Ongoing quality monitoring | Testing workflow changes |
| **Invocation** | `docker compose up` | `docker compose run` |

## Environment Variables Reference

| Variable | Purpose | Default/Example |
|----------|---------|-----------------|
| `DIFY_BASE_URL` | DIFY API endpoint | `http://host.docker.internal:7788` |
| `DIFY_API_KEY` | DIFY auth | `app-xxxxx` |
| `OPENAI_API_KEY` | LLM evaluator auth | `sk-xxxxx` |
| `EVAL_MODEL` | Evaluator model | `gpt-4o` |
| `PHOENIX_BASE_URL` | Phoenix endpoint | `http://phoenix:6006` (set in compose) |

## Troubleshooting

### "Connection refused" to DIFY

**Diagnose:**
```bash
# Test from inside container
docker compose run --rm experiment-runner \
  python -c "import httpx; print(httpx.get('http://host.docker.internal:7788/health'))"
```

**Fix:**
1. Verify DIFY is running: `curl http://localhost:7788/health`
2. Check `.env` has `DIFY_BASE_URL=http://host.docker.internal:7788`
3. Verify `docker-compose.yml` has `extra_hosts` configuration

### "Dataset not found"

**List datasets:**
```bash
docker compose run --rm experiment-runner \
  python -c "from phoenix.client import Client; [print(d.name) for d in Client().datasets.list_datasets()]"
```

### Phoenix not ready

```bash
# Check status
docker compose ps phoenix

# View logs
docker compose logs phoenix

# Restart
docker compose restart phoenix
```

## Next Steps

1. **Test the setup:**
   ```bash
   ./scripts/experiments/run_experiment_docker.sh --dry-run
   ```

2. **Run your first full experiment:**
   ```bash
   ./scripts/experiments/run_experiment_docker.sh "baseline-v1"
   ```

3. **Make DIFY changes and compare:**
   ```bash
   # After modifying DIFY workflow
   ./scripts/experiments/run_experiment_docker.sh "improved-v2"
   ```

4. **Review results in Phoenix UI:**
   - Open http://localhost:6006/datasets
   - Click your dataset
   - Compare experiments side-by-side

## Documentation

- **Quick Start:** `scripts/experiments/QUICKSTART.md`
- **Experiments Guide:** `docs/creative-planning/experiments-guide.md`
- **Docker Guide:** `docs/creative-planning/experiments-docker.md`
- **Deployment Guide:** `docs/creative-planning/deployment.md`
- **Script README:** `scripts/experiments/README.md`

## Benefits of This Approach

✅ **Consistent with your architecture:** Follows same pattern as `eval-runner`
✅ **No local setup needed:** Everything runs in containers
✅ **Team-friendly:** Same experience for all developers
✅ **Production-ready:** Same image/config for dev and prod
✅ **Simple invocation:** One command to run experiments
✅ **Network isolation handled:** `extra_hosts` makes DIFY accessible
