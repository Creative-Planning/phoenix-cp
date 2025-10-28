#!/usr/bin/env python
"""
Upload a CSV dataset to Phoenix for use with DIFY experiments.

This script simplifies uploading Q&A datasets (questions + expected answers)
to Phoenix, whether running locally or on a remote EC2 instance.

Usage:
    # Upload to local Phoenix
    python scripts/datasets/upload_dataset.py my-dataset.csv

    # Upload to remote Phoenix with custom name
    python scripts/datasets/upload_dataset.py my-dataset.csv \
        --name "qa-dataset-v2" \
        --phoenix-url "http://ec2-host:6006" \
        --api-key "your-key"

    # Specify custom column names
    python scripts/datasets/upload_dataset.py my-dataset.csv \
        --input-keys "user_query" \
        --output-keys "gold_answer" \
        --metadata-keys "topic,difficulty"

    # Preview dataset without uploading
    python scripts/datasets/upload_dataset.py my-dataset.csv --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import pandas as pd
except ImportError:
    print("Error: pandas is required. Install with: pip install pandas")
    sys.exit(1)

try:
    from phoenix.client import Client
except ImportError:
    print("Error: arize-phoenix-client is required. Install with: pip install arize-phoenix-client")
    sys.exit(1)

LOGGER = logging.getLogger("phoenix.upload_dataset")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload CSV dataset to Phoenix for DIFY experiments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload to local Phoenix with auto-generated name
  python scripts/datasets/upload_dataset.py my-qa-data.csv

  # Upload to remote Phoenix with custom name
  python scripts/datasets/upload_dataset.py my-qa-data.csv \\
      --name "customer-support-qa-v1" \\
      --phoenix-url "http://ec2-12-34-56-78.us-west-2.compute.amazonaws.com:6006" \\
      --api-key "phx_abc123..."

  # Upload with custom column names
  python scripts/datasets/upload_dataset.py my-qa-data.csv \\
      --input-keys "user_question" \\
      --output-keys "correct_answer" \\
      --metadata-keys "category,priority"

Expected CSV format (questions + expected answers):
  question,expected_answer
  "What is the capital of France?","Paris"
  "Who wrote Hamlet?","William Shakespeare"

Supported column names:
  - Input (questions): question, query, input
  - Output (expected answers): expected_answer, answer, expected, output, reference
        """
    )

    parser.add_argument(
        "csv_file",
        type=Path,
        help="Path to CSV file containing dataset (questions + expected answers)",
    )

    parser.add_argument(
        "--name",
        help="Dataset name in Phoenix (default: auto-generated from filename and timestamp)",
    )

    parser.add_argument(
        "--description",
        help="Optional description for the dataset",
    )

    parser.add_argument(
        "--phoenix-url",
        default=os.getenv("PHOENIX_BASE_URL", "http://localhost:6006"),
        help="Phoenix base URL (default: %(default)s or PHOENIX_BASE_URL env var)",
    )

    parser.add_argument(
        "--api-key",
        default=os.getenv("PHOENIX_API_KEY"),
        help="Phoenix API key (default: PHOENIX_API_KEY env var). Required for remote access.",
    )

    parser.add_argument(
        "--input-keys",
        default="question",
        help="Comma-separated list of CSV columns to use as input (default: question)",
    )

    parser.add_argument(
        "--output-keys",
        default="expected_answer",
        help="Comma-separated list of CSV columns to use as output (default: expected_answer)",
    )

    parser.add_argument(
        "--metadata-keys",
        default="",
        help="Comma-separated list of CSV columns to use as metadata (optional)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the dataset without uploading to Phoenix",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args()


def _setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity level."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def _generate_dataset_name(csv_file: Path) -> str:
    """Generate a dataset name from the CSV filename and current timestamp."""
    base_name = csv_file.stem
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base_name}-{timestamp}"


def _validate_csv_file(csv_file: Path) -> None:
    """Validate that the CSV file exists and is readable."""
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    if not csv_file.is_file():
        raise ValueError(f"Path is not a file: {csv_file}")

    if csv_file.suffix.lower() not in ['.csv', '.txt']:
        LOGGER.warning(f"File extension is {csv_file.suffix}, expected .csv")


def _validate_columns(
    df: pd.DataFrame,
    input_keys: list[str],
    output_keys: list[str],
    metadata_keys: list[str],
) -> None:
    """Validate that the specified columns exist in the DataFrame."""
    all_keys = input_keys + output_keys + metadata_keys
    missing = [key for key in all_keys if key not in df.columns]

    if missing:
        available = ", ".join(df.columns)
        raise ValueError(
            f"Columns not found in CSV: {', '.join(missing)}\n"
            f"Available columns: {available}"
        )


