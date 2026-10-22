"""Workers that turn approved external requests into Qdrant sources."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.ai.interfaces.stt import SpeechToText
from app.rag.service import DuplicateDocumentError, RagService, SourceIdConflictError
from app.rag.web_ingestion import WebIngestionError, WebIngestionService
from app.rag.youtube_ingestion import (
    YouTubeIngestionError,
    YouTubeTranscriptIngestor,
    slice_transcript,
)
from app.schemas.external_sources import (
    ExternalIngestionRequest,
    ExternalIngestionResult,
    ExternalSourceType,
    IngestionProgress,
)
from app.services.ingestion_jobs import ProgressReporter, PublicIngestionError


class ExternalIngestionWorker:
    def __init__(
        self,
        *,
        rag: RagService,
        web: WebIngestionService,
        youtube: YouTubeTranscriptIngestor,
        speech_to_text: SpeechToText,
        audio_directory: Path,
        video_directory: Path,
    ) -> None:
        self._rag = rag
        self._web = web
        self._youtube = youtube
        self._speech_to_text = speech_to_text
        self._audio_directory = audio_directory.resolve()
        self._video_directory = video_directory.resolve()

    async def __call__(
        self,
        request: ExternalIngestionRequest,
        report: ProgressReporter,
    ) -> ExternalIngestionResult:
        try:
            if request.source_type is ExternalSourceType.WEB:
                return await self._web_job(request, report)
            if request.source_type is ExternalSourceType.YOUTUBE:
                return await self._youtube_job(request, report)
            return await self._audio_job(request, report)
        except (WebIngestionError, YouTubeIngestionError) as exc:
            raise PublicIngestionError(
                "SOURCE_UNAVAILABLE",
                str(exc),
                retryable=True,
            ) from exc
        except DuplicateDocumentError as exc:
            raise PublicIngestionError("DUPLICATE_SOURCE", str(exc)) from exc
        except SourceIdConflictError as exc:
            raise PublicIngestionError("SOURCE_ID_CONFLICT", str(exc)) from exc
        except FileNotFoundError as exc:
            raise PublicIngestionError("AUDIO_NOT_FOUND", "El audio cargado ya no existe.") from exc

    async def _web_job(
        self, request: ExternalIngestionRequest, report: ProgressReporter
    ) -> ExternalIngestionResult:
        assert request.url is not None
        await report(IngestionProgress(stage="safe_web_fetch", percent=15))
        document = await self._web.ingest(str(request.url))
        await report(IngestionProgress(stage="embedding", percent=65))
        indexed = await self._rag.index_external_text(
            document.content,
            source_id=request.source_id,
            title=request.title or document.title,
            source_type="web",
            url=document.final_url,
            library_id=request.library_id,
            course_id=request.course_id,
            language=document.language if document.language != "und" else request.language,
        )
        return await self._result(request, indexed.chunk_count)

    async def _youtube_job(
        self, request: ExternalIngestionRequest, report: ProgressReporter
    ) -> ExternalIngestionResult:
        assert request.url is not None
        await report(IngestionProgress(stage="youtube_download", percent=10))
        document = await self._youtube.ingest(
            str(request.url),
            source_id=request.source_id,
            target_directory=self._video_directory,
            language=request.language,
            start_time_seconds=request.start_time_seconds,
            end_time_seconds=request.end_time_seconds,
        )
        if request.title:
            document = replace(document, asset=replace(document.asset, title=request.title))
        await report(IngestionProgress(stage="embedding_transcript", percent=80))
        indexed = await self._rag.index_youtube_transcript(
            document,
            source_id=request.source_id,
            library_id=request.library_id,
            course_id=request.course_id,
            language=request.language,
        )
        return await self._result(
            request,
            indexed.chunk_count,
            detected_language=document.transcript.language,
            duration=document.transcript.duration_seconds,
        )

    async def _audio_job(
        self, request: ExternalIngestionRequest, report: ProgressReporter
    ) -> ExternalIngestionResult:
        assert request.file_reference is not None
        path = (self._audio_directory / request.file_reference).resolve()
        if not path.is_relative_to(self._audio_directory) or not path.is_file():
            raise FileNotFoundError(path)
        await report(IngestionProgress(stage="transcription", percent=20))
        transcript = await self._speech_to_text.transcribe(path)
        transcript = slice_transcript(
            transcript,
            start_time_seconds=request.start_time_seconds,
            end_time_seconds=request.end_time_seconds,
        )
        await report(IngestionProgress(stage="embedding_transcript", percent=80))
        indexed = await self._rag.index_audio_transcript(
            transcript,
            source_id=request.source_id,
            title=request.title or path.stem,
            storage_path=path,
            library_id=request.library_id,
            course_id=request.course_id,
            language=request.language,
        )
        return await self._result(
            request,
            indexed.chunk_count,
            detected_language=transcript.language,
            duration=transcript.duration_seconds,
        )

    async def _result(
        self,
        request: ExternalIngestionRequest,
        chunks: int,
        *,
        detected_language: str | None = None,
        duration: float | None = None,
    ) -> ExternalIngestionResult:
        record = await self._rag.get_source(request.source_id)
        return ExternalIngestionResult(
            source_id=request.source_id,
            document_id=record.document_id if record else None,
            chunks_created=chunks,
            detected_language=detected_language,
            media_duration_seconds=duration,
        )
