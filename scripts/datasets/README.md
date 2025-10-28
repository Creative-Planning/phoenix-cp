# Phoenix Dataset Upload Tools

This directory contains scripts to help analysts upload CSV datasets to Phoenix for running DIFY experiments.

## Quick Start

### 1. Prepare Your CSV File

Create a CSV with questions and expected answers:

```csv
question,expected_answer
"What is the capital of France?","Paris"
"Who wrote Romeo and Juliet?","William Shakespeare"
"What is photosynthesis?","The process by which plants convert light energy into chemical energy"
```

**Supported column names:**
- **Questions:** `question` (recommended), `query`, `input`
- **Expected answers:** `expected_answer` (recommended), `answer`, `expected`, `output`, `reference`

### 2. Upload to Phoenix

**Simplest method (local Phoenix):**
```bash
./scripts/datasets/upload_dataset.sh my-dataset.csv
```

**With custom name:**
```bash
./scripts/datasets/upload_dataset.sh my-dataset.csv "QA Dataset v2"
```

**To remote Phoenix (EC2):**
```bash
PHOENIX_BASE_URL="http://ec2-12-34-56-78.us-west-2.compute.amazonaws.com:6006" \
PHOENIX_API_KEY="phx_..." \
  ./scripts/datasets/upload_dataset.sh my-dataset.csv
```

**Preview before uploading:**
```bash
./scripts/datasets/upload_dataset.sh my-dataset.csv --dry-run
```

---

## Upload Methods Explained

### Method 1: Shell Wrapper (Recommended)

The `upload_dataset.sh` script provides a user-friendly interface:

```bash
./scripts/datasets/upload_dataset.sh [options] <csv-file> [dataset-name]

Options:
  -n, --name NAME    Dataset name
  -u, --url URL      Phoenix URL
  -k, --api-key KEY  Phoenix API key
  --dry-run          Preview without uploading
  --verbose          Enable verbose output
  -h, --help         Show help
```

### Method 2: Python Script (Advanced)

For more control, use the Python script directly:

```bash
python scripts/datasets/upload_dataset.py my-dataset.csv \
    --name "custom-name" \
    --phoenix-url "http://localhost:6006" \
    --api-key "your-api-key" \
    --input-keys "question" \
    --output-keys "expected_answer" \
    --metadata-keys "category,difficulty"
```

### Method 3: Interactive Python (Most Flexible)

For one-off uploads or custom processing:

```python
import pandas as pd
from phoenix.client import Client

# Connect to Phoenix
client = Client(
    base_url="http://localhost:6006",
    api_key="your-api-key"  # Optional for local
)

# Load and upload
df = pd.read_csv("my-dataset.csv")

dataset = client.datasets.create_dataset(
    name="my-qa-dataset",
    dataframe=df,
    input_keys=["question"],
    output_keys=["expected_answer"],
)

print(f"Uploaded {len(dataset)} examples")
```

---

## Environment Setup

### For Local Development

```bash
# Install dependencies
pip install pandas arize-phoenix-client

# Ensure Phoenix is running
docker compose ps phoenix

# Upload dataset
./scripts/datasets/upload_dataset.sh my-data.csv
```

### For Remote Phoenix (EC2)

#### Option A: Upload from Local Machine

```bash
# Set environment variables
export PHOENIX_BASE_URL="http://your-ec2-host:6006"
export PHOENIX_API_KEY="phx_..."  # Get from Phoenix UI

# Upload
./scripts/datasets/upload_dataset.sh my-data.csv "Production QA Dataset v1"
```

#### Option B: Upload from EC2 Host

```bash
# 1. Copy CSV to EC2
scp my-dataset.csv ubuntu@ec2-host:/tmp/

# 2. SSH into EC2
ssh ubuntu@ec2-host

# 3. Upload using local connection
cd /opt/phoenix  # Or wherever Phoenix is deployed

# Using docker (if scripts are available)
docker compose exec phoenix python3 << 'EOF'
from phoenix.client import Client
import pandas as pd

df = pd.read_csv("/tmp/my-dataset.csv")
client = Client()  # Uses localhost

dataset = client.datasets.create_dataset(
    name="uploaded-from-ec2",
    dataframe=df,
    input_keys=["question"],
    output_keys=["expected_answer"],
)
print(f"Uploaded {len(dataset)} examples")
EOF
```

---

## Getting Your Phoenix API Key

### From Phoenix UI:

1. Open Phoenix: `http://localhost:6006` (or your EC2 URL)
2. Log in with admin credentials
3. Navigate to **Settings** → **API Keys**
4. Click **Create API Key**
5. Copy the key (starts with `phx_`)

### From Command Line (EC2):

The deployment script may have already created a system API key in `/opt/phoenix/.env`:

```bash
ssh ubuntu@ec2-host
grep PHOENIX_API_KEY /opt/phoenix/.env
```

---

## CSV Format Requirements

### Minimum Requirements

A valid dataset needs at least:
- One input column (questions)
- One output column (expected answers) for full evaluation

**Example:**
```csv
question,expected_answer
"What is 2+2?","4"
"Capital of France?","Paris"
```

### With Metadata (Optional)

You can include additional columns for categorization:

```csv
question,expected_answer,category,difficulty,topic
"What is 2+2?","4","math","easy","arithmetic"
"Capital of France?","Paris","geography","easy","europe"
```

