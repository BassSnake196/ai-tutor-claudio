import pytest

from app.ai.interfaces.stt import Transcript, TranscriptSegment
from app.rag.external_search import DuckDuckGoExternalSearchBackend
from app.rag.web_ingestion import WebDocument


class FakeWebIngestion:
    async def ingest(self, url: str) -> WebDocument:
        return WebDocument(
            requested_url=url,
            final_url=url,
            title="Guía didáctica",
            content="Conceptos, progresión, actividad y evaluación formativa.",
            fetched_at="2026-08-28T00:00:00+00:00",
            language="es",
            content_type="text/html",
            metadata={},
        )


class FakeCaptions:
    async def fetch(self, url: str) -> Transcript:
        return Transcript(
            segments=(
                TranscriptSegment(10, 15, "Explicación pedagógica con evaluación."),
            ),
            language="es",
            duration_seconds=15,
        )


@pytest.mark.asyncio
async def test_external_search_materializes_web_and_youtube_with_provenance() -> None:
    def search(query: str, limit: int):
        assert limit == 2
        return [
            {"href": "https://example.edu/lesson", "title": "Web"},
            {"href": "https://youtu.be/abcdefghijk", "title": "Video"},
        ]

    backend = DuckDuckGoExternalSearchBackend(
        web_ingestion=FakeWebIngestion(),  # type: ignore[arg-type]
        captions=FakeCaptions(),  # type: ignore[arg-type]
        search=search,
        maximum_results_per_query=2,
    )

    results = await backend.search("enseñar álgebra", limit=5)

    assert len(results) == 2
    assert results[0].metadata["source_type"] == "web"
    assert results[0].metadata["url"] == "https://example.edu/lesson"
    assert results[1].metadata["source_type"] == "youtube"
    assert results[1].metadata["timestamp_start"] == 10
    assert results[1].metadata["timestamp_end"] == 15


@pytest.mark.asyncio
async def test_external_search_discards_individual_fetch_failures() -> None:
    class FailingWeb:
        async def ingest(self, url: str) -> WebDocument:
            raise ValueError("blocked")

    backend = DuckDuckGoExternalSearchBackend(
        web_ingestion=FailingWeb(),  # type: ignore[arg-type]
        search=lambda query, limit: [{"href": "https://blocked.example", "title": "X"}],
    )

    assert await backend.search("consulta", limit=2) == []
