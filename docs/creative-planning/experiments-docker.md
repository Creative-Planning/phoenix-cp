# Running Experiments with Docker Compose

This guide explains how to run Phoenix experiments using the `experiment-runner` Docker service.

## Architecture

The `experiment-runner` is a sidecar container that runs on-demand to execute experiments against your DIFY workflow:

```
┌─────────────────────┐
│   phoenix           │  ← Main Phoenix service
│   (port 6006)       │
└─────────────────────┘
          ↑
          │ Stores experiment results
          │
┌─────────────────────┐
│ experiment-runner   │  ← On-demand service (manual profile)
│ (same Dockerfile)   │     Runs when you invoke it
└─────────────────────┘
          ↓
     Calls DIFY API
          ↓
┌─────────────────────┐
│   DIFY              │  ← Your workflow (separate deployment)
│   (port 7788)       │
└─────────────────────┘
```

**Key differences from `eval-runner`:**
- **eval-runner**: Runs continuously with `--loop`, evaluates existing traces
- **experiment-runner**: Runs on-demand, executes new queries through DIFY and evaluates results

## Prerequisites

1. **Phoenix is running**: `docker compose up -d phoenix`
2. **DIFY is accessible**: Your DIFY workflow is running and reachable
3. **Dataset exists**: You've created a dataset in Phoenix (e.g., from traces)
4. **Environment variables set**: Check your `.env` file

## Environment Variables

Your `.env` file should contain:

```bash
# Required for experiments
DIFY_API_KEY=app-xxxxxxxxxxxxx          # Your DIFY API key
DIFY_BASE_URL=http://localhost:7788     # DIFY API endpoint
OPENAI_API_KEY=sk-xxxxxxxxxxxxx         # For LLM evaluators
EVAL_MODEL=gpt-4o                       # Model to use as judge

# Phoenix connection (set automatically in docker-compose)
# PHOENIX_BASE_URL=http://phoenix:6006  # This is set in docker-compose.yml
```

### Important: DIFY_BASE_URL for Docker

**If DIFY is running on your host machine** (not in Docker Compose), you need to adjust the URL:

```bash
# For Linux (using host network mode)
DIFY_BASE_URL=http://localhost:7788

# For Mac/Windows (use host.docker.internal)
DIFY_BASE_URL=http://host.docker.internal:7788
```

**If DIFY is in the same Docker Compose network**, use the service name:

```bash
DIFY_BASE_URL=http://dify:7788
```

## Usage

### 1. Basic Experiment Run

```bash
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "baseline-v1"
```

**Breakdown:**
- `docker compose run --rm` - Run the service and remove container after completion
- `experiment-runner` - The service name from docker-compose.yml
- `-m scripts.experiments.run_dify_experiment` - Override the default command
- `--dataset-name` - The Phoenix dataset to use
- `--experiment-name` - Name for this experiment run

### 2. Dry Run (Test with 3 Examples)

```bash
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "test-v1" \
  --dry-run 3 \
  --verbose
```

### 3. Skip Q&A Evaluator (Faster)

```bash
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "quick-test" \
  --skip-qa
```

### 4. Get Evaluator Explanations

```bash
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "detailed-test" \
  --explain
```

**Note:** This is slower and costs more tokens, but provides detailed reasoning from evaluators.

## Common Commands

### List Available Datasets

First, you need to access the Phoenix container or use the Python client:

```bash
docker compose run --rm experiment-runner \
  python -c "from phoenix.client import Client; c = Client(); [print(f'{d.name} ({len(d)} examples)') for d in c.datasets.list_datasets()]"
```

### View Help

```bash
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --help
```

### Check Service Status

```bash
# Ensure phoenix is healthy
docker compose ps phoenix

# View phoenix logs
docker compose logs phoenix

# View last experiment run logs
docker compose logs experiment-runner
```

## Workflow: Iterative Development

### Step 1: Run Baseline

```bash
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "baseline-v1"
```

### Step 2: Make Changes to DIFY

- Adjust retrieval settings (top-k, score threshold)
- Modify LLM prompts
- Update knowledge base
- Change model parameters

### Step 3: Run New Experiment

```bash
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "improved-retrieval-v2"
```

### Step 4: Compare in Phoenix UI

1. Open http://localhost:6006/datasets
2. Click on your dataset
3. Go to **Experiments** tab
4. Compare evaluator scores side-by-side
5. See which changes improved quality

### Step 5: Iterate

Repeat steps 2-4 until you achieve your quality goals.

## Troubleshooting

### "Connection refused" to Phoenix

**Problem:** Experiment runner can't reach Phoenix

**Check:**
```bash
# Ensure phoenix is running and healthy
docker compose ps phoenix

# Check phoenix logs
docker compose logs phoenix | tail -20
```

**Solution:** Wait for phoenix to be healthy, or restart:
```bash
docker compose up -d phoenix
```

### "Connection refused" to DIFY

**Problem:** Experiment runner can't reach DIFY

