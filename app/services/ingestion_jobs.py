"""Bounded, process-local asynchronous ingestion job execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.schemas.external_sources import (
    ExternalIngestionRequest,
    ExternalIngestionResult,
    IngestionJob,
    IngestionJobError,
    IngestionJobStatus,
    IngestionProgress,
)


logger = logging.getLogger(__name__)


class ProgressReporter(Protocol):
    def __call__(self, progress: IngestionProgress) -> Awaitable[None]: ...


IngestionWorker = Callable[
    [ExternalIngestionRequest, ProgressReporter],
    Awaitable[ExternalIngestionResult],
]


class PublicIngestionError(Exception):
    """Controlled exception whose already-sanitized message may reach API clients."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.public_error = IngestionJobError(
            code=code,
            message=message,
            retryable=retryable,
        )


class InMemoryIngestionJobManager:
    """Run ingestion coroutines with bounded concurrency and isolated failures.

    State is intentionally process-local for the MVP. A restart loses job state, and
    multiple API workers do not share it; a durable queue can replace this service
    later without changing the public Pydantic contracts.
    """

    def __init__(self, *, max_concurrency: int = 2) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._lock = asyncio.Lock()
        self._jobs: dict[str, IngestionJob] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def submit(
        self,
        request: ExternalIngestionRequest,
        worker: IngestionWorker,
    ) -> IngestionJob:
        now = _utc_now()
        job = IngestionJob(
            job_id=uuid4().hex,
            source_type=request.source_type,
            source_id=request.source_id,
            status=IngestionJobStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._jobs[job.job_id] = job
            self._tasks[job.job_id] = asyncio.create_task(
                self._run(job.job_id, request, worker),
                name=f"ingestion-{job.job_id}",
            )
        logger.info(
            "ingestion_job_submitted job_id=%s source_id=%s source_type=%s",
            job.job_id,
            job.source_id,
            job.source_type.value,
        )
        return _snapshot(job)

    async def get(self, job_id: str) -> IngestionJob | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return _snapshot(job) if job is not None else None

    async def wait(self, job_id: str) -> IngestionJob | None:
        async with self._lock:
            task = self._tasks.get(job_id)
        if task is None:
            return None
        # _run consumes worker failures, so awaiting never re-raises them to the API.
        await task
        return await self.get(job_id)

    async def list_jobs(self) -> list[IngestionJob]:
        async with self._lock:
            return [_snapshot(job) for job in self._jobs.values()]

    async def shutdown(self) -> None:
        """Cancel unfinished process-local jobs during application shutdown."""
        async with self._lock:
            tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(
        self,
        job_id: str,
        request: ExternalIngestionRequest,
        worker: IngestionWorker,
    ) -> None:
        try:
            async with self._semaphore:
                started_at = _utc_now()
                await self._replace(
                    job_id,
                    status=IngestionJobStatus.RUNNING,
                    started_at=started_at,
                    updated_at=started_at,
                    progress=IngestionProgress(stage="starting", percent=0),
                )

                async def report(progress: IngestionProgress) -> None:
                    current = await self.get(job_id)
                    if current is None or current.status is not IngestionJobStatus.RUNNING:
                        return
                    # Do not let a delayed worker report turn a completed job backwards.
                    if progress.percent < current.progress.percent:
                        return
                    await self._replace(job_id, progress=progress, updated_at=_utc_now())

                result = await worker(request, report)
                if result.source_id != request.source_id:
                    raise PublicIngestionError(
                        "SOURCE_ID_MISMATCH",
                        "El resultado no corresponde a la fuente solicitada.",
                    )
                completed_at = _utc_now()
                await self._replace(
                    job_id,
                    status=IngestionJobStatus.COMPLETED,
                    progress=IngestionProgress(
                        stage="completed",
                        percent=100,
                        completed_items=result.chunks_created,
                        total_items=max(1, result.chunks_created),
                    ),
                    result=result,
                    completed_at=completed_at,
                    updated_at=completed_at,
                )
                logger.info(
                    "ingestion_job_completed job_id=%s source_id=%s chunks=%d",
                    job_id,
                    request.source_id,
                    result.chunks_created,
                )
        except asyncio.CancelledError:
            await self._mark_failed(
                job_id,
                IngestionJobError(
                    code="JOB_CANCELLED",
                    message="La ingesta fue cancelada.",
                    retryable=True,
                ),
            )
            # Cancellation belongs to manager shutdown, but state has already been
            # converted to a public failure and no raw worker exception escapes.
        except Exception as exc:  # noqa: BLE001 - task boundary must isolate workers
            public_error = (
                exc.public_error
                if isinstance(exc, PublicIngestionError)
                else IngestionJobError(
                    code="INGESTION_FAILED",
                    message="No se pudo completar la ingesta.",
                    retryable=True,
                )
            )
            await self._mark_failed(job_id, public_error)

    async def _mark_failed(self, job_id: str, error: IngestionJobError) -> None:
        current = await self.get(job_id)
        if current is None:
            return
        now = _utc_now()
        started_at = current.started_at or now
        await self._replace(
            job_id,
            status=IngestionJobStatus.FAILED,
            started_at=started_at,
            completed_at=now,
            updated_at=now,
            progress=IngestionProgress(
                stage="failed",
                percent=current.progress.percent,
                completed_items=current.progress.completed_items,
                total_items=current.progress.total_items,
            ),
            result=None,
            error=error,
        )
        logger.warning(
            "ingestion_job_failed job_id=%s code=%s retryable=%s",
            job_id,
            error.code,
            error.retryable,
        )

    async def _replace(self, job_id: str, **updates: object) -> IngestionJob:
        async with self._lock:
            current = self._jobs[job_id]
            payload = current.model_dump()
            payload.update(updates)
            updated = IngestionJob.model_validate(payload)
            self._jobs[job_id] = updated
            return _snapshot(updated)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _snapshot(job: IngestionJob) -> IngestionJob:
    return job.model_copy(deep=True)
