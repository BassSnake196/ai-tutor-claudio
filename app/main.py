from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ai.orchestrator import TutorOrchestrator
from app.ai.curriculum_orchestrator import CurriculumOrchestrator
from app.ai.registry import ModelRegistry
from app.ai.providers.faster_whisper import FasterWhisperSpeechToText
from app.api.routes.health import router as health_router
from app.api.routes.tutor import router as tutor_router
from app.api.routes.documents import router as documents_router
from app.api.routes.curricula import router as curricula_router
from app.api.routes.external_sources import router as external_sources_router
from app.api.routes.library import router as library_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.rag.service import RagService
from app.rag.vector_store import QdrantVectorStore
from app.rag.source_resolver import FilteredSearchBackendAdapter, SourceResolver
from app.rag.external_search import DuckDuckGoExternalSearchBackend
from app.rag.web_ingestion import WebIngestionService
from app.rag.youtube_ingestion import YouTubeDownloader, YouTubeTranscriptIngestor
from app.services.external_ingestion import ExternalIngestionWorker
from app.services.sqlite_ingestion_jobs import SQLiteIngestionJobManager
from app.services.sqlite_curriculum_library import SQLiteCurriculumLibrary


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    registry = ModelRegistry(settings)
    rag = RagService(
        embeddings=registry.embeddings(),
        vector_store=QdrantVectorStore(
            url=str(settings.qdrant_url),
            collection_name=settings.qdrant_collection,
        ),
    )
    app.state.rag = rag
    app.state.settings = settings
    app.state.curriculum_library = SQLiteCurriculumLibrary(settings.curriculum_library_db_path)
    app.state.orchestrator = TutorOrchestrator(
        registry,
        rag=rag,
        rag_min_score=settings.rag_min_score,
    )
    web_ingestion = WebIngestionService(
        timeout_seconds=settings.web_fetch_timeout_seconds,
        max_bytes=settings.web_fetch_max_bytes,
    )
    external_search = (
        DuckDuckGoExternalSearchBackend(
            web_ingestion=web_ingestion,
            maximum_concurrency=settings.external_search_concurrency,
            maximum_results_per_query=settings.external_search_results_per_query,
        )
        if settings.external_search_enabled
        else None
    )
    speech_to_text = FasterWhisperSpeechToText(
        model_size=settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    youtube_ingestion = YouTubeTranscriptIngestor(
        YouTubeDownloader(
            maximum_duration_seconds=settings.youtube_maximum_duration_seconds,
            maximum_file_bytes=settings.youtube_maximum_file_bytes,
        ),
        speech_to_text,
    )
    jobs = SQLiteIngestionJobManager(
        settings.ingestion_jobs_db_path,
        max_concurrency=settings.ingestion_job_concurrency,
    )
    app.state.ingestion_jobs = jobs
    app.state.audio_storage_directory = settings.audio_storage_directory.resolve()
    app.state.external_ingestion_worker = ExternalIngestionWorker(
        rag=rag,
        web=web_ingestion,
        youtube=youtube_ingestion,
        speech_to_text=speech_to_text,
        audio_directory=settings.audio_storage_directory,
        video_directory=settings.youtube_storage_directory,
    )
    app.state.curriculum_orchestrator = CurriculumOrchestrator(
        registry,
        resolver=SourceResolver(
            FilteredSearchBackendAdapter(rag, score_threshold=settings.rag_min_score),
            external_backend=external_search,
            min_score=settings.rag_min_score,
            external_min_score=settings.rag_external_min_score,
            max_context_chunks=settings.curriculum_max_context_chunks,
            minimum_categories=settings.curriculum_min_categories,
            minimum_chunks=settings.curriculum_min_chunks,
        ),
        source_catalog=rag,
        semantic_audit_enabled=settings.curriculum_semantic_audit_enabled,
    )
    try:
        yield
    finally:
        await jobs.shutdown()
        app.state.curriculum_library.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(tutor_router)
    app.include_router(documents_router)
    app.include_router(curricula_router)
    app.include_router(external_sources_router)
    app.include_router(library_router)
    return app


app = create_app()