Upload with metadata:
```bash
python scripts/datasets/upload_dataset.py my-dataset.csv \
    --input-keys "question" \
    --output-keys "expected_answer" \
    --metadata-keys "category,difficulty,topic"
```

### Questions Only (No Expected Answers)

If you only have questions, you can still upload:

```csv
question
"What is quantum entanglement?"
"How does photosynthesis work?"
```

Upload as:
```bash
python scripts/datasets/upload_dataset.py questions-only.csv \
    --input-keys "question" \
    --output-keys ""  # Empty - no expected answers
```

⚠️ **Note:** Without expected answers, the Q&A correctness evaluator will be skipped. You'll still get:
- Hallucination detection
- Relevance scoring
- Retrieval quality metrics

---

## After Upload: Running Experiments

Once uploaded, use your dataset in experiments:

```bash
# Run experiment with your new dataset
./scripts/experiments/run_experiment.sh \
  --dataset "my-qa-dataset" \
  "baseline-v1"

# Or with Docker
./scripts/experiments/run_experiment_docker.sh \
  --dataset "my-qa-dataset" \
  "baseline-v1"
```

See `docs/creative-planning/experiments-guide.md` for full experiment documentation.

---

## Troubleshooting

### "Connection refused" to Phoenix

**Check if Phoenix is running:**
```bash
# Local
curl http://localhost:6006/healthz

# Remote
curl http://your-ec2-host:6006/healthz
```

**Start Phoenix if needed:**
```bash
docker compose up -d phoenix
```

### "Failed to upload dataset: 401 Unauthorized"

You need a valid API key for authentication:

```bash
# Check if API key is set
echo $PHOENIX_API_KEY

# Get key from Phoenix UI or create one
# See "Getting Your Phoenix API Key" section above
```

### "Columns not found in CSV"

The script expects specific column names. Check your CSV headers:

```bash
# View CSV headers
head -1 my-dataset.csv
```

Then specify the correct column names:
```bash
python scripts/datasets/upload_dataset.py my-dataset.csv \
    --input-keys "your_question_column" \
    --output-keys "your_answer_column"
```

### "pandas is required"

Install the required Python packages:

```bash
pip install pandas arize-phoenix-client
```

Or if using a virtual environment:
```bash
cd /home/acb/venv-dirs/arize-phoenix/
source venv/bin/activate
pip install pandas arize-phoenix-client
```

### Dataset uploaded but not showing in UI

1. Refresh the Phoenix UI
2. Check the Datasets page: `http://localhost:6006/datasets`
3. Verify the dataset was created:

```python
from phoenix.client import Client
client = Client()
for dataset in client.datasets.list_datasets():
    print(f"{dataset.name}: {len(dataset)} examples")
```

---

## Best Practices

### 1. Use Descriptive Names

```bash
# Good
./scripts/datasets/upload_dataset.sh data.csv "customer-support-qa-2025-10-28"

# Bad
./scripts/datasets/upload_dataset.sh data.csv "test123"
```

### 2. Include Version Numbers

```bash
./scripts/datasets/upload_dataset.sh data.csv "product-knowledge-qa-v2"
```

### 3. Preview Before Upload

```bash
./scripts/datasets/upload_dataset.sh data.csv --dry-run
```

### 4. Keep CSV Files in Version Control

```bash
mkdir datasets/
cp my-dataset.csv datasets/customer-support-qa-v1.csv
git add datasets/customer-support-qa-v1.csv
git commit -m "Add customer support QA dataset v1"
```

### 5. Document Dataset Purpose

Add a comment or description:
```bash
python scripts/datasets/upload_dataset.py my-data.csv \
    --name "regression-test-suite" \
    --description "Core regression tests covering top 20 customer queries"
```

---

## Related Documentation

- **Running Experiments:** `docs/creative-planning/experiments-guide.md`
- **Dataset Formats:** `scripts/experiments/DATASET_FORMATS.md`
- **Deployment Guide:** `docs/creative-planning/deployment.md`
- **Phoenix Docs:** https://arize.com/docs/phoenix/datasets-and-experiments/

---

## Examples

### Example 1: Simple Upload (Local)

```bash
# Create CSV
cat > test-data.csv << 'EOF'
question,expected_answer
"What is 2+2?","4"
"Capital of France?","Paris"
EOF

# Upload
./scripts/datasets/upload_dataset.sh test-data.csv

# Run experiment
./scripts/experiments/run_experiment.sh \
    --dataset "test-data-2025-10-28T..." \
    "test-run"
```

### Example 2: Upload to EC2 from Local Machine

```bash
# Set credentials
export PHOENIX_BASE_URL="http://ec2-12-34-56-78.compute.amazonaws.com:6006"
export PHOENIX_API_KEY="phx_abc123..."

# Upload
./scripts/datasets/upload_dataset.sh production-qa.csv "prod-qa-v1"

# Verify
curl "$PHOENIX_BASE_URL/datasets" -H "Authorization: Bearer $PHOENIX_API_KEY"
```

### Example 3: Custom Column Names

```bash
# CSV has non-standard column names
cat my-data.csv
# user_query,correct_response,category
# "How to reset password?","Click 'Forgot Password'","auth"

# Upload with custom column mapping
python scripts/datasets/upload_dataset.py my-data.csv \
    --name "auth-qa" \
    --input-keys "user_query" \
    --output-keys "correct_response" \
    --metadata-keys "category"
```

---

For questions or issues, see the troubleshooting section or consult the main experiments guide.
