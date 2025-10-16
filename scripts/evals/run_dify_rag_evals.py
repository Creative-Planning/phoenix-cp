#!/usr/bin/env python
"""
Utility script that pulls Phoenix traces from a Dify RAG workflow, runs
relevance / hallucination (and optional QA correctness) evals, and logs the
results back to Phoenix so they appear in the UI.
"""

from __future__ import annotations

import argparse
import logging
import os
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any

import pandas as pd
import phoenix as px
from phoenix.evals import (
    HallucinationEvaluator,
    OpenAIModel,
    QAEvaluator,
    RelevanceEvaluator,
    run_evals,
)
from phoenix.session.evaluation import get_qa_with_reference, get_retrieved_documents
from phoenix.trace import DocumentEvaluations, SpanEvaluations
from phoenix.trace.dsl import SpanQuery
from httpx import ConnectError

LOGGER = logging.getLogger("phoenix.dify_evals")


def _extract_text_field(value: Any) -> str:
    """Normalize various Phoenix span payload shapes into plain text."""
    if value is None:
        return ""
    if isinstance(value, dict):
        if "value" in value:
            return _extract_text_field(value.get("value"))
        if "text" in value and isinstance(value["text"], str):
            return value["text"]
    if isinstance(value, list):
        parts = [_extract_text_field(item) for item in value]
        return "\n\n".join(part for part in parts if part)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        if isinstance(parsed, dict):
            for key in ("text", "answer", "output", "content", "value"):
                candidate = parsed.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            if "messages" in parsed and isinstance(parsed["messages"], list):
                return "\n\n".join(
                    msg.get("content", "") if isinstance(msg, dict) else str(msg)
                    for msg in parsed["messages"]
                ).strip()
            return json.dumps(parsed, ensure_ascii=False)
        if isinstance(parsed, list):
            return "\n\n".join(
                part for part in (_extract_text_field(item) for item in parsed) if part
            )
        return stripped
    return str(value)


def _extract_documents(value: Any) -> list[dict[str, Any]]:
    """Return a list of documents with reference text and optional score."""
    if value is None:
        return []
    raw = value
    if isinstance(raw, dict):
        if "documents" in raw:
            candidates = raw["documents"]
        elif "result" in raw and isinstance(raw["result"], list):
            candidates = raw["result"]
        elif "results" in raw and isinstance(raw["results"], list):
            candidates = raw["results"]
        elif "value" in raw:
            return _extract_documents(raw["value"])
        else:
            candidates = [raw]
    elif isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return []
        return _extract_documents(parsed)
    elif isinstance(raw, list):
        candidates = raw
    else:
        return []

    documents: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, dict):
            content = (
                candidate.get("content")
                or candidate.get("text")
                or candidate.get("page_content")
                or candidate.get("value")
            )
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            if content is None and metadata:
                content = metadata.get("content") or metadata.get("text")
            score = (
                candidate.get("score")
                or candidate.get("similarity")
                or candidate.get("relevance")
                or (metadata.get("score") if isinstance(metadata, dict) else None)
            )
        else:
            content = str(candidate)
            score = None

        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        elif isinstance(content, list):
            content = "\n".join(str(item) for item in content)

        if not content:
            continue
        documents.append({"reference": str(content), "document_score": score})
    return documents


