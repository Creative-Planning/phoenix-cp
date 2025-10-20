# Web API for Running Experiments

## Context & Problem Statement

### The Gap in Phoenix UI

Phoenix provides an excellent UI for **viewing** experiment results and comparing evaluator scores across runs, but it has a significant limitation:

**Phoenix does not provide a UI to actually run experiments.**

When you navigate to the experiments section in Phoenix UI, the "Run Experiment" documentation just shows code examples:

```python
experiment = client.experiments.run_experiment(
    dataset=dataset,
    task=task,
    evaluators=[...]
)
```

This means users must:
1. Have Python environment access
2. Write or run Python code from a terminal/notebook
3. Have the Phoenix SDK installed
4. Understand the SDK API

### Why This Matters for Our Use Case

Our workflow is:
1. **Make changes to DIFY workflow** (adjust retrieval, modify prompts, etc.)
2. **Run experiment** to test changes against dataset
3. **View results in Phoenix UI** to see if quality improved

Step #2 requires terminal access and running Python scripts, which creates friction for:
- Non-technical stakeholders who want to test workflow changes
- Team members who don't have local dev environments set up
- Automated testing workflows that should trigger on DIFY changes

### The Solution

Build a **simple web API** that wraps the experiment runner, allowing users to trigger experiments via:
- HTML form (browser-based, no terminal needed)
- HTTP API (for automation/CI/CD)
- Future integrations (Slack bots, scheduled tasks, etc.)

This API will be deployed alongside Phoenix in ECS/Docker and provide the missing UI for running experiments.

---

## Architecture Overview

```
┌─────────────────────┐
│   Phoenix UI        │  ← Users view experiment results here
│   (Port 6006)       │     (Phoenix's built-in UI)
└─────────────────────┘
          ↑
          │ Experiment results stored via SDK
          │
┌─────────────────────┐
│ Experiment API      │  ← NEW: Users trigger experiments here
│ (FastAPI on 8000)   │     (Our custom web interface)
│                     │
│ - HTML form UI      │
│ - REST API          │
│ - Auth via API key  │
└─────────────────────┘
          ↓
     Uses Phoenix SDK
          ↓
┌─────────────────────┐
│   DIFY API          │  ← Experiments call workflow here
│   (Port 80)         │     (Existing DIFY deployment)
└─────────────────────┘
```

---

## Recommended Security Approach

### Strategy: API Key + Network Isolation

**Why this approach:**
- Mirrors DIFY's existing auth pattern (users already familiar)
- Simple deployment (one environment variable)
- Stateless (no session management)
- Works for both HTML and API clients
- Optional IP whitelisting for additional security

### Security Layers

1. **Network Security (VPC)**
   - Deploy in private subnet if only internal users need access
   - Use security groups to restrict inbound traffic
   - Optional: Require VPN access

