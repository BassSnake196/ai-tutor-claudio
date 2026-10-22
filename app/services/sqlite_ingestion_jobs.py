"""Durable SQLite-backed ingestion job manager.

The public surface intentionally mirrors ``InMemoryIngestionJobManager``.  The
worker remains process-local, while every public snapshot is committed before
being returned.  A new process can therefore inspect completed jobs and can
close interrupted queued/running jobs with a safe, retryable public error.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
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


IngestionWorker = Callable[[ExternalIngestionRequest, ProgressReporter], Awaitable[ExternalIngestionResult]]


class PublicIngestionError(Exception):
    """Controlled exception whose sanitized error may reach API clients."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.public_error = IngestionJobError(code=code, message=message, retryable=retryable)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _snapshot(job: IngestionJob) -> IngestionJob:
    return job.model_copy(deep=True)


class SQLiteIngestionJobManager:
    """SQLite-persisted snapshots with bounded asynchronous execution."""

    def __init__(self, database: str | Path = "data/ingestion_jobs.sqlite3", *, max_concurrency: int = 2) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._database = str(database)
        if self._database != ":memory:":
            Path(self._database).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._db_lock = RLock()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._initialize()
        self._mark_interrupted_jobs()

    def _initialize(self) -> None:
        with self._db_lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    job_id TEXT PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_updated ON ingestion_jobs(updated_at DESC)"
            )
            self._connection.commit()

    def _rows(self) -> list[sqlite3.Row]:
        with self._db_lock:
            return self._connection.execute(
                "SELECT snapshot_json FROM ingestion_jobs ORDER BY updated_at DESC, job_id DESC"
            ).fetchall()

    def _load(self, job_id: str) -> IngestionJob | None:
        with self._db_lock:
            row = self._connection.execute(
                "SELECT snapshot_json FROM ingestion_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return IngestionJob.model_validate_json(row["snapshot_json"]) if row else None

    def _save(self, job: IngestionJob) -> None:
        with self._db_lock:
            self._connection.execute(
                """
                INSERT INTO ingestion_jobs(job_id, snapshot_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    snapshot_json=excluded.snapshot_json,
                    updated_at=excluded.updated_at
                """,
                (job.job_id, job.model_dump_json(), job.created_at.isoformat(), job.updated_at.isoformat()),
            )
            self._connection.commit()

    def _mark_interrupted_jobs(self) -> None:
        for row in self._rows():
            job = IngestionJob.model_validate_json(row["snapshot_json"])
            if job.status not in {IngestionJobStatus.QUEUED, IngestionJobStatus.RUNNING}:
                continue
            now = _utc_now()
            interrupted = job.model_copy(
                update={
                    "status": IngestionJobStatus.FAILED,
                    "started_at": job.started_at or job.created_at,
                    "completed_at": now,
                    "updated_at": now,
                    "progress": IngestionProgress(
                        stage="failed",
                        percent=job.progress.percent,
                        completed_items=job.progress.completed_items,
                        total_items=job.progress.total_items,
                    ),
                    "result": None,
                    "error": IngestionJobError(
                        code="JOB_INTERRUPTED",
                        message="La ingesta se interrumpió al reiniciar el servicio.",
                        retryable=True,
                    ),
                }
            )
            self._save(IngestionJob.model_validate(interrupted))

    async def submit(self, request: ExternalIngestionRequest, worker: IngestionWorker) -> IngestionJob:
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
            self._save(job)
            self._tasks[job.job_id] = asyncio.create_task(
                self._run(job.job_id, request, worker), name=f"sqlite-ingestion-{job.job_id}"
            )
        return _snapshot(job)

    async def get(self, job_id: str) -> IngestionJob | None:
        job = self._load(job_id)
        return _snapshot(job) if job is not None else None

    async def wait(self, job_id: str) -> IngestionJob | None:
        async with self._lock:
            task = self._tasks.get(job_id)
        if task is not None:
            await task
        return await self.get(job_id)

    async def list_jobs(self) -> list[IngestionJob]:
        return [IngestionJob.model_validate_json(row["snapshot_json"]) for row in self._rows()]

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        with self._db_lock:
            self._connection.close()

    async def _run(self, job_id: str, request: ExternalIngestionRequest, worker: IngestionWorker) -> None:
        try:
            async with self._semaphore:
                started = _utc_now()
                await self._replace(
                    job_id,
                    status=IngestionJobStatus.RUNNING,
                    started_at=started,
                    updated_at=started,
                    progress=IngestionProgress(stage="starting", percent=0),
                )

                async def report(progress: IngestionProgress) -> None:
                    current = await self.get(job_id)
                    if current is None or current.status is not IngestionJobStatus.RUNNING:
                        return
                    if progress.percent >= current.progress.percent:
                        await self._replace(job_id, progress=progress, updated_at=_utc_now())

                result = await worker(request, report)
                if result.source_id != request.source_id:
                    raise PublicIngestionError("SOURCE_ID_MISMATCH", "El resultado no corresponde a la fuente solicitada.")
                now = _utc_now()
                await self._replace(
                    job_id,
                    status=IngestionJobStatus.COMPLETED,
                    progress=IngestionProgress(
                        stage="completed", percent=100, completed_items=result.chunks_created,
                        total_items=max(1, result.chunks_created),
                    ),
                    result=result,
                    completed_at=now,
                    updated_at=now,
                )
        except asyncio.CancelledError:
            await self._mark_failed(job_id, IngestionJobError(code="JOB_CANCELLED", message="La ingesta fue cancelada.", retryable=True))
        except Exception as exc:  # noqa: BLE001 - worker boundary
            error = exc.public_error if isinstance(exc, PublicIngestionError) else IngestionJobError(
                code="INGESTION_FAILED", message="No se pudo completar la ingesta.", retryable=True
            )
            await self._mark_failed(job_id, error)

    async def _replace(self, job_id: str, **updates: object) -> IngestionJob:
        current = await self.get(job_id)
        if current is None:
            raise KeyError(job_id)
        updated = IngestionJob.model_validate({**current.model_dump(), **updates})
        self._save(updated)
        return _snapshot(updated)

    async def _mark_failed(self, job_id: str, error: IngestionJobError) -> None:
        current = await self.get(job_id)
        if current is None:
            return
        now = _utc_now()
        await self._replace(
            job_id,
            status=IngestionJobStatus.FAILED,
            started_at=current.started_at or now,
            completed_at=now,
            updated_at=now,
            progress=IngestionProgress(
                stage="failed", percent=current.progress.percent,
                completed_items=current.progress.completed_items, total_items=current.progress.total_items,
            ),
            result=None,
            error=error,
        )
