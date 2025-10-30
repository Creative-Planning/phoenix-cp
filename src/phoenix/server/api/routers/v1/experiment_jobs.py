from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from strawberry.relay import GlobalID

from phoenix.db import models
from phoenix.server.api.routers.v1.models import V1RoutesBaseModel
from phoenix.server.api.types.node import from_global_id_with_expected_type
from phoenix.server.authorization import is_not_locked

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ExperimentScript:
    key: str
    label: str
    description: str
    command: tuple[str, ...]


_ALLOWED_SCRIPTS: Dict[str, _ExperimentScript] = {
    "run_dify_experiment": _ExperimentScript(
        key="run_dify_experiment",
        label="Run Dify Retrieval Experiment",
        description=(
            "Execute scripts/experiments/run_dify_experiment.py using the selected dataset. "
            "Requires Dify and evaluator credentials to be configured via environment variables."
        ),
        command=("-m", "scripts.experiments.run_dify_experiment"),
    ),
}

_LOG_DIR = Path(os.getenv("PHOENIX_EXPERIMENT_LOG_DIR", "logs/experiment_runs"))
_LOG_DIR.mkdir(parents=True, exist_ok=True)


class ExperimentScript(V1RoutesBaseModel):
    key: str
    label: str
    description: str


class ListExperimentScriptsResponse(V1RoutesBaseModel):
    data: list[ExperimentScript]


class RunExperimentRequestBody(V1RoutesBaseModel):
    script_key: str = Field(alias="scriptKey")
    experiment_name: Optional[str] = Field(default=None, alias="experimentName")
    dry_run: Optional[int] = Field(default=None, alias="dryRun", ge=1)
    skip_qa: bool = Field(default=False, alias="skipQa")
    explain: bool = Field(default=False, alias="explain")


class RunExperimentResponseBody(V1RoutesBaseModel):
    job_id: str = Field(alias="jobId")
    status: str
    log_url: str = Field(alias="logUrl")
    status_url: str = Field(alias="statusUrl")


class ExperimentJob(V1RoutesBaseModel):
    job_id: str = Field(alias="jobId")
    dataset_id: str = Field(alias="datasetId")
    dataset_name: str = Field(alias="datasetName")
    script_key: str = Field(alias="scriptKey")
    command: list[str]
    status: str
    created_at: datetime = Field(alias="createdAt")
    finished_at: Optional[datetime] = Field(default=None, alias="finishedAt")
    return_code: Optional[int] = Field(default=None, alias="returnCode")
    log_path: str = Field(alias="logPath")
    error_message: Optional[str] = Field(default=None, alias="errorMessage")


class ListExperimentJobsResponse(V1RoutesBaseModel):
    data: list[ExperimentJob]


_jobs: Dict[str, ExperimentJob] = {}
_jobs_lock = asyncio.Lock()

router = APIRouter(tags=["experiments"], include_in_schema=True)


def _get_script_or_404(script_key: str) -> _ExperimentScript:
    script = _ALLOWED_SCRIPTS.get(script_key)
    if script is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown experiment script '{script_key}'.",
        )
    return script


async def _resolve_dataset(request: Request, dataset_id: str) -> tuple[str, str]:
    try:
        dataset_gid = GlobalID.from_id(dataset_id)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid dataset ID format: {dataset_id}",
        ) from exc
    try:
        dataset_rowid = from_global_id_with_expected_type(dataset_gid, "Dataset")
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset with ID {dataset_id} does not exist.",
        ) from exc
    async with request.app.state.db() as session:
        dataset = await session.scalar(
            select(models.Dataset).where(models.Dataset.id == dataset_rowid)
        )
        if dataset is None:
            raise HTTPException(
                status_code=404,
                detail=f"Dataset with ID {dataset_id} does not exist.",
            )
    return str(dataset_gid), dataset.name


