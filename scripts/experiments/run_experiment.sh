#!/bin/bash
#
# Convenience wrapper for running DIFY experiments
#
# Usage:
#   ./scripts/experiments/run_experiment.sh                    # Use defaults
#   ./scripts/experiments/run_experiment.sh "my-experiment"    # Named experiment
#   ./scripts/experiments/run_experiment.sh --dry-run          # Test with 3 examples
#   ./scripts/experiments/run_experiment.sh --help             # Show help
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default configuration
DATASET_NAME="${DATASET_NAME:-Good 2025-10-20T14:32:32.450Z}"
DIFY_BASE_URL="${DIFY_BASE_URL:-http://localhost/v1}"
DIFY_API_KEY="${DIFY_API_KEY:-}"
EVAL_MODEL="${EVAL_MODEL:-gpt-4o}"
EXPERIMENT_NAME=""
DRY_RUN=""
VERBOSE=""
EXTRA_ARGS=()

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
DIFY Experiment Runner

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
  --help               Show this help message

Environment Variables:
  DATASET_NAME         Default dataset name
  DIFY_BASE_URL        DIFY API endpoint (default: http://localhost/v1)
  DIFY_API_KEY         DIFY API key (required)
  EVAL_MODEL           Evaluation model (default: gpt-4o)
  OPENAI_API_KEY       OpenAI API key for evaluators (required)

Examples:
  # Quick dry run test
  $0 --dry-run

  # Run full experiment with custom name
  $0 "improved-retrieval-v2"

  # Run with verbose logging
  $0 --verbose "debug-test"

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
            EXTRA_ARGS+=("--skip-qa")
            shift
            ;;
        --explain)
            EXTRA_ARGS+=("--explain")
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

# Validation
if [[ -z "$DIFY_API_KEY" ]]; then
    error "DIFY_API_KEY environment variable is not set"
    echo ""
    echo "Please set your DIFY API key:"
    echo "  export DIFY_API_KEY='app-xxxxx'"
    echo ""
    echo "Or pass it via environment variable:"
    echo "  DIFY_API_KEY='app-xxxxx' $0"
    exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    warn "OPENAI_API_KEY not set. LLM evaluators may fail."
    echo "  Set it with: export OPENAI_API_KEY='sk-xxxxx'"
    echo ""
fi

# Show configuration
info "Configuration:"
echo "  Dataset:       $DATASET_NAME"
echo "  DIFY URL:      $DIFY_BASE_URL"
echo "  Eval Model:    $EVAL_MODEL"
if [[ -n "$EXPERIMENT_NAME" ]]; then
    echo "  Experiment:    $EXPERIMENT_NAME"
fi
if [[ -n "$DRY_RUN" ]]; then
    echo "  Dry Run:       $DRY_RUN examples"
fi
echo ""

# Build command
CMD=(
    python
    "$SCRIPT_DIR/run_dify_experiment.py"
    --dataset-name "$DATASET_NAME"
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
info "Running experiment..."
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
    exit $exit_code
fi