def _build_dify_retrieval_dataframe(
    client: px.Client,
    project_name: str,
    start_time: datetime,
) -> pd.DataFrame | None:
    """Extract retriever spans emitted by Dify and format them for Phoenix evals."""
    spans = client.query_spans(
        SpanQuery().select("trace_id", "span_id", "parent_id", "name", "span_kind", "input", "output"),
        project_name=project_name,
        start_time=start_time,
        limit=10000,
    )
    if spans is None or spans.empty:
        return None

    spans = spans.reset_index(drop=False)
    candidate_spans = []
    rows: list[dict[str, Any]] = []
    for _, span in spans.iterrows():
        name = str(span.get("name", "") or "")
        span_kind = str(span.get("span_kind", "") or "")
        lower_name = name.lower()
        if not (
            "retrieval" in lower_name
            or span_kind.upper() in {"RETRIEVER", "TOOL"}
            or name in {"dataset_retrieval", "tool"}
        ):
            continue
        candidate_spans.append((name, span_kind))
        trace_id = span.get("context.trace_id") or span.get("trace_id")
        span_id = span.get("context.span_id") or span.get("span_id")
        query_text = _extract_text_field(span.get("input"))
        documents = _extract_documents(span.get("output"))
        for position, document in enumerate(documents):
            reference = document.get("reference")
            if not reference:
                continue
            rows.append(
                {
                    "context.trace_id": trace_id,
                    "context.span_id": span_id,
                    "document_position": position,
                    "input": query_text,
                    "reference": reference,
                    "document_score": document.get("document_score"),
                }
            )

    if not rows:
        if candidate_spans:
            LOGGER.debug(
                "Candidate retriever spans had no documents. Examples: %s",
                candidate_spans[:5],
            )
        else:
            LOGGER.debug(
                "No spans matched retrieval heuristics. Observed names=%s span_kinds=%s",
                spans.get("name", pd.Series(dtype=str)).dropna().unique()[:10],
                spans.get("span_kind", pd.Series(dtype=str)).dropna().unique()[:10],
            )
        return None

    dataframe = pd.DataFrame(rows)
    dataframe = dataframe.set_index(["context.span_id", "document_position"]).sort_index()
    return dataframe


def _build_dify_qa_dataframe(
    client: px.Client,
    project_name: str,
    start_time: datetime,
    retrieval_df: pd.DataFrame | None,
) -> pd.DataFrame | None:
    """Combine Dify message spans with their retrieved document references."""
    spans = client.query_spans(
        SpanQuery()
        .select("trace_id", "span_id", "parent_id", "name", "span_kind", "input", "output")
        .where("name in ['message', 'llm', 'workflow']"),
        project_name=project_name,
        start_time=start_time,
        limit=5000,
    )
    if spans is None or spans.empty:
        return None

    spans = spans.reset_index(drop=False)
    reference_lookup: dict[Any, str] = {}
    if retrieval_df is not None and not retrieval_df.empty:
        retrieval_reset = retrieval_df.reset_index()
        trace_col = "context.trace_id" if "context.trace_id" in retrieval_reset.columns else "trace_id"
        if "reference" in retrieval_reset.columns and trace_col in retrieval_reset.columns:
            reference_lookup = (
                retrieval_reset.groupby(trace_col)["reference"]
                .apply(
                    lambda series: "\n\n".join(str(ref) for ref in series if ref)
                )
                .to_dict()
            )

    rows: list[dict[str, Any]] = []
    for _, span in spans.iterrows():
        name = span.get("name")
        if name not in {"message", "llm", "workflow"}:
            continue
        question = _extract_text_field(span.get("input"))
        answer = _extract_text_field(span.get("output"))
        if not question and not answer:
            continue
        trace_id = span.get("context.trace_id") or span.get("trace_id")
        span_id = span.get("context.span_id") or span.get("span_id")
        rows.append(
            {
                "context.span_id": span_id,
                "context.trace_id": trace_id,
                "input": question,
                "output": answer,
                "reference": reference_lookup.get(trace_id, ""),
            }
        )

    if not rows:
        return None

    dataframe = pd.DataFrame(rows).set_index("context.span_id")
    return dataframe


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phoenix evals for a Dify RAG workflow.")
    parser.add_argument(
        "--project",
        default=os.getenv("PHOENIX_PROJECT", "default"),
        help="Phoenix project name containing the traces (default: %(default)s).",
    )
    parser.add_argument(
        "--since-minutes",
        type=int,
        default=int(os.getenv("EVAL_WINDOW_MINUTES", "60")),
        help="Look back window in minutes for traces to evaluate (default: %(default)s).",
    )
    parser.add_argument(
        "--model-name",
        default=os.getenv("EVAL_MODEL", "gpt-4o"),
        help="LLM used as the judge (default: %(default)s).",
    )
    parser.add_argument(
        "--skip-qa",
        action="store_true",
        help="Skip the Q&A correctness evaluator (relevance + hallucination still run).",
        default=False,
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Request explanations from the evaluators (adds latency and token cost).",
        default=False,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run evals but do not log annotations back to Phoenix.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Continuously execute using the configured interval.",
        default=False,
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("EVAL_INTERVAL_SECONDS", "900")),
        help="Delay between runs when --loop is set (default: %(default)s).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging for debugging.",
    )
    parser.add_argument(
        "--log-dir",
        default=os.getenv("EVAL_LOG_DIR"),
        help="Directory for verbose logs and eval artifacts. Defaults to 'logs/evals' when --verbose is set and no directory is provided.",
    )
    return parser.parse_args()


