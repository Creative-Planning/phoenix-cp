# DIFY Workflow Experiments

This directory contains scripts for running Phoenix experiments on your DIFY AI workflow to evaluate and track performance improvements over time.

## Overview

The experiment workflow:

1. **Loads a dataset** of test prompts/questions from Phoenix
2. **Runs each prompt** through your DIFY workflow via API
3. **Evaluates the responses** using multiple evaluators:
   - **Code Evaluators** (basic checks):
     - `has_answer`: Did the workflow return a non-empty response?
     - `no_error`: Did the API call succeed?
     - `has_retrieval`: Were documents retrieved from the knowledge base?
     - `retrieval_count`: How many documents were retrieved?
   - **LLM Evaluators** (quality assessment):
     - `Hallucination`: Does the response contradict the retrieved documents?
     - `Relevance`: Are the retrieved documents relevant to the query?
     - `Q&A Correctness`: Is the answer correct? (requires expected answers in dataset)

4. **Logs everything to Phoenix** so you can compare experiments side-by-side in the UI

## Setup

### 1. Install Dependencies

```bash
# Create a virtual environment if needed
cd /home/acb/venv-dirs/arize-phoenix/
python3.11 -m venv venv
source venv/bin/activate

# Install required packages
pip install arize-phoenix-client arize-phoenix-otel openinference-instrumentation-openai openai httpx pandas
```

### 2. Set Environment Variables

```bash
# DIFY API Configuration
export DIFY_BASE_URL="http://localhost/v1"
export DIFY_API_KEY="your-dify-api-key-here"

# Phoenix Configuration (if not using defaults)
export PHOENIX_BASE_URL="http://localhost:6006"

# Evaluation Model (optional, defaults to gpt-4o)
export EVAL_MODEL="gpt-4o"

# OpenAI API Key (for evaluators)
export OPENAI_API_KEY="your-openai-api-key"
```

### 3. Get Your DIFY API Key

1. Go to your DIFY instance at `http://localhost`
2. Navigate to your workflow/app
3. Go to **API Access** or **Settings** → **API Keys**
4. Create or copy an API key
5. Set it in your environment: `export DIFY_API_KEY="app-xxxxx"`

## Usage

### Quick Start

Run an experiment using your existing dataset:

```bash
python scripts/experiments/run_dify_experiment.py \
  --dataset-name "Good 2025-10-20T14:32:32.450Z"
```

### Dry Run (Test First!)

Test with just 3 examples before running the full dataset:

```bash
python scripts/experiments/run_dify_experiment.py \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --dry-run 3 \
  --verbose
```

### Full Options

```bash
python scripts/experiments/run_dify_experiment.py \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "v2-improved-retrieval" \
  --dify-base-url "http://localhost/v1" \
  --dify-api-key "app-xxxxx" \
  --eval-model "gpt-4o" \
  --explain \
  --verbose
```

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--dataset-name` | Name of the Phoenix dataset to use | (required) |
| `--dataset-id` | Dataset ID (alternative to name) | - |
| `--experiment-name` | Custom name for this experiment | Auto-generated |
| `--dify-base-url` | DIFY API base URL | `http://localhost/v1` |
| `--dify-api-key` | DIFY API key | From `DIFY_API_KEY` env var |
| `--eval-model` | LLM model for evaluations | `gpt-4o` |
| `--skip-qa` | Skip Q&A correctness evaluator | `false` |
| `--explain` | Get explanations from evaluators | `false` |
| `--dry-run N` | Test with only N examples | Run all |
| `--timeout` | API call timeout in seconds | `60` |
| `--user-id` | User ID sent to DIFY | `experiment-user` |
| `--verbose` | Enable debug logging | `false` |

## Workflow: Iterative Improvement

### 1. Run Baseline Experiment

```bash
# First experiment with current workflow
python scripts/experiments/run_dify_experiment.py \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "baseline-v1"
```

### 2. Make Changes to DIFY Workflow

- Adjust retrieval settings
- Modify prompts
- Change model parameters
- Update knowledge base
- etc.

### 3. Run New Experiment

```bash
# Test the improved workflow
python scripts/experiments/run_dify_experiment.py \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --experiment-name "improved-retrieval-v2"
```

### 4. Compare in Phoenix UI

