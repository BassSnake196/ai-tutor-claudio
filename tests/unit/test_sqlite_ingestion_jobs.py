import asyncio

import pytest

from app.schemas.external_sources import (
    ExternalIngestionRequest,
    ExternalIngestionResult,
    IngestionJobStatus,
    IngestionProgress,
)
from app.services.sqlite_ingestion_jobs import SQLiteIngestionJobManager


def request() -> ExternalIngestionRequest:
    return ExternalIngestionRequest(
        source_type="WEB", source_id="web-durable", url="https://example.edu/material"
    )


@pytest.mark.asyncio
async def test_completed_job_survives_new_manager(tmp_path) -> None:
    database = tmp_path / "jobs.sqlite3"
    manager = SQLiteIngestionJobManager(database)

    async def worker(req, report):
        await report(IngestionProgress(stage="download", percent=50))
        return ExternalIngestionResult(source_id=req.source_id, chunks_created=2)

    queued = await manager.submit(request(), worker)
    finished = await manager.wait(queued.job_id)
    assert finished is not None and finished.status is IngestionJobStatus.COMPLETED
    await manager.shutdown()

    recovered_manager = SQLiteIngestionJobManager(database)
    recovered = await recovered_manager.get(queued.job_id)
    assert recovered == finished
    assert await recovered_manager.wait(queued.job_id) == finished
    await recovered_manager.shutdown()


@pytest.mark.asyncio
async def test_restart_marks_running_job_interrupted_and_retryable(tmp_path) -> None:
    database = tmp_path / "jobs.sqlite3"
    manager = SQLiteIngestionJobManager(database)
    job = await manager.submit(request(), lambda req, report: asyncio.sleep(10))
    await asyncio.sleep(0.02)
    # Simulate an abrupt process death: do not call shutdown, so the snapshot
    # remains RUNNING in SQLite for the next manager instance.
    manager._connection.close()  # noqa: SLF001 - deliberate crash simulation
    manager._tasks[job.job_id].cancel()  # noqa: SLF001 - finish the local test task
    await asyncio.gather(manager._tasks[job.job_id], return_exceptions=True)  # noqa: SLF001

    recovered_manager = SQLiteIngestionJobManager(database)
    recovered = await recovered_manager.get(job.job_id)
    assert recovered is not None
    assert recovered.status is IngestionJobStatus.FAILED
    assert recovered.error is not None
    assert recovered.error.code == "JOB_INTERRUPTED"
    assert recovered.error.retryable is True
    await recovered_manager.shutdown()


@pytest.mark.asyncio
async def test_list_jobs_returns_persisted_snapshots(tmp_path) -> None:
    database = tmp_path / "jobs.sqlite3"
    manager = SQLiteIngestionJobManager(database)

    async def worker(req, report):
        return ExternalIngestionResult(source_id=req.source_id, chunks_created=1)

    job = await manager.submit(request(), worker)
    await manager.wait(job.job_id)
    await manager.shutdown()
    recovered = SQLiteIngestionJobManager(database)
    jobs = await recovered.list_jobs()
    assert [item.job_id for item in jobs] == [job.job_id]
    await recovered.shutdown()
