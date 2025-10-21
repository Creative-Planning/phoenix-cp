# Dataset Formats for DIFY Experiments

This document explains the two dataset formats supported by `run_dify_experiment.py` and which evaluators work with each.

## Overview

The experiment runner supports two dataset formats, depending on whether you have "gold standard" expected answers or just test questions.

---

## Dataset Type 1: Input Only (Questions Only)

**Use case:** You have test questions but no expected answers. You want to evaluate retrieval quality and hallucination, but can't measure answer correctness.

### Dataset Structure

**Recommended CSV Format:**
```csv
question
"What is the capital of France?"
"Who wrote Romeo and Juliet?"
"What is photosynthesis?"
```

**Supported column names for questions:**
- `question` (recommended)
- `query`
- `input`

**Important:** The column name must match what you specify in `input_keys` when importing.

**When uploading to Phoenix:**
- **Input keys:** `["question"]` (use the exact column name from your CSV)
- **Output keys:** `[]` (leave empty - no expected answers)
- **Metadata keys:** `["metadata"]` (optional - any additional columns)

### Example Creation

```python
import pandas as pd
from phoenix.client import Client

client = Client()

df = pd.DataFrame({
    "question": [
        "What is the capital of France?",
        "Who wrote Romeo and Juliet?",
        "What is photosynthesis?"
    ]
})

dataset = client.datasets.create_dataset(
    name="test-questions-only",
    dataframe=df,
    input_keys=["question"],
    output_keys=[],  # No expected answers
)
```

### What Gets Evaluated

| Evaluator | Works? | Description |
|-----------|--------|-------------|
| **has_answer** | ✅ | Checks if DIFY returned a non-empty answer |
| **no_error** | ✅ | Checks if DIFY call succeeded without errors |
| **has_retrieval** | ✅ | Checks if documents were retrieved |
| **retrieval_count** | ✅ | Counts how many documents were retrieved |
| **hallucination** | ✅ | LLM checks if answer contradicts retrieved docs |
| **relevance** | ✅ | LLM checks if retrieved docs are relevant to question |
| **qa_correctness** | ❌ | Cannot evaluate - no expected answer to compare against |

### When to Use

- Early testing when you don't have gold answers yet
- Monitoring retrieval quality and hallucination
- Testing if workflow returns reasonable responses
- Comparing retrieval configurations (e.g., top_k=3 vs top_k=5)

---

## Dataset Type 2: Input + Expected Output (Questions + Gold Answers)

**Use case:** You have test questions AND expected/correct answers. You can evaluate retrieval quality, hallucination, AND answer correctness.

### Dataset Structure

**Recommended CSV Format:**
```csv
question,expected_answer
"What is the capital of France?","Paris"
"Who wrote Romeo and Juliet?","William Shakespeare"
"What is photosynthesis?","The process by which plants convert light energy into chemical energy"
```

**Supported column names:**
- **For questions:** `question` (recommended), `query`, or `input`
- **For expected answers:** `expected_answer` (recommended), `answer`, `expected`, or `output`

**Important:** Column names must match what you specify in `input_keys` and `output_keys` when importing.

**When uploading to Phoenix:**
- **Input keys:** `["question"]` (use the exact column name from your CSV)
- **Output keys:** `["expected_answer"]` (use the exact column name from your CSV)
- **Metadata keys:** `["metadata"]` or other columns (optional)

### Example Creation

```python
import pandas as pd
from phoenix.client import Client

client = Client()

df = pd.DataFrame({
    "question": [
        "What is the capital of France?",
        "Who wrote Romeo and Juliet?",
        "What is photosynthesis?"
    ],
    "expected_answer": [
        "Paris",
        "William Shakespeare",
        "The process by which plants convert light energy into chemical energy"
    ],
    "metadata": [
        {"topic": "geography"},
        {"topic": "literature"},
        {"topic": "biology"}
    ]
})

dataset = client.datasets.create_dataset(
    name="test-questions-with-answers",
    dataframe=df,
    input_keys=["question"],
    output_keys=["expected_answer"],
    metadata_keys=["metadata"],
)
```

### What Gets Evaluated

| Evaluator | Works? | Description |
|-----------|--------|-------------|
| **has_answer** | ✅ | Checks if DIFY returned a non-empty answer |
| **no_error** | ✅ | Checks if DIFY call succeeded without errors |
| **has_retrieval** | ✅ | Checks if documents were retrieved |
| **retrieval_count** | ✅ | Counts how many documents were retrieved |
| **hallucination** | ✅ | LLM checks if answer contradicts retrieved docs |
| **relevance** | ✅ | LLM checks if retrieved docs are relevant to question |
| **qa_correctness** | ✅ | LLM checks if DIFY answer matches expected answer |

### When to Use

- Comprehensive quality evaluation
- Comparing workflow changes to see if answer quality improves
- Regression testing to ensure changes don't break existing good answers
- Measuring improvement over time

---

## How the Experiment Works

### 1. Task Execution

For each example in the dataset, the experiment:

1. **Extracts the question** from the dataset's `input` field
2. **Calls DIFY** via the chat API with the question
3. **Returns a structured dict:**
   ```python
   {
       "output": "The answer from DIFY",
       "reference": "Retrieved doc 1\n\nRetrieved doc 2\n\nRetrieved doc 3",
       "metadata": {
           "conversation_id": "...",
           "message_id": "...",
           "retriever_count": 3,
           "usage": {...}
       },
       "error": None  # or error message if call failed
   }
   ```

### 2. Evaluation

The evaluators receive:
- `output`: The entire dict returned by the task (shown above)
- `input`: The dataset's input field (the question)
- `expected`: The dataset's output field (gold answer if present, empty dict if not)