1. Go to `http://localhost:6006/datasets`
2. Click on your dataset
3. View the **Experiments** tab
4. Compare evaluator scores side-by-side
5. See which changes improved or degraded performance

## Creating New Datasets

You can create datasets in several ways:

### From Traces (Recommended)

1. Use your DIFY workflow normally
2. In Phoenix UI, view the traces
3. Select interesting/representative traces
4. Click "Add to Dataset"
5. Use that dataset for experiments

### From Code

```python
from phoenix.client import Client
import pandas as pd

client = Client()

# Create a DataFrame with test questions
df = pd.DataFrame({
    "question": [
        "What are the specs of the iPhone 13 Pro Max?",
        "Tell me about the latest iPhone features",
        "How does the camera compare to Samsung?",
    ]
})

# Upload to Phoenix
dataset = client.datasets.create_dataset(
    name="my-test-questions",
    dataframe=df,
    input_keys=["question"],
)

print(f"Created dataset: {dataset.name} (ID: {dataset.id})")
```

### From CSV

```python
from phoenix.client import Client
import pandas as pd

client = Client()

# Load from CSV
df = pd.read_csv("my_questions.csv")

dataset = client.datasets.create_dataset(
    name="questions-from-csv",
    dataframe=df,
    input_keys=["question"],
    # If you have expected answers:
    output_keys=["expected_answer"],
)
```

## Understanding Evaluators

### Code Evaluators (Fast, Simple)

These run instantly and check basic properties:

- **has_answer**: Ensures the workflow returned something
- **no_error**: Ensures the API call succeeded
- **has_retrieval**: Checks if documents were found
- **retrieval_count**: Counts retrieved documents

### LLM Evaluators (Slow, Deep)

These use GPT-4 to assess quality:

- **Hallucination**: Checks if the answer contradicts the retrieved documents
  - Score: 0 (hallucinated) or 1 (factual)
- **Relevance**: Checks if retrieved docs are relevant to the question
  - Score: 0 (not relevant) or 1 (relevant)
- **Q&A Correctness**: Checks if the answer is correct
  - Requires `expected` or `answer` field in dataset
  - Score: 0 (incorrect) or 1 (correct)

Use `--explain` to get detailed explanations, but note this increases cost and latency.

## Troubleshooting

### "Dataset not found"

```bash
# List all available datasets
python -c "from phoenix.client import Client; c = Client(); print([d.name for d in c.datasets.list_datasets()])"
```

### "DIFY API key is required"

Make sure you've set the environment variable:

```bash
export DIFY_API_KEY="app-xxxxx"
```

Or pass it directly:

```bash
python scripts/experiments/run_dify_experiment.py \
  --dataset-name "Good 2025-10-20T14:32:32.450Z" \
  --dify-api-key "app-xxxxx"
```

### "Connection refused" or timeout

Check that:
1. Phoenix is running: `http://localhost:6006`
2. DIFY is running: `http://localhost`
3. The base URLs are correct

### No retrieval documents in results

If your DIFY workflow isn't returning retrieved documents in the API response:
- Check that your workflow has a knowledge retrieval node
- Verify the retrieval node is properly configured
- Test the workflow directly in DIFY UI first

## Advanced: Custom Evaluators

You can add your own evaluators in `run_dify_experiment.py`:

```python
from phoenix.experiments.evaluators import create_evaluator

@create_evaluator(name="answer_length", kind="CODE")
def answer_length(output: dict) -> int:
    """Count characters in the answer."""
    return len(output.get("output", ""))

@create_evaluator(name="is_concise", kind="CODE")
def is_concise(output: dict) -> bool:
    """Check if answer is under 500 characters."""
    return len(output.get("output", "")) < 500

# Add to evaluators list
custom_evaluators = create_custom_evaluators() + [answer_length, is_concise]
```

## See Also

- [Experiments Guide](../../docs/creative-planning/experiments-guide.md)
- [Docker-Specific Guide](../../docs/creative-planning/experiments-docker.md)
- [DIFY API Reference](../../docs/creative-planning/dify-api-reference.md)
- [Phoenix Datasets Docs](https://arize.com/docs/phoenix/datasets-and-experiments/how-to-datasets/)
- [Phoenix Experiments Docs](https://arize.com/docs/phoenix/datasets-and-experiments/how-to-experiments/)
- [Phoenix Evaluators Docs](https://arize.com/docs/phoenix/evaluation/evals)
