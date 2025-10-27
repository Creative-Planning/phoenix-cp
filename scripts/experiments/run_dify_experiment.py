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
import inspect
import logging
import os
import sys
from typing import Any

import httpx
from phoenix.client import Client, __version__ as phoenix_client_version
from phoenix.evals import BedrockModel, OpenAIModel
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
        "--eval-provider",
        default=os.getenv("EVAL_PROVIDER", "openai"),
        choices=("openai", "bedrock"),
        help="LLM provider for evaluations (default: %(default)s).",
    )
    parser.add_argument(
        "--bedrock-region",
        default=os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION"),
        help="AWS region to use with the Bedrock provider (falls back to AWS_REGION env).",
    )
    parser.add_argument(
        "--bedrock-profile",
        default=os.getenv("BEDROCK_PROFILE"),
        help="Optional AWS profile name to use with the Bedrock provider.",
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
    parser.add_argument(
        "--project-name",
        default=os.getenv("PHOENIX_PROJECT_NAME", "dify-experiments"),
        help="Phoenix project name for organizing traces (default: %(default)s).",
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
        # Support various common column names
        if isinstance(input, dict):
            query = (
                input.get("question")
                or input.get("query")
                or input.get("input")
                or input.get("sys.query")  # Phoenix trace exports
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


def build_eval_model(
    provider: str,
    model_name: str,
    *,
    bedrock_region: str | None = None,
    bedrock_profile: str | None = None,
) -> Any:
    """
    Create the evaluation model used by Phoenix evaluators.

    Supports OpenAI (default) and AWS Bedrock providers.
    """
    normalized_provider = provider.lower()

    if normalized_provider == "openai":
        return OpenAIModel(model_name=model_name)

    if normalized_provider == "bedrock":
        session = None

        if bedrock_profile or bedrock_region:
            try:
                import boto3  # type: ignore
            except ImportError as exc:  # pragma: no cover - nicer error for missing dep
                raise RuntimeError(
                    "boto3 is required to use the Bedrock eval provider."
                ) from exc

            session_kwargs: dict[str, str] = {}
            if bedrock_profile:
                session_kwargs["profile_name"] = bedrock_profile
            if bedrock_region:
                session_kwargs["region_name"] = bedrock_region

            session = boto3.session.Session(**session_kwargs)

        model_kwargs: dict[str, Any] = {"model_id": model_name}
        if session is not None:
            model_kwargs["session"] = session

        return BedrockModel(**model_kwargs)

    raise ValueError(f"Unsupported eval provider '{provider}'.")


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


def setup_llm_evaluators(model: Any, model_name: str, skip_qa: bool = False) -> list:
    """
    Set up custom LLM evaluators that wrap Phoenix legacy evaluators.

    These evaluators extract answer/retrieved_docs from the task output dict
    and use the legacy evaluators for the actual LLM-as-judge evaluation.
    """
    from phoenix.evals import (
        HallucinationEvaluator as LegacyHallucinationEvaluator,
        RelevanceEvaluator as LegacyRelevanceEvaluator,
        QAEvaluator as LegacyQAEvaluator,
    )

    evaluators = []

    # Hallucination evaluator: checks if answer contradicts retrieved documents
    legacy_hallucination = LegacyHallucinationEvaluator(model)

    @create_evaluator(name="hallucination", kind="LLM")
    def hallucination_evaluator(output: dict, input: dict) -> tuple[float, str]:
        """
        Evaluate if the DIFY answer hallucinates given the retrieved documents.

        Args:
            output: Task output dict with keys: output (answer), reference (docs), metadata
            input: Dataset input dict with the question

        Returns:
            (score, explanation) tuple
        """
        if not isinstance(output, dict):
            return (0.0, "Error: task output is not a dict")

        answer = output.get("output", "")
        retrieved_docs = output.get("reference", "")
        # Support various common column names for questions
        question = (
            input.get("question")
            or input.get("query")
            or input.get("input")
            or input.get("sys.query")  # Phoenix trace exports use this
            or ""
        )

        if not answer:
            return (0.0, "No answer provided")
        if not retrieved_docs:
            return (0.0, "No retrieved documents to check against")

        # Build a record compatible with legacy evaluator
        record = {
            "input": question,
            "output": answer,
            "reference": retrieved_docs,
        }

        # Call legacy evaluator
        label, score, explanation = legacy_hallucination.evaluate(record, provide_explanation=True)

        return (score or 0.0, explanation or f"Label: {label}")

    evaluators.append(hallucination_evaluator)

    # Relevance evaluator: checks if retrieved documents are relevant to the query
    legacy_relevance = LegacyRelevanceEvaluator(model)

    @create_evaluator(name="relevance", kind="LLM")
    def relevance_evaluator(output: dict, input: dict) -> tuple[float, str]:
        """
        Evaluate if the retrieved documents are relevant to the question.

        Args:
            output: Task output dict with retrieved documents
            input: Dataset input dict with the question

        Returns:
            (score, explanation) tuple
        """
        if not isinstance(output, dict):
            return (0.0, "Error: task output is not a dict")

        retrieved_docs = output.get("reference", "")
        # Support various common column names for questions
        question = (
            input.get("question")
            or input.get("query")
            or input.get("input")
            or input.get("sys.query")  # Phoenix trace exports use this
            or ""
        )

        if not retrieved_docs:
            return (0.0, "No retrieved documents")
        if not question:
            return (0.0, "No question provided")

        # Build a record compatible with legacy evaluator
        record = {
            "input": question,
            "reference": retrieved_docs,
        }

        # Call legacy evaluator
        label, score, explanation = legacy_relevance.evaluate(record, provide_explanation=True)

        return (score or 0.0, explanation or f"Label: {label}")

    evaluators.append(relevance_evaluator)

    # Q&A evaluator: checks if answer is correct given expected answer
    # Only works if dataset has "expected" output field
    if not skip_qa:
        legacy_qa = LegacyQAEvaluator(model)

        @create_evaluator(name="qa_correctness", kind="LLM")
        def qa_evaluator(output: dict, input: dict, expected: dict | None = None) -> tuple[float, str]:
            """
            Evaluate if the DIFY answer is correct compared to expected answer.

            Args:
                output: Task output dict with the answer
                input: Dataset input dict with the question
                expected: Dataset output dict with expected answer (if present)

            Returns:
                (score, explanation) tuple
            """
            if not isinstance(output, dict):
                return (0.0, "Error: task output is not a dict")

            answer = output.get("output", "")
            # Support various common column names for questions
            question = (
                input.get("question")
                or input.get("query")
                or input.get("input")
                or input.get("sys.query")  # Phoenix trace exports use this
                or ""
            )

            if not answer:
                return (0.0, "No answer provided")
            if not question:
                return (0.0, "No question provided")

            # Check if we have expected answer
            if not expected or not isinstance(expected, dict):
                return (0.0, "No expected answer in dataset - cannot evaluate correctness")

            # Support various common column names for expected answers
            expected_answer = (
                expected.get("expected_answer")
                or expected.get("answer")
                or expected.get("expected")
                or expected.get("output")
                or expected.get("reference")  # GBA FAQ uses this
                or ""
            )
            if not expected_answer:
                return (0.0, "Expected answer field is empty")

            # Build a record compatible with legacy evaluator
            record = {
                "input": question,
                "output": answer,
                "reference": expected_answer,  # For Q&A, reference is the gold answer
            }

            # Call legacy evaluator
            label, score, explanation = legacy_qa.evaluate(record, provide_explanation=True)

            return (score or 0.0, explanation or f"Label: {label}")

        evaluators.append(qa_evaluator)
        LOGGER.info("Q&A correctness evaluator included (requires expected answer in dataset)")

    LOGGER.info(
        "Initialized %d LLM evaluators with model: %s (%s)",
        len(evaluators),
        model_name,
        model.__class__.__name__,
    )

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
    LOGGER.info("Evaluation provider: %s", args.eval_provider)
    LOGGER.info("Evaluation model: %s", args.eval_model)
    if args.eval_provider.lower() == "bedrock":
        if args.bedrock_region:
            LOGGER.info("Bedrock region: %s", args.bedrock_region)
        if args.bedrock_profile:
            LOGGER.info("Bedrock profile: %s", args.bedrock_profile)

    # Initialize Phoenix client and enable tracing
    phoenix_client = Client()
    register(project_name=args.project_name)  # Auto-instruments OpenAI calls in evaluators

    phoenix_url = os.getenv("PHOENIX_BASE_URL", "http://localhost:6006")
    LOGGER.info("Connected to Phoenix at: %s", phoenix_url)
    LOGGER.info("Phoenix project: %s", args.project_name)

    # Load the dataset
    if args.dataset_id:
        LOGGER.info("Loading dataset by ID: %s", args.dataset_id)
        dataset_id = args.dataset_id
        dataset_name = args.dataset_id  # Will be updated when we fetch metadata
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

        dataset_id = matching[0]["id"]
        dataset_name = matching[0]["name"]

    LOGGER.info("Using dataset: %s (ID: %s)", dataset_name, dataset_id)

    # Workaround: Manually construct Dataset object because get_dataset() returns 500 error
    # The Phoenix server has a bug where example_count is None, causing validation to fail
    # We'll fetch examples directly and use the dataset_info from list()
    LOGGER.debug("Fetching dataset examples...")
    examples_response = phoenix_client._client.get(
        f"v1/datasets/{dataset_id}/examples",
        headers={"accept": "application/json"},
    )
    examples_response.raise_for_status()
    examples_data = examples_response.json()["data"]

    # Import Dataset class to construct it manually
    from phoenix.client.resources.datasets import Dataset

    # Use dataset metadata from list() response (which doesn't have example_count)
    dataset_info = matching[0] if not args.dataset_id else {"id": dataset_id, "name": dataset_name}
    dataset = Dataset(dataset_info, examples_data)

    LOGGER.info("Loaded dataset with %d examples", len(dataset))

    # Create the task runner
    task = DifyTaskRunner(
        base_url=args.dify_base_url,
        api_key=args.dify_api_key,
        timeout=args.timeout,
        user_id=args.user_id,
    )

    # Set up evaluators
    custom_evaluators = create_custom_evaluators()
    try:
        eval_model = build_eval_model(
            args.eval_provider,
            args.eval_model,
            bedrock_region=args.bedrock_region,
            bedrock_profile=args.bedrock_profile,
        )
    except Exception as exc:
        LOGGER.error("Failed to initialize evaluation model: %s", exc)
        sys.exit(1)

    if args.eval_provider.lower() == "bedrock" and args.eval_model == "gpt-4o":
        LOGGER.warning(
            "The default OpenAI model '%s' is not available on Bedrock. "
            "Set --eval-model to a valid Bedrock model identifier (e.g., 'anthropic.claude-3-5-haiku-20241022-v1:0').",
            args.eval_model,
        )

    llm_evaluators = setup_llm_evaluators(eval_model, args.eval_model, skip_qa=args.skip_qa)

    all_evaluators = custom_evaluators + llm_evaluators

    LOGGER.info("Configured %d evaluators total", len(all_evaluators))

    # Run the experiment
    LOGGER.info("Running experiment...")

    experiment_params = {
        "dataset": dataset,
        "task": task,
        "evaluators": all_evaluators,
        "project_name": args.project_name,
    }

    run_experiment_sig = inspect.signature(phoenix_client.experiments.run_experiment)
    if "project_name" not in run_experiment_sig.parameters:
        LOGGER.warning(
            "Phoenix client %s does not support project-aware experiments; default project will be used.",
            phoenix_client_version,
        )
        experiment_params.pop("project_name")

    if args.experiment_name:
        experiment_params["experiment_name"] = args.experiment_name

    if args.dry_run:
        LOGGER.info("DRY RUN mode: testing with %d examples", args.dry_run)
        experiment_params["dry_run"] = args.dry_run

    try:
        experiment = phoenix_client.experiments.run_experiment(**experiment_params)

        LOGGER.info("✓ Experiment completed successfully!")

        # Handle both object-style and dict-style responses from the Phoenix client
        experiment_id = getattr(experiment, "id", None)
        experiment_name = getattr(experiment, "name", None)

        if experiment_id is None and isinstance(experiment, dict):
            experiment_id = experiment.get("id") or experiment.get("experimentId")
            experiment_name = experiment_name or experiment.get("name")

        LOGGER.info("Experiment ID: %s", experiment_id or "<unknown>")
        LOGGER.info("Experiment name: %s", experiment_name or "<unnamed>")

        # Print experiment URL (only if we have an ID)
        if experiment_id:
            base_url = phoenix_url.rstrip('/')
            # Remove /graphql or /v1 suffix if present
            if base_url.endswith('/graphql'):
                base_url = base_url[:-8]
            elif base_url.endswith('/v1'):
                base_url = base_url[:-3]

            experiment_url = (
                f"{base_url}/datasets/{dataset_id}/compare"
                f"?experimentId={experiment_id}"
            )
            LOGGER.info("View results: %s", experiment_url)
        else:
            LOGGER.warning("Experiment ID missing from response; skipping result URL generation")

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
