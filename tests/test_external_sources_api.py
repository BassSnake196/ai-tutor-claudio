import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.external_sources import router
from app.schemas.external_sources import ExternalIngestionResult
from app.services.ingestion_jobs import InMemoryIngestionJobManager


async def successful_worker(request, report):
    return ExternalIngestionResult(source_id=request.source_id, chunks_created=2)


def test_web_job_submission_and_status_lookup(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.ingestion_jobs = InMemoryIngestionJobManager()
    app.state.external_ingestion_worker = successful_worker
    app.state.audio_storage_directory = tmp_path

    with TestClient(app) as client:
        response = client.post(
            "/v1/external-sources",
            json={
                "source_type": "WEB",
                "source_id": "web-api-test",
                "url": "https://example.edu/lesson",
            },
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        for _ in range(20):
            status_response = client.get(f"/v1/external-sources/jobs/{job_id}")
            if status_response.json()["status"] == "COMPLETED":
                break
            time.sleep(0.01)

    assert status_response.status_code == 200
    assert status_response.json()["result"]["chunks_created"] == 2


def test_audio_upload_is_stored_under_managed_directory(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.ingestion_jobs = InMemoryIngestionJobManager()
    app.state.external_ingestion_worker = successful_worker
    app.state.audio_storage_directory = tmp_path

    with TestClient(app) as client:
        response = client.post(
            "/v1/external-sources/audio",
            data={"source_id": "audio-api-test", "language": "es"},
            files={"file": ("clase.mp3", b"fake-audio", "audio/mpeg")},
        )

    assert response.status_code == 202
    stored = list(tmp_path.glob("*.mp3"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == b"fake-audio"


def test_rejects_file_audio_on_json_endpoint_and_unknown_job(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.ingestion_jobs = InMemoryIngestionJobManager()
    app.state.external_ingestion_worker = successful_worker
    app.state.audio_storage_directory = tmp_path

    with TestClient(app) as client:
        invalid = client.post(
            "/v1/external-sources",
            json={
                "source_type": "FILE_AUDIO",
                "source_id": "audio-api-test",
                "file_reference": "audio.mp3",
            },
        )
        missing = client.get("/v1/external-sources/jobs/unknown")

    assert invalid.status_code == 422
    assert missing.status_code == 404