def _init_logging(verbose: bool, log_file: Path | None) -> None:
    log_level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def _get_window_start(minutes_back: int) -> datetime:
    minutes_back = max(minutes_back, 1)
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_back)


def _ensure_dataframe(name: str, dataframe):
    if dataframe is None or dataframe.empty:
        raise SystemExit(f"No {name} spans found for supplied window. Expand --since-minutes.")
    return dataframe


def main() -> None:
    args = _parse_args()
    if os.getenv("EVAL_SKIP_QA", "").lower() in {"1", "true", "yes"}:
        args.skip_qa = True
    if os.getenv("EVAL_EXPLAIN", "").lower() in {"1", "true", "yes"}:
        args.explain = True

    log_dir: Path | None = None
    if args.log_dir:
        log_dir = Path(args.log_dir).expanduser()
    elif args.verbose:
        log_dir = Path("logs/evals")

    log_file: Path | None = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "dify_rag_evals.log"

    args.log_dir = log_dir

    _init_logging(args.verbose, log_file)

    if args.loop:
        LOGGER.info(
            "Loop mode enabled. Interval: %s seconds | project=%s",
            args.interval_seconds,
            args.project,
        )
        while True:
            try:
                _run_once(args)
            except SystemExit as exc:
                LOGGER.warning("Eval run stopped: %s", exc)
            except Exception:
                LOGGER.exception("Unexpected error while running evals")
            sleep(max(args.interval_seconds, 1))
    else:
        _run_once(args)