**Custom evaluators** extract the relevant fields:
- **Code evaluators** check the dict structure (has_answer, no_error, etc.)
- **LLM evaluators** extract answer/docs and call Phoenix's legacy evaluators

### 3. Results Storage

All results are stored in Phoenix and visible in the UI:
- Compare experiments side-by-side
- See evaluation scores for each example
- View explanations from LLM evaluators
- Track improvements over time

---

## Running Experiments

### Basic Usage

```bash
# With Type 1 dataset (questions only)
./scripts/experiments/run_experiment_docker.sh \
  --dataset "test-questions-only" \
  --skip-qa \
  "baseline-v1"

# With Type 2 dataset (questions + expected answers)
./scripts/experiments/run_experiment_docker.sh \
  --dataset "test-questions-with-answers" \
  "baseline-v1"
```

### Comparing Experiments

```bash
# 1. Run baseline
./scripts/experiments/run_experiment_docker.sh "baseline"

# 2. Make changes to DIFY workflow
#    (adjust retrieval settings, modify prompts, etc.)

# 3. Run new experiment
./scripts/experiments/run_experiment_docker.sh "improved-retrieval-v2"

# 4. Compare in Phoenix UI
#    http://localhost:6006/datasets → Select dataset → Compare experiments
```

### Using the `--skip-qa` Flag

If your dataset has expected answers but you want to skip Q&A evaluation (faster/cheaper):

```bash
./scripts/experiments/run_experiment_docker.sh \
  --dataset "test-questions-with-answers" \
  --skip-qa \
  "quick-test"
```

---

## Example Workflow: Building a Dataset from Traces

You can create datasets from your existing DIFY traces in Phoenix:

1. **Go to Phoenix UI:** http://localhost:6006
2. **Navigate to Traces** for your project
3. **Select interesting examples** (good answers, edge cases, failures)
4. **Click "Add to Dataset"**
5. **Create or select a dataset**

For Type 1 (questions only):
- Select the question from the trace input
- Don't add the answer to the output

For Type 2 (questions + answers):
- Select the question from the trace input
- Manually add the correct/expected answer to the output field

---

## Tips and Best Practices

### Dataset Size

- **Dry run first:** `--dry-run 3` to test with 3 examples
- **Development:** 10-20 examples for quick iteration
- **Pre-production:** 50-100 examples for comprehensive testing
- **Regression suite:** 100+ examples covering edge cases

### Dataset Quality

- Include diverse topics from your knowledge base
- Add edge cases (ambiguous questions, multi-part questions)
- Include examples where you know the workflow struggles
- For Type 2, ensure expected answers are truly correct

### Iterative Improvement

1. Run experiment on baseline workflow
2. Review results in Phoenix UI - identify low scores
3. Adjust DIFY settings (retrieval, prompts, etc.)
4. Run new experiment with same dataset
5. Compare scores - did they improve?
6. Repeat until satisfactory

### Cost Management

- LLM evaluators call OpenAI for each example
- Use `--skip-qa` to reduce API calls
- Use `--dry-run N` during development
- Consider smaller datasets for frequent testing

---

## CSV Import Guide

### Quick Reference: Column Name Mapping

When you import a CSV, Phoenix maps columns to fields your code can access:

```python
# If your CSV has:
# question,expected_answer
# "What is...?","The answer is..."

# And you import with:
client.datasets.create_dataset(
    csv_file_path="data.csv",
    input_keys=["question"],
    output_keys=["expected_answer"]
)

# Your task function receives:
def task(input):
    question = input["question"]  # ← Must match input_keys
    # ...

# Your evaluators receive:
def evaluator(input, output, expected):
    question = input["question"]           # ← From input_keys
    gold_answer = expected["expected_answer"]  # ← From output_keys
    # ...
```

### Converting Existing CSVs

**Your current GBA FAQ CSV:**
```
question_id,input,reference
1,"How do I...?","The answer is..."
```

**Option 1 (Recommended): Rename headers**
```
question_id,question,expected_answer
1,"How do I...?","The answer is..."
```

Then import:
```python
dataset = client.datasets.create_dataset(
    csv_file_path="gba_faq.csv",
    input_keys=["question"],
    output_keys=["expected_answer"],
    metadata_keys=["question_id"]
)
```

**Option 2: Use existing column names**

Keep CSV as-is and import with:
```python
dataset = client.datasets.create_dataset(
    csv_file_path="gba_faq.csv",
    input_keys=["input"],
    output_keys=["reference"],
    metadata_keys=["question_id"]
)
```

Then update the code to use `input.get("input")` instead of `input.get("question")`.

**Recommendation:** Option 1 is cleaner and follows Phoenix conventions.

### Type 1 Dataset from Phoenix Trace Export

If you exported traces from Phoenix UI, the structure is:
```
example_id,input_input,output_output,...
```

Where `input_input` contains JSON like:
```json
{"sys.query": "How do I...?", "sys.files": [], ...}
```

Phoenix will already have this imported correctly. The dataset is ready to use.

## Troubleshooting

### Q&A Evaluator Returns 0.0 Score

**Cause:** Dataset doesn't have expected answer, or field name doesn't match.

**Solution:** Ensure your dataset has one of these output fields:
- `answer`
- `expected`
- `expected_answer`
- `output`

### Hallucination/Relevance Returns 0.0 Score

**Cause:** DIFY didn't retrieve any documents.

**Solution:**
- Check DIFY workflow has knowledge retrieval enabled
- Verify knowledge base has relevant documents
- Check retrieval_count evaluator to confirm docs were retrieved

### All Evaluators Fail

**Cause:** Task output format doesn't match expected structure.

**Solution:** Check Phoenix UI experiment results to see what the task returned. Should be a dict with `output` and `reference` keys.