def _preview_dataset(
    df: pd.DataFrame,
    input_keys: list[str],
    output_keys: list[str],
    metadata_keys: list[str],
) -> None:
    """Display a preview of the dataset to the user."""
    print("\n" + "=" * 80)
    print("DATASET PREVIEW")
    print("=" * 80)
    print(f"Total examples: {len(df)}")
    print(f"Input columns: {', '.join(input_keys)}")
    print(f"Output columns: {', '.join(output_keys)}")
    if metadata_keys:
        print(f"Metadata columns: {', '.join(metadata_keys)}")
    print("\nFirst 3 examples:")
    print("-" * 80)

    preview_df = df.head(3)
    for idx, row in preview_df.iterrows():
        print(f"\nExample {idx + 1}:")
        print(f"  Input:")
        for key in input_keys:
            value = str(row[key])[:100]  # Truncate long values
            print(f"    {key}: {value}")
        print(f"  Output:")
        for key in output_keys:
            value = str(row[key])[:100]
            print(f"    {key}: {value}")
        if metadata_keys:
            print(f"  Metadata:")
            for key in metadata_keys:
                value = str(row[key])[:100]
                print(f"    {key}: {value}")

    print("=" * 80 + "\n")


def main() -> int:
    """Main entry point for the upload script."""
    args = _parse_args()
    _setup_logging(args.verbose)

    # Validate CSV file
    try:
        _validate_csv_file(args.csv_file)
    except (FileNotFoundError, ValueError) as e:
        LOGGER.error(str(e))
        return 1

    # Parse column keys
    input_keys = [k.strip() for k in args.input_keys.split(",") if k.strip()]
    output_keys = [k.strip() for k in args.output_keys.split(",") if k.strip()]
    metadata_keys = [k.strip() for k in args.metadata_keys.split(",") if k.strip()]

    # Load CSV
    LOGGER.info(f"Loading CSV file: {args.csv_file}")
    try:
        df = pd.read_csv(args.csv_file)
        LOGGER.info(f"Loaded {len(df)} rows with columns: {', '.join(df.columns)}")
    except Exception as e:
        LOGGER.error(f"Failed to load CSV: {e}")
        return 1

    # Validate columns exist
    try:
        _validate_columns(df, input_keys, output_keys, metadata_keys)
    except ValueError as e:
        LOGGER.error(str(e))
        return 1

    # Generate dataset name if not provided
    dataset_name = args.name or _generate_dataset_name(args.csv_file)

    # Preview dataset
    _preview_dataset(df, input_keys, output_keys, metadata_keys)

    if args.dry_run:
        LOGGER.info("DRY RUN: Would upload dataset with name: %s", dataset_name)
        LOGGER.info("DRY RUN: Target Phoenix URL: %s", args.phoenix_url)
        return 0

    # Connect to Phoenix
    LOGGER.info(f"Connecting to Phoenix at: {args.phoenix_url}")
    try:
        client = Client(base_url=args.phoenix_url, api_key=args.api_key)
    except Exception as e:
        LOGGER.error(f"Failed to connect to Phoenix: {e}")
        LOGGER.error("Make sure Phoenix is running and the API key is correct")
        return 1

    # Upload dataset
    LOGGER.info(f"Uploading dataset: {dataset_name}")
    try:
        dataset = client.datasets.create_dataset(
            name=dataset_name,
            dataframe=df,
            input_keys=input_keys,
            output_keys=output_keys,
            metadata_keys=metadata_keys if metadata_keys else None,
            dataset_description=args.description,
        )
    except Exception as e:
        LOGGER.error(f"Failed to upload dataset: {e}")
        return 1

    # Success!
    print("\n" + "=" * 80)
    print("✓ UPLOAD SUCCESSFUL!")
    print("=" * 80)
    print(f"Dataset name: {dataset.name}")
    print(f"Dataset ID: {dataset.id}")
    print(f"Examples uploaded: {len(dataset)}")
    print(f"Phoenix URL: {args.phoenix_url}/datasets/{dataset.id}")
    print("\nNext steps:")
    print(f"  1. View in Phoenix UI: {args.phoenix_url}/datasets")
    print(f"  2. Run experiment:")
    print(f'     ./scripts/experiments/run_experiment.sh \\')
    print(f'       --dataset "{dataset.name}" \\')
    print(f'       "baseline-v1"')
    print("=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