async def _run_job(job: ExperimentJob) -> None:
    async with _jobs_lock:
        _jobs[job.job_id] = job.model_copy()
    log_path = Path(job.log_path)
    command = job.command
    # Ensure parent directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)
    job_copy = job.model_copy()
    job_copy.status = "running"
    async with _jobs_lock:
        _jobs[job.job_id] = job_copy
    try:
        # Open file in thread-safe manner using to_thread to avoid blocking event loop.
        log_file = await asyncio.to_thread(
            lambda: open(log_path, "w", encoding="utf-8", buffering=1)
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=log_file,
                stderr=log_file,
            )
            return_code = await process.wait()
        finally:
            await asyncio.to_thread(log_file.close)
        status = "succeeded" if return_code == 0 else "failed"
        job_copy.status = status
        job_copy.return_code = return_code
    except Exception as exc:  # pragma: no cover - defensive
        job_copy.status = "failed"
        job_copy.error_message = str(exc)
    finally:
        job_copy.finished_at = datetime.now(timezone.utc)
        async with _jobs_lock:
            _jobs[job.job_id] = job_copy


@router.get(
    "/experiment-scripts",
    response_model=ListExperimentScriptsResponse,
    response_model_by_alias=True,
    dependencies=[Depends(is_not_locked)],
)
async def list_experiment_scripts() -> ListExperimentScriptsResponse:
    return ListExperimentScriptsResponse(
        data=[
            ExperimentScript(key=script.key, label=script.label, description=script.description)
            for script in _ALLOWED_SCRIPTS.values()
        ]
    )


@router.get(
    "/experiment-jobs",
    response_model=ListExperimentJobsResponse,
    response_model_by_alias=True,
    dependencies=[Depends(is_not_locked)],
)
async def list_experiment_jobs(
    limit: int = Query(default=50, ge=1, le=200),
) -> ListExperimentJobsResponse:
    async with _jobs_lock:
        jobs = list(_jobs.values())
    jobs.sort(key=lambda job: job.created_at, reverse=True)
    return ListExperimentJobsResponse(data=jobs[:limit])


@router.post(
    "/datasets/{dataset_id}/run-experiment",
    response_model=RunExperimentResponseBody,
    response_model_by_alias=True,
    status_code=202,
    dependencies=[Depends(is_not_locked)],
)
async def run_experiment(
    request: Request,
    dataset_id: str,
    request_body: RunExperimentRequestBody,
) -> RunExperimentResponseBody:
    logger.info(
        "Run experiment requested dataset_id=%s script_key=%s name=%s dry_run=%s skip_qa=%s explain=%s",
        dataset_id,
        request_body.script_key,
        request_body.experiment_name,
        request_body.dry_run,
        request_body.skip_qa,
        request_body.explain,
    )
    script = _get_script_or_404(request_body.script_key)
    dataset_global_id, dataset_name = await _resolve_dataset(request, dataset_id)

    job_id = str(uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = _LOG_DIR / f"{timestamp}_{job_id}.log"

    command = [sys.executable, *script.command, "--dataset-name", dataset_name]
    if request_body.experiment_name:
        command.extend(["--experiment-name", request_body.experiment_name])
    if request_body.dry_run is not None:
        command.extend(["--dry-run", str(request_body.dry_run)])
    if request_body.skip_qa:
        command.append("--skip-qa")
    if request_body.explain:
        command.append("--explain")

    job = ExperimentJob(
        jobId=job_id,
        datasetId=dataset_global_id,
        datasetName=dataset_name,
        scriptKey=script.key,
        command=command,
        status="queued",
        createdAt=datetime.now(timezone.utc),
        logPath=str(log_path),
    )

    async with _jobs_lock:
        _jobs[job_id] = job

    asyncio.create_task(_run_job(job))

    status_url = f"/v1/experiment-jobs/{job_id}"
    log_url = f"{status_url}/log"
    return RunExperimentResponseBody(
        jobId=job_id,
        status="queued",
        logUrl=log_url,
        statusUrl=status_url,
    )


@router.get(
    "/experiment-jobs/{job_id}",
    response_model=ExperimentJob,
    response_model_by_alias=True,
    dependencies=[Depends(is_not_locked)],
)
async def get_experiment_job(job_id: str) -> ExperimentJob:
    async with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Experiment job '{job_id}' not found.")
    return job


@router.get(
    "/experiment-jobs/{job_id}/log",
    response_class=PlainTextResponse,
    dependencies=[Depends(is_not_locked)],
)
async def get_experiment_job_log(job_id: str) -> PlainTextResponse:
    async with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Experiment job '{job_id}' not found.")
    log_path = Path(job.log_path)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found.")
    # Read log asynchronously to avoid blocking the event loop
    try:
        content = await asyncio.to_thread(log_path.read_text, encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Log file not found.") from None
    return PlainTextResponse(content=content, media_type="text/plain; charset=utf-8")