def _run_once(args: argparse.Namespace) -> None:
    LOGGER.info("Starting Dify RAG evals | project=%s window=%s minutes", args.project, args.since_minutes)

    client = px.Client(warn_if_server_not_running=False)
    window_start = _get_window_start(args.since_minutes)

    run_artifact_dir: Path | None = None
    run_started_at = datetime.now(timezone.utc)
    run_timestamp = run_started_at.strftime("%Y%m%d_%H%M%S")
    if args.log_dir is not None:
        run_artifact_dir = Path(args.log_dir) / run_timestamp
        run_artifact_dir.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Verbose artifacts directory: %s", run_artifact_dir)
        metadata_path = run_artifact_dir / "metadata.json"
        with metadata_path.open("w", encoding="utf-8") as metadata_file:
            json.dump(
                {
                    "project": args.project,
                    "since_minutes": args.since_minutes,
                    "model_name": args.model_name,
                    "skip_qa": args.skip_qa,
                    "explain": args.explain,
                    "dry_run": args.dry_run,
                    "loop": args.loop,
                    "window_start_utc": window_start.isoformat(),
                    "artifact_dir": str(run_artifact_dir),
                    "run_timestamp_utc": run_started_at.isoformat(),
                },
                metadata_file,
                indent=2,
            )

    max_attempts = max(int(os.getenv("EVAL_CONNECT_RETRIES", "5")), 1)
    retry_delay = max(int(os.getenv("EVAL_CONNECT_RETRY_SECONDS", "10")), 1)

    qa_df = None
    retrieval_df = None
    for attempt in range(1, max_attempts + 1):
        try:
            LOGGER.debug("Fetching Phoenix spans attempt %d/%d", attempt, max_attempts)
            qa_df = get_qa_with_reference(client, project_name=args.project, start_time=window_start)
            retrieval_df = get_retrieved_documents(
                client,
                project_name=args.project,
                start_time=window_start,
            )
            break
        except ConnectError as exc:
            if attempt == max_attempts:
                raise SystemExit(f"Unable to reach Phoenix API after {max_attempts} attempts.") from exc
            LOGGER.warning(
                "Phoenix API unreachable (%s). Retry %d/%d in %d seconds.",
                exc,
                attempt,
                max_attempts,
                retry_delay,
            )
            sleep(retry_delay)
    else:
        return

    if retrieval_df is None or retrieval_df.empty:
        LOGGER.info("No retriever spans from Phoenix helper; attempting Dify fallback extraction.")
        retrieval_df = _build_dify_retrieval_dataframe(client, args.project, window_start)
    retrieval_df = _ensure_dataframe("retriever", retrieval_df)

    if qa_df is None or qa_df.empty:
        LOGGER.info("No QA spans from Phoenix helper; attempting Dify fallback extraction.")
        qa_df = _build_dify_qa_dataframe(client, args.project, window_start, retrieval_df)
    qa_df = _ensure_dataframe("QA", qa_df)

    model = OpenAIModel(model_name=args.model_name)

    LOGGER.info("Instantiated OpenAI evaluator model: %s", args.model_name)

    evals_to_run = []

    hallucination = HallucinationEvaluator(model)
    evals_to_run.append(("Hallucination", qa_df, [hallucination], SpanEvaluations))

    relevance = RelevanceEvaluator(model)
    evals_to_run.append(("Retrieval Relevance", retrieval_df, [relevance], DocumentEvaluations))

    if not args.skip_qa:
        qa_correctness = QAEvaluator(model)
        evals_to_run.append(("QA Correctness", qa_df, [qa_correctness], SpanEvaluations))

    logged_evals = []
    for eval_name, dataframe, evaluators, evaluation_cls in evals_to_run:
        LOGGER.info("Running %s evaluator on %d rows", eval_name, len(dataframe))
        results = run_evals(
            dataframe,
            evaluators=evaluators,
            provide_explanation=args.explain,
        )[0]
        if run_artifact_dir is not None:
            _write_eval_artifacts(run_artifact_dir, eval_name, dataframe, results)
        if args.dry_run:
            LOGGER.info("Dry run enabled, skipping log for %s", eval_name)
            continue
        LOGGER.debug("%s results head:\n%s", eval_name, results.head())
        logged_evals.append(evaluation_cls(eval_name=eval_name, dataframe=results))

    if not logged_evals:
        LOGGER.info("No evals to log (likely dry-run mode). Exiting.")
        return

    client.log_evaluations(*logged_evals)
    LOGGER.info("Logged %d evaluations back to Phoenix project '%s'.", len(logged_evals), args.project)


def _write_eval_artifacts(
    run_artifact_dir: Path,
    eval_name: str,
    input_dataframe: pd.DataFrame,
    results_dataframe: pd.DataFrame,
) -> None:
    """Persist evaluation inputs and outputs for auditing when verbose logging is enabled."""

    def _sanitize(name: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")
        return safe.lower() or "eval"

    prefix = _sanitize(eval_name)
    input_path = run_artifact_dir / f"{prefix}_input.csv"
    results_path = run_artifact_dir / f"{prefix}_results.csv"
    input_dataframe.to_csv(input_path)
    results_dataframe.to_csv(results_path)
    LOGGER.debug("Persisted %s artifacts to %s", eval_name, run_artifact_dir)


if __name__ == "__main__":
    main()