2. **API Key Authentication**
   - Single shared key (like DIFY's API key model)
   - Set via environment variable: `EXPERIMENT_API_KEY`
   - Sent as Bearer token in Authorization header

3. **Optional IP Whitelist**
   - Additional layer: restrict to specific IPs
   - Set via environment variable: `ALLOWED_IPS=10.0.1.5,10.0.1.6`

---

## Implementation Design

### API Endpoints

#### 1. `POST /experiments/run` - Trigger Experiment

**Request:**
```json
{
  "experiment_name": "improved-retrieval-v2",
  "dataset_name": "Good 2025-10-20T14:32:32.450Z",
  "dry_run": false,
  "skip_qa": false,
  "verbose": false
}
```

**Headers:**
```
Authorization: Bearer <EXPERIMENT_API_KEY>
Content-Type: application/json
```

**Response (202 Accepted):**
```json
{
  "status": "started",
  "experiment_name": "improved-retrieval-v2",
  "dataset_name": "Good 2025-10-20T14:32:32.450Z",
  "message": "Experiment started in background. Check Phoenix UI for results.",
  "phoenix_url": "http://localhost:6006/datasets"
}
```

**Error Responses:**
- `401 Unauthorized` - Missing or invalid API key
- `403 Forbidden` - IP not whitelisted
- `400 Bad Request` - Invalid parameters

#### 2. `GET /datasets` - List Available Datasets

**Request:**
```
GET /datasets
Authorization: Bearer <EXPERIMENT_API_KEY>
```

**Response:**
```json
[
  {
    "id": "abc123",
    "name": "Good 2025-10-20T14:32:32.450Z",
    "example_count": 15
  },
  {
    "id": "def456",
    "name": "Edge Cases 2025-10-21",
    "example_count": 8
  }
]
```

#### 3. `GET /` - HTML Form UI

**Request:**
```
GET /
```

**Response:**
HTML page with:
- Login form (enter API key, stored in localStorage)
- Dataset dropdown (populated from `/datasets`)
- Experiment name input
- Run experiment button
- Link to Phoenix UI

---

## FastAPI Implementation

### Main API Code

```python
# scripts/experiments/experiment_api.py

from fastapi import FastAPI, HTTPException, Header, Request, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import subprocess
import logging
from pathlib import Path

app = FastAPI(title="Phoenix Experiment Runner")
logger = logging.getLogger(__name__)

# Configuration from environment
EXPERIMENT_API_KEY = os.getenv("EXPERIMENT_API_KEY")
ALLOWED_IPS = os.getenv("ALLOWED_IPS", "").split(",") if os.getenv("ALLOWED_IPS") else []
PHOENIX_URL = os.getenv("PHOENIX_BASE_URL", "http://localhost:6006")

if not EXPERIMENT_API_KEY:
    raise RuntimeError("EXPERIMENT_API_KEY environment variable must be set")

# Request/Response Models
class ExperimentRequest(BaseModel):
    experiment_name: str
    dataset_name: str = "Good 2025-10-20T14:32:32.450Z"
    dry_run: bool = False
    skip_qa: bool = False
    verbose: bool = False

class ExperimentResponse(BaseModel):
    status: str
    experiment_name: str
    dataset_name: str
    message: str
    phoenix_url: str

class Dataset(BaseModel):
    id: str
    name: str
    example_count: int

# Security Dependencies
def verify_api_key(authorization: str = Header(None), request: Request = None):
    """Verify API key and optional IP whitelist"""

    # Check IP whitelist if configured
    if ALLOWED_IPS and request:
        client_ip = request.client.host
        if client_ip not in ALLOWED_IPS:
            logger.warning(f"IP {client_ip} not in whitelist")
            raise HTTPException(403, "IP address not allowed")

    # Check API key
    if not authorization:
        raise HTTPException(401, "Authorization header required")

    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization format. Use: Bearer <token>")

    token = authorization.replace("Bearer ", "")
    if token != EXPERIMENT_API_KEY:
        logger.warning("Invalid API key attempt")
        raise HTTPException(403, "Invalid API key")

    return True

# Background task to run experiment
def run_experiment_task(request: ExperimentRequest):
    """Execute experiment script in background"""
    script_dir = Path(__file__).parent
    cmd = [
        "python",
        str(script_dir / "run_dify_experiment.py"),
        "--dataset-name", request.dataset_name,
        "--experiment-name", request.experiment_name,
    ]

    if request.dry_run:
        cmd.extend(["--dry-run", "3"])

    if request.skip_qa:
        cmd.append("--skip-qa")

    if request.verbose:
        cmd.append("--verbose")

    try:
        logger.info(f"Starting experiment: {request.experiment_name}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode == 0:
            logger.info(f"Experiment completed: {request.experiment_name}")
        else:
            logger.error(f"Experiment failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error(f"Experiment timed out: {request.experiment_name}")
    except Exception as e:
        logger.error(f"Experiment error: {e}")

# API Endpoints
@app.post("/experiments/run", response_model=ExperimentResponse)
async def run_experiment(
    request: ExperimentRequest,
    background_tasks: BackgroundTasks,
    authenticated: bool = Depends(verify_api_key)
):
    """Trigger an experiment run"""

    # Start experiment in background
    background_tasks.add_task(run_experiment_task, request)

    return ExperimentResponse(
        status="started",
        experiment_name=request.experiment_name,
        dataset_name=request.dataset_name,
        message="Experiment started in background. Check Phoenix UI for results.",
        phoenix_url=f"{PHOENIX_URL}/datasets"
    )

@app.get("/datasets", response_model=list[Dataset])
async def list_datasets(authenticated: bool = Depends(verify_api_key)):
    """List available Phoenix datasets"""
    from phoenix.client import Client

    try:
        client = Client()
        datasets = []

        for dataset in client.datasets.list_datasets():
            datasets.append(Dataset(
                id=dataset.id,
                name=dataset.name,
                example_count=len(dataset)
            ))

        return datasets
    except Exception as e:
        logger.error(f"Error listing datasets: {e}")
        raise HTTPException(500, f"Failed to list datasets: {str(e)}")

@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve HTML form UI"""
    html_file = Path(__file__).parent / "experiment_ui.html"
    if html_file.exists():
        return html_file.read_text()
    else:
        return """
        <html>
        <body>
            <h1>Experiment Runner</h1>
            <p>UI file not found. Use the API directly:</p>
            <pre>
POST /experiments/run
Authorization: Bearer YOUR_API_KEY

{
  "experiment_name": "test-v1",
  "dataset_name": "Good 2025-10-20T14:32:32.450Z"
}
            </pre>
        </body>
        </html>
        """

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## HTML Form UI

### User Experience Flow

1. **First Visit:** User sees API key input form
2. **Enter Key:** User enters `EXPERIMENT_API_KEY` and clicks "Save"
3. **Key Stored:** API key saved in browser's localStorage
4. **Form Appears:** Dataset dropdown and experiment controls shown
5. **Run Experiment:** Select dataset, enter name, click "Run"
6. **Confirmation:** Success message with link to Phoenix UI
7. **Logout:** Button to clear stored key and return to login

### HTML Implementation

```html
<!-- scripts/experiments/experiment_ui.html -->

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Phoenix Experiment Runner</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .card {
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            margin-top: 0;
            color: #333;
        }
        input, select, button {
            width: 100%;
            padding: 12px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            box-sizing: border-box;
        }
        button {
            background: #0066cc;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: 500;
        }
        button:hover {
            background: #0052a3;
        }
        button.secondary {
            background: #6c757d;
        }
        button.secondary:hover {
            background: #545b62;
        }
        .hidden {
            display: none;
        }
        .message {
            padding: 15px;
            margin: 15px 0;
            border-radius: 4px;
        }
        .message.success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .message.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .checkbox-group {
            display: flex;
            align-items: center;
            margin: 10px 0;
        }
        .checkbox-group input[type="checkbox"] {
            width: auto;
            margin-right: 10px;
        }
        label {
            display: block;
            margin-top: 15px;
            font-weight: 500;
            color: #555;
        }
        .info {
            background: #e7f3ff;
            padding: 15px;
            border-radius: 4px;
            margin: 15px 0;
            color: #004085;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>🧪 Phoenix Experiment Runner</h1>

        <!-- API Key Login Form -->
        <div id="authSection" class="hidden">
            <p>Enter your experiment API key to continue:</p>
            <input type="password" id="apiKeyInput" placeholder="API Key (same as EXPERIMENT_API_KEY env var)">
            <button onclick="saveApiKey()">Save Key & Continue</button>
            <div id="authError" class="message error hidden"></div>
        </div>

        <!-- Experiment Form -->
        <div id="experimentSection" class="hidden">
            <div class="info">
                Run experiments to evaluate your DIFY workflow changes.
                Results will appear in <a href="" id="phoenixLink" target="_blank">Phoenix UI</a>.
            </div>

            <label for="datasetSelect">Dataset:</label>
            <select id="datasetSelect">
                <option value="">Loading datasets...</option>
            </select>

            <label for="experimentName">Experiment Name:</label>
            <input type="text" id="experimentName" placeholder="e.g., improved-retrieval-v2" required>

            <div class="checkbox-group">
                <input type="checkbox" id="dryRun">
                <label for="dryRun" style="margin: 0;">Dry run (test with 3 examples only)</label>
            </div>

            <div class="checkbox-group">
                <input type="checkbox" id="skipQa">
                <label for="skipQa" style="margin: 0;">Skip Q&A evaluator (faster)</label>
            </div>

            <div class="checkbox-group">
                <input type="checkbox" id="verbose">
                <label for="verbose" style="margin: 0;">Verbose logging</label>
            </div>

            <button onclick="runExperiment()">▶️ Run Experiment</button>
            <button class="secondary" onclick="logout()">Logout</button>

            <div id="resultMessage" class="hidden"></div>
        </div>
    </div>

    <script>
        const API_KEY_STORAGE = 'phoenix_experiment_api_key';
        const PHOENIX_URL = window.location.origin.replace('8000', '6006'); // Adjust if needed

        // Initialize page
        function init() {
            const apiKey = localStorage.getItem(API_KEY_STORAGE);

            if (apiKey) {
                showExperimentForm();
                loadDatasets();
            } else {
                showAuthForm();
            }

            // Set Phoenix link
            document.getElementById('phoenixLink').href = `${PHOENIX_URL}/datasets`;
        }

        function showAuthForm() {
            document.getElementById('authSection').classList.remove('hidden');
            document.getElementById('experimentSection').classList.add('hidden');
        }

        function showExperimentForm() {
            document.getElementById('authSection').classList.add('hidden');
            document.getElementById('experimentSection').classList.remove('hidden');
        }

        function saveApiKey() {
            const apiKey = document.getElementById('apiKeyInput').value.trim();

            if (!apiKey) {
                showError('authError', 'Please enter an API key');
                return;
            }

            // Store key and test it by loading datasets
            localStorage.setItem(API_KEY_STORAGE, apiKey);
            showExperimentForm();
            loadDatasets();
        }

        function logout() {
            localStorage.removeItem(API_KEY_STORAGE);
            showAuthForm();
            document.getElementById('apiKeyInput').value = '';
        }

        async function loadDatasets() {
            const apiKey = localStorage.getItem(API_KEY_STORAGE);
            const select = document.getElementById('datasetSelect');

            try {
                const response = await fetch('/datasets', {
                    headers: {
                        'Authorization': `Bearer ${apiKey}`
                    }
                });

                if (response.status === 401 || response.status === 403) {
                    showError('authError', 'Invalid API key');
                    logout();
                    return;
                }

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const datasets = await response.json();

                select.innerHTML = '';
                if (datasets.length === 0) {
                    select.innerHTML = '<option value="">No datasets found</option>';
                } else {
                    datasets.forEach(dataset => {
                        const option = document.createElement('option');
                        option.value = dataset.name;
                        option.textContent = `${dataset.name} (${dataset.example_count} examples)`;
                        select.appendChild(option);
                    });
                }
            } catch (error) {
                select.innerHTML = '<option value="">Error loading datasets</option>';
                console.error('Failed to load datasets:', error);
            }
        }

        async function runExperiment() {
            const apiKey = localStorage.getItem(API_KEY_STORAGE);
            const experimentName = document.getElementById('experimentName').value.trim();
            const datasetName = document.getElementById('datasetSelect').value;

            if (!experimentName) {
                showMessage('Please enter an experiment name', 'error');
                return;
            }

            if (!datasetName) {
                showMessage('Please select a dataset', 'error');
                return;
            }

            const payload = {
                experiment_name: experimentName,
                dataset_name: datasetName,
                dry_run: document.getElementById('dryRun').checked,
                skip_qa: document.getElementById('skipQa').checked,
                verbose: document.getElementById('verbose').checked
            };

            try {
                const response = await fetch('/experiments/run', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${apiKey}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(payload)
                });

                if (response.status === 401 || response.status === 403) {
                    showMessage('Authentication failed. Please login again.', 'error');
                    logout();
                    return;
                }

                const result = await response.json();

                if (response.ok) {
                    showMessage(
                        `✅ Experiment "${experimentName}" started! ` +
                        `<a href="${result.phoenix_url}" target="_blank">View results in Phoenix UI →</a>`,
                        'success'
                    );

                    // Clear form
                    document.getElementById('experimentName').value = '';
                    document.getElementById('dryRun').checked = false;
                } else {
                    showMessage(`❌ Failed to start experiment: ${result.message || 'Unknown error'}`, 'error');
                }
            } catch (error) {
                showMessage(`❌ Error: ${error.message}`, 'error');
                console.error('Failed to run experiment:', error);
            }
        }

        function showMessage(text, type) {
            const messageDiv = document.getElementById('resultMessage');
            messageDiv.innerHTML = text;
            messageDiv.className = `message ${type}`;
            messageDiv.classList.remove('hidden');
        }

        function showError(elementId, text) {
            const errorDiv = document.getElementById(elementId);
            errorDiv.textContent = text;
            errorDiv.classList.remove('hidden');
        }

        // Initialize on page load
        init();
    </script>
</body>
</html>
```

---

## Deployment Configuration

### Docker Compose (Local Development)

```yaml
# docker-compose.yml (add to existing Phoenix setup)

services:
  phoenix:
    image: arizephoenix/phoenix:latest
    ports:
      - "6006:6006"
    environment:
      - PHOENIX_WORKING_DIR=/data
    volumes:
      - phoenix-data:/data

  experiment-api:
    build:
      context: .
      dockerfile: Dockerfile.experiment-api
    ports:
      - "8000:8000"
    environment:
      - EXPERIMENT_API_KEY=${EXPERIMENT_API_KEY}
      - DIFY_API_KEY=${DIFY_API_KEY}
      - DIFY_BASE_URL=http://dify/v1
      - PHOENIX_BASE_URL=http://phoenix:6006
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ALLOWED_IPS=${ALLOWED_IPS:-}
    depends_on:
      - phoenix
    volumes:
      - ./scripts/experiments:/app/scripts/experiments

volumes:
  phoenix-data:
```

### Dockerfile

```dockerfile
# Dockerfile.experiment-api

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn[standard] \
    arize-phoenix-client \
    arize-phoenix-otel \
    openinference-instrumentation-openai \
    openai \
    httpx \
    pandas

# Copy experiment scripts
COPY scripts/experiments /app/scripts/experiments

# Run API server
CMD ["uvicorn", "scripts.experiments.experiment_api:app", "--host", "0.0.0.0", "--port", "8000"]
```

### AWS ECS Task Definition

```json
{
  "family": "phoenix-experiment-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [
    {
      "name": "experiment-api",
      "image": "your-ecr-repo/experiment-api:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "PHOENIX_BASE_URL",
          "value": "http://phoenix.internal:6006"
        },
        {
          "name": "DIFY_BASE_URL",
          "value": "http://dify.internal/v1"
        }
      ],
      "secrets": [
        {
          "name": "EXPERIMENT_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:experiment-api-key"
        },
        {
          "name": "DIFY_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:dify-api-key"
        },
        {
          "name": "OPENAI_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:openai-api-key"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/experiment-api",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

### Environment Variables Reference

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `EXPERIMENT_API_KEY` | ✅ Yes | Shared secret for API authentication | `exp-abc123xyz` |
| `DIFY_API_KEY` | ✅ Yes | DIFY workflow API key | `app-xyz789` |
| `OPENAI_API_KEY` | ✅ Yes | OpenAI key for evaluators | `sk-abc123` |
| `PHOENIX_BASE_URL` | No | Phoenix instance URL | `http://localhost:6006` |
| `DIFY_BASE_URL` | No | DIFY API endpoint | `http://localhost/v1` |
| `ALLOWED_IPS` | No | Comma-separated IP whitelist | `10.0.1.5,10.0.1.6` |

---

## Usage Examples

### Via Web UI

1. Navigate to `http://localhost:8000`
2. Enter API key (same value as `EXPERIMENT_API_KEY` env var)
3. Select dataset from dropdown
4. Enter experiment name: `improved-retrieval-v2`
5. Click "Run Experiment"
6. Click link to view results in Phoenix UI

### Via cURL

```bash
# Run experiment
curl -X POST http://localhost:8000/experiments/run \
  -H "Authorization: Bearer $EXPERIMENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "experiment_name": "improved-retrieval-v2",
    "dataset_name": "Good 2025-10-20T14:32:32.450Z",
    "dry_run": false,
    "skip_qa": false
  }'

# List datasets
curl http://localhost:8000/datasets \
  -H "Authorization: Bearer $EXPERIMENT_API_KEY"
```

### Via Python

```python
import requests

API_KEY = "your-experiment-api-key"
BASE_URL = "http://localhost:8000"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# List datasets
response = requests.get(f"{BASE_URL}/datasets", headers=headers)
datasets = response.json()
print(f"Available datasets: {[d['name'] for d in datasets]}")

# Run experiment
payload = {
    "experiment_name": "test-v1",
    "dataset_name": datasets[0]["name"],
    "dry_run": True
}
response = requests.post(f"{BASE_URL}/experiments/run", headers=headers, json=payload)
result = response.json()
print(f"Status: {result['status']}")
print(f"View results: {result['phoenix_url']}")
```

---

## Future Enhancements

### Phase 2 Improvements

1. **Experiment Status Tracking**
   - Add `/experiments/{id}/status` endpoint
   - Poll for completion before redirecting to results
   - Show progress bar in UI

2. **User Management**
   - Replace single API key with per-user authentication
   - Track who ran which experiments
   - Role-based access (viewer vs. runner)

3. **Scheduled Experiments**
   - Add cron-like scheduling
   - Weekly baseline runs
   - Automated regression testing

4. **Webhook Integrations**
   - Slack notifications when experiments complete
   - GitHub PR comments with quality comparisons
   - Email reports for experiment results

5. **Advanced UI Features**
   - Side-by-side experiment comparison in API
   - Visualize evaluator score trends
   - Export results to CSV/JSON

---

## Security Checklist

Before deploying to production:

- [ ] Set strong `EXPERIMENT_API_KEY` (32+ random characters)
- [ ] Store secrets in AWS Secrets Manager / Parameter Store
- [ ] Configure VPC security groups to restrict inbound traffic
- [ ] Enable HTTPS/TLS for API endpoint
- [ ] Set `ALLOWED_IPS` for additional IP filtering
- [ ] Configure CloudWatch logging for audit trail
- [ ] Set up alerts for failed authentication attempts
- [ ] Implement rate limiting (e.g., max 10 experiments/hour)
- [ ] Regular key rotation policy

---

## Testing the API

### Local Testing Steps

1. **Start Phoenix:**
   ```bash
   docker run -p 6006:6006 arizephoenix/phoenix:latest
   ```

2. **Set environment variables:**
   ```bash
   export EXPERIMENT_API_KEY="test-key-123"
   export DIFY_API_KEY="app-your-dify-key"
   export OPENAI_API_KEY="sk-your-openai-key"
   ```

3. **Run the API:**
   ```bash
   cd scripts/experiments
   python experiment_api.py
   ```

4. **Test endpoints:**
   ```bash
   # Health check
   curl http://localhost:8000/health

   # List datasets (should fail - no auth)
   curl http://localhost:8000/datasets

   # List datasets (with auth)
   curl http://localhost:8000/datasets \
     -H "Authorization: Bearer test-key-123"

   # Open in browser
   open http://localhost:8000
   ```

---

## Troubleshooting

### Common Issues

**Problem:** API key not working
- **Check:** Environment variable is set: `echo $EXPERIMENT_API_KEY`
- **Check:** No extra spaces in key
- **Check:** Header format is correct: `Bearer <key>` (not `<key>` alone)

**Problem:** Datasets not loading
- **Check:** Phoenix is running and accessible
- **Check:** `PHOENIX_BASE_URL` points to correct Phoenix instance
- **Check:** Phoenix contains datasets (check UI directly)

**Problem:** Experiment not starting
- **Check:** `DIFY_API_KEY` is set and valid
- **Check:** DIFY is running and accessible
- **Check:** Dataset exists with correct name

**Problem:** IP whitelist blocking requests
- **Check:** Your IP is in `ALLOWED_IPS`
- **Solution:** Add IP or remove whitelist for testing: `unset ALLOWED_IPS`

---

## References

- Phoenix Experiments Docs: https://arize.com/docs/phoenix/datasets-and-experiments/how-to-experiments/run-experiments
- FastAPI Security: https://fastapi.tiangolo.com/tutorial/security/
- DIFY API Documentation: `/docs/cp-docs/dify-api.md`
- Experiment Runner Script: `/scripts/experiments/run_dify_experiment.py`
