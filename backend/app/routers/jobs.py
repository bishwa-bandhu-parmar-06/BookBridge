"""Job status polling: GET /api/jobs/{job_id}."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas import ErrorResponse, JobResponse
from app.services.jobs import JobRegistry, get_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse, responses={404: {"model": ErrorResponse}})
def get_job(job_id: str, jobs: JobRegistry = Depends(get_jobs)) -> JobResponse:
    return JobResponse(**jobs.get(job_id).public())
