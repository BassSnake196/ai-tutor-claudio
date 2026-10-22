"""Asynchronous web, YouTube and uploaded-audio ingestion endpoints."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import ValidationError

from app.schemas.external_sources import (
    ExternalIngestionRequest,
    ExternalSourceType,
    IngestionJob,
)
from app.services.external_ingestion import ExternalIngestionWorker
from app.services.ingestion_jobs import InMemoryIngestionJobManager


router = APIRouter(prefix="/v1/external-sources", tags=["external-sources"])
ALLOWED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".mp4", ".flac"}
MAX_AUDIO_BYTES = 500 * 1024 * 1024
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


@router.post("", response_model=IngestionJob, status_code=status.HTTP_202_ACCEPTED)
async def submit_external_source(
    payload: ExternalIngestionRequest,
    request: Request,
) -> IngestionJob:
    if payload.source_type is ExternalSourceType.FILE_AUDIO:
        raise HTTPException(
            status_code=422,
            detail="Los audios locales deben enviarse mediante /v1/external-sources/audio.",
        )
    manager: InMemoryIngestionJobManager = request.app.state.ingestion_jobs
    worker: ExternalIngestionWorker = request.app.state.external_ingestion_worker
    return await manager.submit(payload, worker)


@router.post("/audio", response_model=IngestionJob, status_code=status.HTTP_202_ACCEPTED)
async def submit_audio_source(
    request: Request,
    file: UploadFile = File(...),
    source_id: str = Form(...),
    library_id: str = Form(default="default"),
    course_id: str | None = Form(default=None),
    language: str = Form(default="es"),
    title: str | None = Form(default=None),
) -> IngestionJob:
    if not SAFE_ID.fullmatch(source_id):
        raise HTTPException(status_code=422, detail="source_id tiene un formato inválido.")
    suffix = Path(file.filename or "").suffix.casefold()
    if suffix not in ALLOWED_AUDIO_SUFFIXES:
        raise HTTPException(status_code=415, detail="Formato de audio o video no permitido.")

    directory: Path = request.app.state.audio_storage_directory
    directory.mkdir(parents=True, exist_ok=True)
    reference = f"{uuid4().hex}{suffix}"
    target = (directory / reference).resolve()
    if not target.is_relative_to(directory.resolve()):
        raise HTTPException(status_code=422, detail="Destino de audio inválido.")

    settings = getattr(request.app.state, "settings", None)
    maximum_bytes = int(getattr(settings, "youtube_maximum_file_bytes", MAX_AUDIO_BYTES))
    total = 0
    try:
        with target.open("xb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > maximum_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"El archivo supera el límite de {maximum_bytes} bytes.",
                    )
                output.write(chunk)
        payload = ExternalIngestionRequest(
            source_type=ExternalSourceType.FILE_AUDIO,
            source_id=source_id,
            file_reference=reference,
            library_id=library_id,
            course_id=course_id,
            language=language,
            title=title or file.filename or source_id,
        )
        manager: InMemoryIngestionJobManager = request.app.state.ingestion_jobs
        worker: ExternalIngestionWorker = request.app.state.external_ingestion_worker
        return await manager.submit(payload, worker)
    except ValidationError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except Exception:
        target.unlink(missing_ok=True)
        raise


@router.get("/jobs", response_model=list[IngestionJob])
async def list_ingestion_jobs(request: Request) -> list[IngestionJob]:
    manager: InMemoryIngestionJobManager = request.app.state.ingestion_jobs
    return await manager.list_jobs()


@router.get("/jobs/{job_id}", response_model=IngestionJob)
async def get_ingestion_job(job_id: str, request: Request) -> IngestionJob:
    manager: InMemoryIngestionJobManager = request.app.state.ingestion_jobs
    job = await manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El trabajo de ingesta no existe.")
    return job
