import asyncio

import pytest
from pydantic import ValidationError

from app.schemas.external_sources import (
    ExternalIngestionRequest,
    ExternalIngestionResult,
    ExternalSourceType,
    IngestionJobError,
    IngestionJobStatus,
    IngestionProgress,
)
from app.services.ingestion_jobs import (
    InMemoryIngestionJobManager,
    PublicIngestionError,
)


def web_request(**updates: object) -> ExternalIngestionRequest:
    values: dict[str, object] = {
        "source_type": ExternalSourceType.WEB,
        "source_id": "didactica-algebra",
        "url": "https://example.edu/algebra",
        "library_id": "default",
        "language": "es-MX",
    }
    values.update(updates)
    return ExternalIngestionRequest(**values)


def test_contracts_accept_each_external_source_type() -> None:
    web = web_request()
    youtube = ExternalIngestionRequest(
        source_type=ExternalSourceType.YOUTUBE,
        source_id="video-1",
        url="https://youtu.be/abcdefghijk",
        language="es",
        start_time_seconds=10,
        end_time_seconds=80,
    )
    audio = ExternalIngestionRequest(
        source_type=ExternalSourceType.FILE_AUDIO,
        source_id="audio-1",
        file_reference="upload-01.mp3",
        language="en-US",
    )

    assert str(web.url).startswith("https://")
    assert youtube.end_time_seconds == 80
    assert audio.file_reference == "upload-01.mp3"


@pytest.mark.parametrize(
    "values",
    [
        {"source_type": "WEB", "source_id": "web-1"},
        {
            "source_type": "YOUTUBE",
            "source_id": "video-1",
            "url": "https://videos.example.com/watch/1",
        },
        {"source_type": "FILE_AUDIO", "source_id": "audio-1"},
        {
            "source_type": "FILE_AUDIO",
            "source_id": "audio-1",
            "file_reference": "../secret.mp3",
        },
        {
            "source_type": "WEB",
            "source_id": "bad id",
            "url": "https://example.edu",
        },
        {
            "source_type": "WEB",
            "source_id": "web-1",
            "url": "https://example.edu",
            "language": "invalid_language",
        },
        {
            "source_type": "YOUTUBE",
            "source_id": "video-1",
            "url": "https://youtube.com/watch?v=abcdefghijk",
            "start_time_seconds": 20,
            "end_time_seconds": 10,
        },
    ],
)
def test_request_rejects_unsafe_or_incoherent_inputs(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExternalIngestionRequest(**values)


def test_request_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        web_request(api_key="must-not-be-accepted")


def test_progress_rejects_invalid_counts() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        IngestionProgress(percent=50, completed_items=3, total_items=2)


@pytest.mark.asyncio
async def test_manager_executes_worker_and_exposes_progress_and_timestamps() -> None:
    manager = InMemoryIngestionJobManager(max_concurrency=1)

    async def worker(request: ExternalIngestionRequest, report: object) -> ExternalIngestionResult:
        await report(  # type: ignore[operator]
            IngestionProgress(
                stage="chunking",
                percent=60,
                completed_items=3,
                total_items=5,
            )
        )
        return ExternalIngestionResult(source_id=request.source_id, chunks_created=5)

    queued = await manager.submit(web_request(), worker)
    finished = await manager.wait(queued.job_id)

    assert queued.status is IngestionJobStatus.QUEUED
    assert finished is not None
    assert finished.status is IngestionJobStatus.COMPLETED
    assert finished.progress.percent == 100
    assert finished.result is not None and finished.result.chunks_created == 5
    assert finished.started_at is not None
    assert finished.completed_at is not None
    assert finished.created_at <= finished.started_at <= finished.completed_at


@pytest.mark.asyncio
async def test_manager_limits_worker_concurrency() -> None:
    manager = InMemoryIngestionJobManager(max_concurrency=2)
    active = 0
    maximum_active = 0
    release = asyncio.Event()
    two_started = asyncio.Event()

    async def worker(request: ExternalIngestionRequest, report: object) -> ExternalIngestionResult:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        if active == 2:
            two_started.set()
        await release.wait()
        active -= 1
        return ExternalIngestionResult(source_id=request.source_id, chunks_created=1)

    queued = [
        await manager.submit(
            web_request(source_id=f"source-{index}", url=f"https://example.edu/{index}"),
            worker,
        )
        for index in range(4)
    ]
    await asyncio.wait_for(two_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert maximum_active == 2
    snapshots = await manager.list_jobs()
    assert sum(item.status is IngestionJobStatus.RUNNING for item in snapshots) == 2
    assert sum(item.status is IngestionJobStatus.QUEUED for item in snapshots) == 2

    release.set()
    await asyncio.gather(*(manager.wait(item.job_id) for item in queued))
    assert all(
        item.status is IngestionJobStatus.COMPLETED for item in await manager.list_jobs()
    )


@pytest.mark.asyncio
async def test_arbitrary_worker_exception_is_sanitized_and_does_not_escape() -> None:
    manager = InMemoryIngestionJobManager()
    secret = "AIza-not-a-real-key"

    async def worker(request: ExternalIngestionRequest, report: object) -> ExternalIngestionResult:
        raise RuntimeError(f"provider failed using {secret} at C:/private/file")

    queued = await manager.submit(web_request(), worker)
    failed = await manager.wait(queued.job_id)

    assert failed is not None
    assert failed.status is IngestionJobStatus.FAILED
    assert failed.error == IngestionJobError(
        code="INGESTION_FAILED",
        message="No se pudo completar la ingesta.",
        retryable=True,
    )
    assert secret not in failed.model_dump_json()
    assert "C:/private" not in failed.model_dump_json()


@pytest.mark.asyncio
async def test_controlled_public_error_preserves_only_declared_public_fields() -> None:
    manager = InMemoryIngestionJobManager()

    async def worker(request: ExternalIngestionRequest, report: object) -> ExternalIngestionResult:
        raise PublicIngestionError(
            "DOWNLOAD_BLOCKED",
            "La fuente rechazó la descarga.",
            retryable=False,
        )

    queued = await manager.submit(web_request(), worker)
    failed = await manager.wait(queued.job_id)

    assert failed is not None and failed.error is not None
    assert failed.error.code == "DOWNLOAD_BLOCKED"
    assert failed.error.message == "La fuente rechazó la descarga."
    assert failed.error.retryable is False


@pytest.mark.asyncio
async def test_manager_returns_none_for_unknown_job() -> None:
    manager = InMemoryIngestionJobManager()

    assert await manager.get("missing") is None
    assert await manager.wait("missing") is None


def test_manager_rejects_zero_concurrency() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        InMemoryIngestionJobManager(max_concurrency=0)