**Diagnose:**
```bash
# Test from inside the container
docker compose run --rm experiment-runner \
  python -c "import httpx; print(httpx.get('http://localhost:7788/health', timeout=5).status_code)"
```

**Solution:** Update `DIFY_BASE_URL` in `.env`:

```bash
# For Linux host mode
DIFY_BASE_URL=http://host.docker.internal:7788

# Or use --network host
docker compose run --rm --network host experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "test"
```

### "Dataset not found"

**Problem:** Dataset name doesn't exist in Phoenix

**List datasets:**
```bash
docker compose run --rm experiment-runner \
  python -c "from phoenix.client import Client; [print(d.name) for d in Client().datasets.list_datasets()]"
```

**Solution:** Use the exact name (case-sensitive) or create a new dataset.

### "DIFY_API_KEY environment variable is not set"

**Problem:** API key missing from `.env`

**Solution:** Add to `.env` file:
```bash
DIFY_API_KEY=app-your-api-key-here
```

Then restart the service to pick up new env vars:
```bash
docker compose down
docker compose up -d phoenix
```

### Python Module Import Errors

**Problem:** Can't find `scripts.experiments.run_dify_experiment`

**Check:** Ensure you're using `-m` (module) not direct path:

```bash
# ✅ Correct
-m scripts.experiments.run_dify_experiment

# ❌ Wrong
scripts/experiments/run_dify_experiment.py
```

**Rebuild if needed:**
```bash
docker compose build experiment-runner
```

## Advanced Usage

### Running with Custom Python Code

You can run arbitrary Python in the experiment-runner container:

```bash
docker compose run --rm experiment-runner \
  python -c "
from phoenix.client import Client
from phoenix.experiments import run_experiment

client = Client()
datasets = list(client.datasets.list_datasets())
print(f'Found {len(datasets)} datasets')
for d in datasets:
    print(f'  - {d.name}: {len(d)} examples')
"
```

### Custom Timeout

```bash
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "slow-workflow" \
  --timeout 120
```

### Using a Different Dataset

```bash
# First, list available datasets
docker compose run --rm experiment-runner \
  python -c "from phoenix.client import Client; [print(d.name) for d in Client().datasets.list_datasets()]"

# Then use the dataset name
docker compose run --rm experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "My Custom Dataset 2025-10-21" \
  --experiment-name "test-custom-data"
```

## Network Configuration Options

### Option 1: Default Bridge Network (Current Setup)

Services communicate via service names:
- `PHOENIX_BASE_URL=http://phoenix:6006` ✅ (set in docker-compose.yml)
- `DIFY_BASE_URL` needs special handling for host services

### Option 2: Host Network Mode

If DIFY is on the host, you can use host networking:

```bash
docker compose run --rm --network host experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "test" \
  --dify-base-url "http://localhost:7788"
```

**Note:** With `--network host`, you also need to override Phoenix URL:
```bash
docker compose run --rm --network host \
  -e PHOENIX_BASE_URL=http://localhost:6006 \
  experiment-runner \
  -m scripts.experiments.run_dify_experiment \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "test"
```

### Option 3: Add DIFY to Docker Compose

If you want everything in one network, add DIFY to `docker-compose.yml`:

```yaml
services:
  # ... existing services ...

  dify:
    image: your-dify-image
    ports:
      - "7788:80"
    # ... dify configuration ...
```

Then update `.env`:
```bash
DIFY_BASE_URL=http://dify:80
```

## Performance Considerations

### Experiment Runtime

Typical experiment with 15 examples:
- **Code evaluators**: Instant (< 1 second)
- **LLM evaluators**: ~2-5 seconds per example
- **Total time**: 1-2 minutes for 15 examples

With `--explain` flag:
- **Total time**: 3-5 minutes for 15 examples (more API calls)

### Cost Considerations

Using GPT-4o as evaluator (default):
- ~500-1000 tokens per evaluation
- 3 LLM evals per example (Hallucination, Relevance, Q&A)
- 15 examples = ~45 API calls
- **Estimated cost**: $0.10-0.30 per experiment run

Use `--skip-qa` to reduce to 2 evals per example and cut costs by ~33%.

## Best Practices

1. **Start with dry runs**: Always test with `--dry-run 3` first
2. **Use descriptive names**: Name experiments clearly: `improved-retrieval-v2`, not `test1`
3. **Track changes**: Document what changed between experiments
4. **Baseline first**: Run a baseline before making DIFY changes
5. **Compare in Phoenix**: Always view results in UI to spot patterns
6. **Skip Q&A when iterating**: Use `--skip-qa` for faster iteration, full eval for final tests

## See Also

- [Experiments Guide](./experiments-guide.md)
- [Experiment Script README](../../scripts/experiments/README.md)
- [DIFY API Documentation](./dify-api-reference.md)
- [Deployment Guide](./deployment.md)
- [Phoenix Experiments Docs](https://arize.com/docs/phoenix/datasets-and-experiments/)
