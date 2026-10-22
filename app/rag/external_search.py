"""Free, bounded external research over public web pages and YouTube captions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

from app.rag.web_ingestion import WebDocument, WebIngestionService
from app.rag.youtube_ingestion import (
    YouTubeCaptionService,
    YouTubeIngestionError,
    chunk_transcript,
)


SearchCallable = Callable[[str, int], Sequence[dict[str, Any]]]


@dataclass(frozen=True)
class ExternalSearchResult:
    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any]


class DuckDuckGoExternalSearchBackend:
    """Search result adapter with safe fetches and no cloud-token consumption."""

    def __init__(
        self,
        *,
        web_ingestion: WebIngestionService | None = None,
        captions: YouTubeCaptionService | None = None,
        search: SearchCallable | None = None,
        maximum_concurrency: int = 3,
        maximum_results_per_query: int = 2,
        maximum_content_characters: int = 12_000,
    ) -> None:
        if maximum_concurrency < 1:
            raise ValueError("maximum_concurrency debe ser al menos 1.")
        self._web = web_ingestion or WebIngestionService()
        self._captions = captions or YouTubeCaptionService()
        self._search = search or self._ddgs_search
        self._semaphore = asyncio.Semaphore(maximum_concurrency)
        self._maximum_results_per_query = max(1, maximum_results_per_query)
        self._maximum_content_characters = maximum_content_characters

    async def search(self, query: str, *, limit: int) -> Sequence[ExternalSearchResult]:
        if limit < 1:
            return []
        requested = min(limit, self._maximum_results_per_query)
        raw_results = await asyncio.to_thread(self._search, query, requested)
        tasks = [
            self._materialize(item, rank=index, total=max(1, len(raw_results)))
            for index, item in enumerate(raw_results[:requested])
        ]
        materialized = await asyncio.gather(*tasks, return_exceptions=True)
        return [item for item in materialized if isinstance(item, ExternalSearchResult)]

    @staticmethod
    def _ddgs_search(query: str, limit: int) -> Sequence[dict[str, Any]]:
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise RuntimeError("ddgs no está instalado.") from exc
        return list(DDGS().text(f"{query} fuente educativa oficial", max_results=limit))

    async def _materialize(
        self,
        raw: dict[str, Any],
        *,
        rank: int,
        total: int,
    ) -> ExternalSearchResult:
        url = str(raw.get("href") or raw.get("url") or "").strip()
        title = str(raw.get("title") or "Fuente externa").strip()
        hostname = (urlsplit(url).hostname or "").casefold()
        async with self._semaphore:
            if hostname == "youtu.be" or hostname == "youtube.com" or hostname.endswith(
                ".youtube.com"
            ):
                return await self._youtube_result(url, title, rank, total)
            document = await self._web.ingest(url)
            return self._web_result(document, rank, total)

    async def _youtube_result(
        self, url: str, title: str, rank: int, total: int
    ) -> ExternalSearchResult:
        try:
            transcript = await self._captions.fetch(url)
        except YouTubeIngestionError:
            raise
        chunks = chunk_transcript(transcript, source_id=self._source_id(url))
        content = "\n".join(chunk.content for chunk in chunks)[: self._maximum_content_characters]
        source_id = self._source_id(url)
        digest = sha256(content.encode("utf-8")).hexdigest()
        return ExternalSearchResult(
            chunk_id=f"{source_id}:{digest[:16]}",
            content=content,
            score=self._rank_score(rank, total),
            metadata={
                "source_id": source_id,
                "document_id": source_id,
                "title": title,
                "source_type": "youtube",
                "language": transcript.language or "und",
                "chunk_index": 0,
                "timestamp_start": chunks[0].timestamp_start,
                "timestamp_end": chunks[-1].timestamp_end,
                "url": url,
                "content_hash": digest,
                "trust_level": "UNTRUSTED_EXTERNAL",
            },
        )

    def _web_result(
        self, document: WebDocument, rank: int, total: int
    ) -> ExternalSearchResult:
        content = document.content[: self._maximum_content_characters]
        source_id = self._source_id(document.final_url)
        digest = sha256(content.encode("utf-8")).hexdigest()
        return ExternalSearchResult(
            chunk_id=f"{source_id}:{digest[:16]}",
            content=content,
            score=self._rank_score(rank, total),
            metadata={
                "source_id": source_id,
                "document_id": source_id,
                "title": document.title,
                "source_type": "web",
                "language": document.language,
                "chunk_index": 0,
                "url": document.final_url,
                "content_hash": digest,
                "ingested_at": document.fetched_at,
                "trust_level": document.trust_level,
            },
        )

    @staticmethod
    def _source_id(url: str) -> str:
        return f"external:{sha256(url.encode('utf-8')).hexdigest()[:24]}"

    @staticmethod
    def _rank_score(rank: int, total: int) -> float:
        return max(0.55, 1.0 - (rank / max(1, total)) * 0.35)
