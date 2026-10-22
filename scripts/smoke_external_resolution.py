"""Exercise Qdrant -> public web/YouTube hierarchy without calling Gemini."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.registry import ModelRegistry  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.rag.external_search import DuckDuckGoExternalSearchBackend  # noqa: E402
from app.rag.service import RagService  # noqa: E402
from app.rag.source_resolver import FilteredSearchBackendAdapter, SourceResolver  # noqa: E402
from app.rag.vector_store import QdrantVectorStore  # noqa: E402
from app.schemas.requests import CurriculumRequest  # noqa: E402
from app.schemas.source_resolution import SourcePolicy  # noqa: E402


async def main() -> None:
    settings = get_settings()
    registry = ModelRegistry(settings)
    rag = RagService(
        embeddings=registry.embeddings(),
        vector_store=QdrantVectorStore(
            url=str(settings.qdrant_url),
            collection_name=settings.qdrant_collection,
        ),
    )
    resolver = SourceResolver(
        FilteredSearchBackendAdapter(rag, score_threshold=settings.rag_min_score),
        external_backend=DuckDuckGoExternalSearchBackend(
            maximum_results_per_query=1,
            maximum_concurrency=2,
        ),
        min_score=settings.rag_min_score,
        max_context_chunks=settings.curriculum_max_context_chunks,
        minimum_categories=settings.curriculum_min_categories,
        minimum_chunks=settings.curriculum_min_chunks,
    )
    evidence = await resolver.resolve(
        CurriculumRequest(
            topic="Álgebra básica",
            target_level="Secundaria",
            duration_weeks=2,
            hours_per_week=2,
            source_policy=SourcePolicy.EXTERNAL_ALLOWED,
        )
    )
    print(
        json.dumps(
            {
                "stages": [stage.stage.value for stage in evidence.trace.stages],
                "chunks": len(evidence.chunks),
                "coverage": evidence.coverage.score,
                "sufficient": evidence.coverage.sufficient,
                "external_search_required": evidence.trace.external_search_required,
                "urls": sorted(
                    {
                        str(chunk.metadata.url)
                        for chunk in evidence.chunks
                        if chunk.metadata.url is not None
                    }
                ),
                "warnings": evidence.warnings,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
