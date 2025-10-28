#!/usr/bin/env bash
#
# Convenience wrapper for uploading CSV datasets to Phoenix.
#
# This script provides a simple interface for analysts to upload datasets,
# with sensible defaults and helpful error messages.
#
# Usage:
#   ./scripts/datasets/upload_dataset.sh my-dataset.csv
#   ./scripts/datasets/upload_dataset.sh my-dataset.csv "Custom Dataset Name"
#   ./scripts/datasets/upload_dataset.sh --help

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default values
PHOENIX_URL="${PHOENIX_BASE_URL:-http://localhost:6006}"
DATASET_NAME=""
DRY_RUN=false
VERBOSE=false

# Print colored message
info() {
    echo -e "${BLUE}ℹ${NC} $*"
}

success() {
    echo -e "${GREEN}✓${NC} $*"
}

warn() {
    echo -e "${YELLOW}⚠${NC} $*"
}

error() {
    echo -e "${RED}✗${NC} $*" >&2
}

# Show usage
usage() {
    cat <<EOF
Upload CSV datasets to Phoenix for DIFY experiments

Usage:
  $(basename "$0") <csv-file> [dataset-name] [options]

Arguments:
  csv-file         Path to CSV file with questions and expected answers

Options:
  -n, --name NAME  Dataset name (default: auto-generated from filename)
  -u, --url URL    Phoenix URL (default: $PHOENIX_URL)
  -k, --api-key    Phoenix API key (default: PHOENIX_API_KEY env var)
  --dry-run        Preview without uploading
  --verbose        Enable verbose output
  -h, --help       Show this help

Environment Variables:
  PHOENIX_BASE_URL    Default Phoenix URL
  PHOENIX_API_KEY     API key for authentication

Examples:
  # Upload to local Phoenix
  $(basename "$0") my-dataset.csv

  # Upload with custom name
  $(basename "$0") my-dataset.csv "QA Dataset v2"

  # Upload to remote Phoenix
  PHOENIX_BASE_URL="http://ec2-host:6006" \\
  PHOENIX_API_KEY="phx_..." \\
    $(basename "$0") my-dataset.csv

  # Preview dataset before uploading
  $(basename "$0") my-dataset.csv --dry-run

Expected CSV Format:
  question,expected_answer
  "What is the capital of France?","Paris"
  "Who wrote Hamlet?","William Shakespeare"

  Supported column names:
    - Questions: question, query, input
    - Answers: expected_answer, answer, expected, output, reference
EOF
}

# Parse arguments
CSV_FILE=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        -n|--name)
            DATASET_NAME="$2"
            shift 2
            ;;
        -u|--url)
            PHOENIX_URL="$2"
            shift 2
            ;;
        -k|--api-key)
            export PHOENIX_API_KEY="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        -*)
            error "Unknown option: $1"
            usage
            exit 1
            ;;
        *)
            if [[ -z "$CSV_FILE" ]]; then
                CSV_FILE="$1"
            elif [[ -z "$DATASET_NAME" ]]; then
                DATASET_NAME="$1"
            else
                error "Unexpected argument: $1"
                usage
                exit 1
            fi
            shift
            ;;
    esac
done

# Validate CSV file argument
if [[ -z "$CSV_FILE" ]]; then
    error "Missing required argument: csv-file"
    usage
    exit 1
fi

if [[ ! -f "$CSV_FILE" ]]; then
    error "CSV file not found: $CSV_FILE"
    exit 1
fi

# Check for Python and required packages
if ! command -v python3 &> /dev/null; then
    error "Python 3 is required but not found"
    exit 1
fi

# Build Python command
PYTHON_SCRIPT="$SCRIPT_DIR/upload_dataset.py"

if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    error "Upload script not found: $PYTHON_SCRIPT"
    exit 1
fi

PYTHON_ARGS=("$CSV_FILE" "--phoenix-url" "$PHOENIX_URL")

if [[ -n "$DATASET_NAME" ]]; then
    PYTHON_ARGS+=("--name" "$DATASET_NAME")
fi

if [[ "$DRY_RUN" == "true" ]]; then
    PYTHON_ARGS+=("--dry-run")
fi

if [[ "$VERBOSE" == "true" ]]; then
    PYTHON_ARGS+=("--verbose")
fi

# Check if Phoenix is accessible (only for non-dry-run)
if [[ "$DRY_RUN" != "true" ]]; then
    info "Checking Phoenix connection at $PHOENIX_URL..."
    if ! curl -sf "${PHOENIX_URL}/healthz" &> /dev/null; then
        warn "Could not connect to Phoenix at $PHOENIX_URL"
        warn "Make sure Phoenix is running: docker compose ps phoenix"
        echo ""
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            error "Aborted"
            exit 1
        fi
    else
        success "Phoenix is running"
    fi
fi

# Run the upload
info "Running upload script..."
echo ""

if python3 "$PYTHON_SCRIPT" "${PYTHON_ARGS[@]}"; then
    exit 0
else
    error "Upload failed"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check that Python dependencies are installed:"
    echo "     pip install pandas arize-phoenix-client"
    echo "  2. Verify Phoenix is running:"
    echo "     curl ${PHOENIX_URL}/healthz"
    echo "  3. Check API key if using remote Phoenix:"
    echo "     echo \$PHOENIX_API_KEY"
    exit 1
fi
