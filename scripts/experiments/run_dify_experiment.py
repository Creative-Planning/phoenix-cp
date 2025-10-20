#!/usr/bin/env python
"""
Run experiments on DIFY workflow using Phoenix datasets and evaluators.

This script:
1. Loads an existing Phoenix dataset (with prompts/questions)
2. Defines a task that calls the DIFY chat API
3. Runs evaluators (Relevance, Hallucination, Q&A) on the results
4. Logs everything to Phoenix for comparison across workflow iterations

Usage:
    python scripts/experiments/run_dify_experiment.py --dataset-name "Good 2025-10-20T14:32:32.450Z"

    # With custom DIFY endpoint and API key
    python scripts/experiments/run_dify_experiment.py \
        --dataset-name "Good 2025-10-20T14:32:32.450Z" \
        --dify-base-url "http://localhost/v1" \
        --dify-api-key "your-api-key"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

import httpx
from phoenix.client import Client
from phoenix.evals import (
    HallucinationEvaluator,
    OpenAIModel,
    QAEvaluator,
    RelevanceEvaluator,
)
from phoenix.experiments.evaluators import create_evaluator
from phoenix.otel import register

LOGGER = logging.getLogger("phoenix.dify_experiment")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phoenix experiments on DIFY workflow."
    )
    parser.add_argument(
        "--dataset-name",
        required=True,
        help="Name of the existing Phoenix dataset to use for the experiment.",
    )
    parser.add_argument(
        "--dataset-id",
        help="Dataset ID (alternative to --dataset-name). Use if you know the ID.",
    )
    parser.add_argument(
        "--dify-base-url",
        default=os.getenv("DIFY_BASE_URL", "http://localhost/v1"),
        help="DIFY API base URL (default: %(default)s).",
    )
    parser.add_argument(
        "--dify-api-key",
        default=os.getenv("DIFY_API_KEY"),
        help="DIFY API key for authentication. Can also use DIFY_API_KEY env var.",
    )
    parser.add_argument(
        "--experiment-name",
        help="Custom name for this experiment run. Auto-generated if not provided.",
    )
    parser.add_argument(
        "--eval-model",
        default=os.getenv("EVAL_MODEL", "gpt-4o"),
        help="LLM model to use as judge for evaluations (default: %(default)s).",
    )
    parser.add_argument(
        "--skip-qa",
        action="store_true",
        help="Skip the Q&A correctness evaluator (only run relevance + hallucination).",
        default=False,
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Request explanations from LLM evaluators (increases cost/latency).",
        default=False,
    )
    parser.add_argument(
        "--dry-run",
        type=int,
        metavar="N",
        help="Run experiment on only N examples for testing (e.g., --dry-run 3).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout in seconds for DIFY API calls (default: %(default)s).",
    )
    parser.add_argument(
        "--user-id",
        default="experiment-user",
        help="User identifier to send to DIFY (default: %(default)s).",
    )
    return parser.parse_args()


def _init_logging(verbose: bool) -> None:
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


class DifyTaskRunner:
    """Handles calling the DIFY workflow API and formatting responses."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 60,
        user_id: str = "experiment-user",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.user_id = user_id
        self.client = httpx.Client(timeout=timeout)

    def __call__(self, input: dict[str, Any] | str) -> dict[str, Any]:
        """
        Task function that Phoenix experiments will call for each dataset example.

        Args:
            input: The input from the dataset example. Can be a dict with keys like
                   'question', 'query', etc., or a simple string.

        Returns:
            A dict containing:
                - output: The AI response text
                - reference: Retrieved documents (for hallucination/relevance eval)
                - metadata: Additional info (conversation_id, task_id, etc.)
                - error: Any error message if the call failed
        """
        # Extract the query/question from input
        if isinstance(input, dict):
            query = (
                input.get("question")
                or input.get("query")
                or input.get("input")
                or input.get("text")
                or str(input)
            )
        else:
            query = str(input)

        LOGGER.debug("Calling DIFY API with query: %s", query[:100])

        # Prepare request payload
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",  # Use blocking mode for simpler handling
            "conversation_id": "",  # Empty = new conversation each time
            "user": self.user_id,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self.client.post(
                f"{self.base_url}/chat-messages",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            # Extract the answer
            answer = data.get("answer", "")

            # Extract retriever resources (documents) if available
            metadata = data.get("metadata", {})
            retriever_resources = metadata.get("retriever_resources", [])

            # Format retrieved documents as reference text for evaluators
            reference_texts = []
            for doc in retriever_resources:
                content = doc.get("content", "")
                if content:
                    reference_texts.append(content)

            reference = "\n\n".join(reference_texts) if reference_texts else ""

            result = {
                "output": answer,
                "reference": reference,
                "metadata": {
                    "conversation_id": data.get("conversation_id"),
                    "message_id": data.get("message_id"),
                    "task_id": data.get("task_id"),
                    "usage": metadata.get("usage"),
                    "retriever_count": len(retriever_resources),
                },
                "error": None,
            }

            LOGGER.debug(
                "DIFY response received: %d chars, %d docs retrieved",
                len(answer),
                len(retriever_resources),
            )

            return result

        except httpx.HTTPStatusError as exc:
            error_msg = f"HTTP {exc.response.status_code}: {exc.response.text}"
            LOGGER.error("DIFY API error: %s", error_msg)
            return {
                "output": "",
                "reference": "",
                "metadata": {},
                "error": error_msg,
            }
        except Exception as exc:
            error_msg = f"Unexpected error: {type(exc).__name__}: {exc}"
            LOGGER.error("Task execution error: %s", error_msg)
            return {
                "output": "",
                "reference": "",
                "metadata": {},
                "error": error_msg,
            }


def create_custom_evaluators() -> list:
    """Create custom code evaluators specific to DIFY workflow."""

    @create_evaluator(name="has_answer", kind="CODE")
    def has_answer(output: dict) -> bool:
        """Check if the DIFY workflow returned a non-empty answer."""
        return bool(output.get("output", "").strip())

    @create_evaluator(name="no_error", kind="CODE")
    def no_error(output: dict) -> bool:
        """Check if the DIFY API call completed without errors."""
        return not bool(output.get("error"))

    @create_evaluator(name="has_retrieval", kind="CODE")
    def has_retrieval(output: dict) -> bool:
        """Check if documents were retrieved from the knowledge base."""
        return bool(output.get("reference", "").strip())

    @create_evaluator(name="retrieval_count", kind="CODE")
    def retrieval_count(output: dict) -> int:
        """Count how many documents were retrieved."""
        metadata = output.get("metadata", {})
        return metadata.get("retriever_count", 0)

    return [has_answer, no_error, has_retrieval, retrieval_count]


def setup_llm_evaluators(model_name: str) -> list:
    """Set up Phoenix LLM evaluators for RAG quality assessment."""
    model = OpenAIModel(model_name=model_name)

    evaluators = []

    # Hallucination: checks if the output contradicts the retrieved documents
    hallucination_eval = HallucinationEvaluator(model)
    evaluators.append(hallucination_eval)

    # Relevance: checks if retrieved documents are relevant to the query
    relevance_eval = RelevanceEvaluator(model)
    evaluators.append(relevance_eval)

    LOGGER.info("Initialized LLM evaluators with model: %s", model_name)

    return evaluators


def main() -> None:
    args = _parse_args()
    _init_logging(args.verbose)

    # Validate API key
    if not args.dify_api_key:
        LOGGER.error(
            "DIFY API key is required. Set via --dify-api-key or DIFY_API_KEY env var."
        )
        sys.exit(1)

    LOGGER.info("Starting DIFY experiment runner")
    LOGGER.info("Dataset: %s", args.dataset_name or args.dataset_id)
    LOGGER.info("DIFY URL: %s", args.dify_base_url)

    # Initialize Phoenix client and enable tracing
    phoenix_client = Client()
    register()  # Auto-instruments OpenAI calls in evaluators

    phoenix_url = os.getenv("PHOENIX_BASE_URL", "http://localhost:6006")
    LOGGER.info("Connected to Phoenix at: %s", phoenix_url)

    # Load the dataset
    if args.dataset_id:
        LOGGER.info("Loading dataset by ID: %s", args.dataset_id)
        dataset = phoenix_client.datasets.get_dataset(dataset=args.dataset_id)
    else:
        LOGGER.info("Loading dataset by name: %s", args.dataset_name)
        # List datasets and find by name
        datasets = list(phoenix_client.datasets.list())
        matching = [d for d in datasets if d["name"] == args.dataset_name]

        if not matching:
            LOGGER.error(
                "Dataset '%s' not found. Available datasets: %s",
                args.dataset_name,
                [d["name"] for d in datasets],
            )
            sys.exit(1)

        if len(matching) > 1:
            LOGGER.warning(
                "Multiple datasets found with name '%s'. Using the most recent one.",
                args.dataset_name,
            )

        # Get the full dataset object using the ID
        dataset = phoenix_client.datasets.get_dataset(dataset=matching[0]["id"])

    LOGGER.info("Loaded dataset: %s (ID: %s)", dataset.name, dataset.id)
    LOGGER.info("Dataset has %d examples", len(dataset))

    # Create the task runner
    task = DifyTaskRunner(
        base_url=args.dify_base_url,
        api_key=args.dify_api_key,
        timeout=args.timeout,
        user_id=args.user_id,
    )

    # Set up evaluators
    custom_evaluators = create_custom_evaluators()
    llm_evaluators = setup_llm_evaluators(args.eval_model)

    # Note: Q&A evaluator needs expected answers in the dataset, which may not be present
    if not args.skip_qa:
        LOGGER.info("Q&A evaluator will be included (requires 'expected' or 'answer' in dataset)")
        model = OpenAIModel(model_name=args.eval_model)
        qa_eval = QAEvaluator(model)
        llm_evaluators.append(qa_eval)

    all_evaluators = custom_evaluators + llm_evaluators

    LOGGER.info("Configured %d evaluators total", len(all_evaluators))

    # Run the experiment
    LOGGER.info("Running experiment...")

    experiment_params = {
        "dataset": dataset,
        "task": task,
        "evaluators": all_evaluators,
    }

    if args.experiment_name:
        experiment_params["experiment_name"] = args.experiment_name

    if args.dry_run:
        LOGGER.info("DRY RUN mode: testing with %d examples", args.dry_run)
        experiment_params["dry_run"] = args.dry_run

    try:
        experiment = phoenix_client.experiments.run_experiment(**experiment_params)

        LOGGER.info("✓ Experiment completed successfully!")
        LOGGER.info("Experiment ID: %s", experiment.id)
        LOGGER.info("Experiment name: %s", experiment.name)

        # Print experiment URL
        base_url = phoenix_url.rstrip('/')
        # Remove /graphql or /v1 suffix if present
        if base_url.endswith('/graphql'):
            base_url = base_url[:-8]
        elif base_url.endswith('/v1'):
            base_url = base_url[:-3]

        experiment_url = (
            f"{base_url}/datasets/{dataset.id}/compare"
            f"?experimentId={experiment.id}"
        )
        LOGGER.info("View results: %s", experiment_url)

        LOGGER.info(
            "\nYou can now view the experiment results in the Phoenix UI."
        )
        LOGGER.info(
            "Compare this experiment with others to see how workflow changes affect quality."
        )

    except Exception as exc:
        LOGGER.exception("Experiment failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
