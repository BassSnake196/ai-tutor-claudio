from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Tutor Claudio"
    app_env: str = "development"
    log_level: str = "INFO"

    ollama_base_url: HttpUrl = Field(default="http://localhost:11434")
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_seconds: float = Field(default=180, ge=10, le=600)
    ollama_critic_max_output_tokens: int = Field(default=768, ge=128, le=2_048)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"
    gemini_fallback_models: str = "gemini-3.1-flash-lite,gemini-2.5-flash-lite"
    gemini_structured_thinking_budget: int = Field(default=1_024, ge=0, le=8_192)
    gemini_structured_max_output_tokens: int = Field(default=8_192, ge=512, le=65_536)

    qdrant_url: HttpUrl = Field(default="http://localhost:6333")
    qdrant_collection: str = "tutor_documents"
    rag_min_score: float = Field(default=0.35, ge=0, le=1)
    rag_external_min_score: float = Field(default=0.0, ge=0, le=1)
    default_library_id: str = "default"
    curriculum_min_categories: int = Field(default=3, ge=1, le=4)
    curriculum_min_chunks: int = Field(default=4, ge=1, le=20)
    curriculum_max_context_chunks: int = Field(default=12, ge=1, le=30)
    curriculum_semantic_audit_enabled: bool = True
    embedding_model_name: str = "nomic-embed-text"
    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    curriculum_library_db_path: Path = Path("data/curriculum_library.sqlite3")
    ingestion_jobs_db_path: Path = Path("data/ingestion_jobs.sqlite3")

    external_search_enabled: bool = True
    external_search_results_per_query: int = Field(default=2, ge=1, le=5)
    external_search_concurrency: int = Field(default=3, ge=1, le=10)
    web_fetch_timeout_seconds: float = Field(default=12, gt=0, le=60)
    web_fetch_max_bytes: int = Field(default=2 * 1024 * 1024, ge=10_000, le=10 * 1024 * 1024)
    ingestion_job_concurrency: int = Field(default=2, ge=1, le=8)
    whisper_model_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    audio_storage_directory: Path = Path("data/videos_audio")
    youtube_storage_directory: Path = Path("data/videos_audio/youtube")
    youtube_maximum_duration_seconds: int = Field(default=7_200, ge=60, le=21_600)
    youtube_maximum_file_bytes: int = Field(
        default=500 * 1024 * 1024,
        ge=1_000_000,
        le=2 * 1024 * 1024 * 1024,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
