#!/bin/bash
#
# Convenience wrapper for running experiments via Docker Compose
#
# Usage:
#   ./scripts/experiments/run_experiment_docker.sh                     # Interactive mode
#   ./scripts/experiments/run_experiment_docker.sh "my-experiment"     # Named experiment
#   ./scripts/experiments/run_experiment_docker.sh --dry-run           # Test with 3 examples
#   ./scripts/experiments/run_experiment_docker.sh --help              # Show help
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default configuration
DATASET_NAME="${DATASET_NAME:-Good 2025-10-20T14:32:32.450Z}"
EXPERIMENT_NAME=""
DRY_RUN=""
VERBOSE=""
EXTRA_ARGS=()
USE_HOST_NETWORK="false"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
info() {
    echo -e "${BLUE}INFO:${NC} $*"
}

success() {
    echo -e "${GREEN}SUCCESS:${NC} $*"
}

warn() {
    echo -e "${YELLOW}WARNING:${NC} $*"
}

error() {
    echo -e "${RED}ERROR:${NC} $*" >&2
}

show_help() {
    cat << EOF
DIFY Experiment Runner (Docker Compose)

Usage:
  $0 [OPTIONS] [EXPERIMENT_NAME]

Arguments:
  EXPERIMENT_NAME       Optional name for this experiment run

Options:
  --dataset NAME        Dataset name (default: "$DATASET_NAME")
  --dry-run [N]        Run with only N examples (default: 3)
  --verbose            Enable verbose debug logging
  --skip-qa            Skip Q&A correctness evaluator
  --explain            Get explanations from LLM evaluators
  --host-network       Use host network mode (for DIFY on localhost)
  --help               Show this help message

Environment Variables:
  DATASET_NAME         Default dataset name
  DIFY_BASE_URL        DIFY API endpoint (from .env)
  DIFY_API_KEY         DIFY API key (from .env)
  OPENAI_API_KEY       OpenAI API key for evaluators (from .env)
  EVAL_MODEL           Evaluation model (from .env)

Examples:
  # Quick dry run test
  $0 --dry-run

  # Run full experiment with custom name
  $0 "improved-retrieval-v2"

  # Run with verbose logging
  $0 --verbose "debug-test"

  # Use host network if DIFY is on localhost
  $0 --host-network "baseline-v1"

  # Use a different dataset
  $0 --dataset "my-other-dataset" "test-run"

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --dataset)
            DATASET_NAME="$2"
            shift 2
            ;;
        --dry-run)
            if [[ "${2:-}" =~ ^[0-9]+$ ]]; then
                DRY_RUN="$2"
                shift 2
            else
                DRY_RUN="3"
                shift
            fi
            ;;
        --verbose|-v)
            VERBOSE="--verbose"
            shift
            ;;
        --skip-qa)
            EXTRA_ARGS+=(--skip-qa)
            shift
            ;;
        --explain)
            EXTRA_ARGS+=(--explain)
            shift
            ;;
        --host-network)
            USE_HOST_NETWORK="true"
            shift
            ;;
        --*)
            error "Unknown option: $1"
            show_help
            exit 1
            ;;
        *)
            EXPERIMENT_NAME="$1"
            shift
            ;;
    esac
done

# Check if docker compose is available
if ! command -v docker &> /dev/null; then
    error "Docker is not installed or not in PATH"
    exit 1
fi

# Navigate to repo root
cd "$REPO_ROOT"

# Check if phoenix is running
if ! docker compose ps phoenix | grep -q "running\|healthy"; then
    warn "Phoenix service is not running. Starting it now..."
    docker compose up -d phoenix
    info "Waiting for Phoenix to be healthy..."
    sleep 5
fi

# Show configuration
info "Configuration:"
echo "  Dataset:       $DATASET_NAME"
if [[ -n "$EXPERIMENT_NAME" ]]; then
    echo "  Experiment:    $EXPERIMENT_NAME"
fi
if [[ -n "$DRY_RUN" ]]; then
    echo "  Dry Run:       $DRY_RUN examples"
fi
if [[ "$USE_HOST_NETWORK" == "true" ]]; then
    echo "  Network:       host (for localhost DIFY access)"
fi
echo ""

# Build command
CMD=(
    docker compose run --rm
)

# Add network mode if requested
if [[ "$USE_HOST_NETWORK" == "true" ]]; then
    CMD+=(--network host)
    CMD+=(-e PHOENIX_BASE_URL=http://localhost:6006)
fi

CMD+=(
    experiment-runner
    -m
    scripts.experiments.run_dify_experiment
    --dataset-name
    "$DATASET_NAME"
)

if [[ -n "$EXPERIMENT_NAME" ]]; then
    CMD+=(--experiment-name "$EXPERIMENT_NAME")
fi

if [[ -n "$DRY_RUN" ]]; then
    CMD+=(--dry-run "$DRY_RUN")
fi

if [[ -n "$VERBOSE" ]]; then
    CMD+=("$VERBOSE")
fi

CMD+=("${EXTRA_ARGS[@]}")

# Execute
info "Running experiment via Docker Compose..."
echo ""

if [[ -n "$VERBOSE" ]]; then
    echo "Command: ${CMD[*]}"
    echo ""
fi

if "${CMD[@]}"; then
    echo ""
    success "Experiment completed! Check Phoenix UI to view results."
    echo ""
    echo "View results at: http://localhost:6006/datasets"
else
    exit_code=$?
    echo ""
    error "Experiment failed with exit code $exit_code"
    echo ""
    echo "Troubleshooting tips:"
    echo "  1. Check Phoenix is running: docker compose ps phoenix"
    echo "  2. Check DIFY is accessible from container"
    echo "  3. Verify .env has DIFY_API_KEY and OPENAI_API_KEY"
    echo "  4. Try with --host-network flag if DIFY is on localhost"
    echo "  5. Run with --verbose for more details"
    exit $exit_code
fi
