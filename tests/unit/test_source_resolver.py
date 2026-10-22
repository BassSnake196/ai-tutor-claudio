import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from app.rag.coverage import assess_coverage
from app.rag.research_queries import build_research_queries
from app.rag.source_resolver import (
    EXTERNAL_STAGE,
    LOCAL_LIBRARY_STAGE,
    SELECTED_STAGE,
    FilteredSearchBackendAdapter,
    SourceResolver,
)
from app.schemas.requests import CurriculumRequest
from app.schemas.sources import SourceType


@dataclass
class RequestFixture:
    topic: str = "Álgebra básica"
    target_level: str = "Secundaria"
    source_policy: str = "LOCAL_FIRST"
    source_ids: list[str] = field(default_factory=list)
    library_id: str = "default"
    course_id: str | None = "matematicas"
    prior_knowledge: list[str] = field(default_factory=list)
    desired_outcomes: list[str] = field(default_factory=list)
    pedagogical_approach: str = ""
    constraints: list[str] = field(default_factory=list)


def chunk(
    chunk_id: str,
    *,
    score: float = 0.9,
    source_id: str = "source-a",
    content: str | None = None,
    content_hash: str | None = None,
) -> SimpleNamespace:
    metadata: dict[str, Any] = {"source_id": source_id}
    if content_hash:
        metadata["content_hash"] = content_hash
    return SimpleNamespace(
        chunk_id=chunk_id,
        content=content or f"Contenido único {chunk_id}",
        score=score,
        metadata=metadata,
    )


def category_from_query(query: str) -> str:
    if "conceptos fundamentales" in query:
        return "concepts"
    if "secuencia de aprendizaje" in query:
        return "progression"
    if "errores frecuentes" in query:
        return "didactics"
    if "evaluación diagnóstica" in query:
        return "assessment"
    return "requirements"


class FakeBackend:
    def __init__(self, responses: dict[tuple[str, str], list[Any]], *, delay: float = 0) -> None:
        self.responses = responses
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0

    async def search(self, query: str, **kwargs: Any) -> list[Any]:
        stage = SELECTED_STAGE if kwargs.get("include_source_ids") else LOCAL_LIBRARY_STAGE
        category = category_from_query(query)
        self.calls.append({"stage": stage, "category": category, **kwargs})
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            response = self.responses.get((stage, category), [])
            if isinstance(response, Exception):
                raise response
            return list(response)
        finally:
            self.active -= 1


class FakeExternalBackend:
    def __init__(self, responses: dict[str, Any], *, delay: float = 0) -> None:
        self.responses = responses
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0

    async def search(self, query: str, *, limit: int) -> list[Any]:
        category = category_from_query(query)
        self.calls.append({"category": category, "query": query, "limit": limit})
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            response = self.responses.get(category, [])
            if isinstance(response, Exception):
                raise response
            return list(response)
        finally:
            self.active -= 1


def external_chunk(
    chunk_id: str,
    *,
    url: str,
    score: float = 0.9,
    source_type: str | None = None,
    content: str | None = None,
    content_hash: str | None = None,
) -> SimpleNamespace:
    metadata: dict[str, Any] = {"url": url, "title": f"Fuente {chunk_id}"}
    if source_type:
        metadata["source_type"] = source_type
    if content_hash:
        metadata["content_hash"] = content_hash
    return SimpleNamespace(
        chunk_id=chunk_id,
        content=content or f"Evidencia externa {chunk_id}",
        score=score,
        metadata=metadata,
    )


def sufficient_stage(stage: str, *, source_id: str = "selected") -> dict[tuple[str, str], list[Any]]:
    return {
        (stage, "concepts"): [chunk("c1", source_id=source_id)],
        (stage, "progression"): [chunk("c2", source_id=source_id)],
        (stage, "didactics"): [chunk("c3", source_id=source_id)],
        (stage, "assessment"): [chunk("c4", source_id=source_id)],
    }


def test_research_queries_are_deterministic_and_limited_to_five() -> None:
    request = RequestFixture(
        prior_knowledge=["Números enteros"],
        desired_outcomes=["Resolver ecuaciones"],
        constraints=["Sin calculadora"],
    )

    first = build_research_queries(request)
    second = build_research_queries(request)

    assert first == second
    assert len(first) == 5
    assert [item.category.value for item in first[:4]] == [
        "CONCEPTS",
        "PROGRESSION",
        "DIDACTICS",
        "ASSESSMENT",
    ]
    assert "Sin calculadora" in first[-1].query


def test_coverage_requires_concepts_three_categories_and_four_chunks() -> None:
    evidence = [
        {"chunk_id": "1", "category": "CONCEPTS"},
        {"chunk_id": "2", "category": "PROGRESSION"},
        {"chunk_id": "3", "category": "DIDACTICS"},
        {"chunk_id": "4", "category": "DIDACTICS"},
    ]
    report = assess_coverage(evidence)
    without_concepts = assess_coverage(
        [
            {"chunk_id": "1", "category": "PROGRESSION"},
            {"chunk_id": "2", "category": "DIDACTICS"},
            {"chunk_id": "3", "category": "ASSESSMENT"},
            {"chunk_id": "4", "category": "ASSESSMENT"},
        ]
    )

    assert report.sufficient is True
    assert report.score == 0.75
    assert without_concepts.sufficient is False


@pytest.mark.asyncio
async def test_selected_sources_stop_local_expansion_when_sufficient() -> None:
    backend = FakeBackend(sufficient_stage(SELECTED_STAGE))
    resolver = SourceResolver(backend)

    result = await resolver.resolve(RequestFixture(source_ids=["selected", "selected"]))

    assert result.coverage.sufficient is True
    assert len(backend.calls) == 4
    assert all(call["include_source_ids"] == ("selected",) for call in backend.calls)
    assert {chunk.stage for chunk in result.chunks} == {SELECTED_STAGE}
    assert [stage.stage for stage in result.trace.stages] == [SELECTED_STAGE]


@pytest.mark.asyncio
async def test_local_first_expands_only_inside_authorized_scope() -> None:
    responses = {
        (SELECTED_STAGE, "concepts"): [
            chunk("s1", source_id="selected"),
            chunk("s2", source_id="selected"),
        ],
        (LOCAL_LIBRARY_STAGE, "progression"): [chunk("l1", source_id="library")],
        (LOCAL_LIBRARY_STAGE, "didactics"): [chunk("l2", source_id="library")],
        (LOCAL_LIBRARY_STAGE, "assessment"): [chunk("l3", source_id="library")],
    }
    backend = FakeBackend(responses)
    resolver = SourceResolver(backend)

    result = await resolver.resolve(RequestFixture(source_ids=["selected"]))

    local_calls = [call for call in backend.calls if call["stage"] == LOCAL_LIBRARY_STAGE]
    assert result.coverage.sufficient is True
    assert len(local_calls) == 4
    assert all(call["exclude_source_ids"] == ("selected",) for call in local_calls)
    assert all(call["library_id"] == "default" for call in local_calls)
    assert all(call["course_id"] == "matematicas" for call in local_calls)
    assert result.chunks[0].stage == SELECTED_STAGE


@pytest.mark.asyncio
async def test_uploaded_only_abstains_without_querying_local_library() -> None:
    backend = FakeBackend(
        {(SELECTED_STAGE, "concepts"): [chunk("only", source_id="selected")]}
    )
    resolver = SourceResolver(backend)

    result = await resolver.resolve(
        RequestFixture(source_policy="UPLOADED_ONLY", source_ids=["selected"])
    )

    assert result.coverage.sufficient is False
    assert len(backend.calls) == 4
    assert all(call["stage"] == SELECTED_STAGE for call in backend.calls)
    assert "impide ampliar" in result.warnings[-1]


@pytest.mark.asyncio
async def test_uploaded_only_rejects_an_empty_selection() -> None:
    resolver = SourceResolver(FakeBackend({}))

    with pytest.raises(ValueError, match="requiere al menos un source_id"):
        await resolver.resolve(RequestFixture(source_policy="UPLOADED_ONLY"))


@pytest.mark.asyncio
async def test_external_allowed_marks_pending_search_after_local_is_insufficient() -> None:
    backend = FakeBackend({})
    resolver = SourceResolver(backend)

    result = await resolver.resolve(RequestFixture(source_policy="EXTERNAL_ALLOWED"))

    assert result.coverage.sufficient is False
    assert result.trace.external_search_required is True
    assert len(result.trace.stages) == 1
    assert result.trace.stages[0].stage == LOCAL_LIBRARY_STAGE


@pytest.mark.asyncio
async def test_external_stage_runs_once_after_insufficient_local_and_completes_coverage() -> None:
    external = FakeExternalBackend(
        {
            "concepts": [external_chunk("e1", url="https://example.edu/conceptos")],
            "progression": [external_chunk("e2", url="https://example.edu/progresion")],
            "didactics": [external_chunk("e3", url="https://example.edu/didactica")],
            "assessment": [external_chunk("e4", url="https://example.edu/evaluacion")],
        },
        delay=0.01,
    )
    resolver = SourceResolver(FakeBackend({}), external_backend=external)

    result = await resolver.resolve(
        RequestFixture(source_policy="EXTERNAL_ALLOWED", source_ids=["selected"])
    )

    assert result.coverage.sufficient is True
    assert [stage.stage for stage in result.trace.stages] == [
        SELECTED_STAGE,
        LOCAL_LIBRARY_STAGE,
        EXTERNAL_STAGE,
    ]
    assert len(external.calls) == 4
    assert external.max_active == 4
    assert result.trace.external_search_required is False
    assert {item.metadata.source_type for item in result.chunks} == {SourceType.WEB}
    assert all(item.fragment_reference.startswith("https://") for item in result.chunks)
    external_trace = result.trace.stages[-1]
    assert external_trace.filters.source_types == [SourceType.WEB, SourceType.YOUTUBE]
    assert external_trace.queries
    assert external_trace.latency_ms >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("external_min_score", "expected_ids"), [(0.1, ["low-external"]), (0.3, [])])
async def test_external_threshold_is_independent_from_dense_threshold(
    external_min_score: float, expected_ids: list[str]
) -> None:
    external = FakeExternalBackend(
        {
            "concepts": [external_chunk("low-external", url="https://example.edu/low", score=0.2)]
        }
    )
    resolver = SourceResolver(
        FakeBackend({}),
        external_backend=external,
        min_score=0.35,
        external_min_score=external_min_score,
    )

    result = await resolver.resolve(RequestFixture(source_policy="EXTERNAL_ALLOWED"))

    assert [item.chunk_id for item in result.chunks] == expected_ids


@pytest.mark.asyncio
async def test_external_stage_is_not_called_when_local_is_sufficient() -> None:
    external = FakeExternalBackend(sufficient_stage(EXTERNAL_STAGE))
    resolver = SourceResolver(
        FakeBackend(sufficient_stage(LOCAL_LIBRARY_STAGE)),
        external_backend=external,
    )

    result = await resolver.resolve(RequestFixture(source_policy="EXTERNAL_ALLOWED"))

    assert result.coverage.sufficient is True
    assert external.calls == []
    assert [stage.stage for stage in result.trace.stages] == [LOCAL_LIBRARY_STAGE]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "source_ids"),
    [
        ("LOCAL_FIRST", []),
        ("UPLOADED_ONLY", ["selected"]),
        ("NO_SOURCES", []),
    ],
)
async def test_external_backend_is_never_used_by_other_policies(
    policy: str, source_ids: list[str]
) -> None:
    external = FakeExternalBackend(
        {"concepts": [external_chunk("e1", url="https://example.edu/conceptos")]}
    )
    resolver = SourceResolver(FakeBackend({}), external_backend=external)

    result = await resolver.resolve(
        RequestFixture(source_policy=policy, source_ids=source_ids)
    )

    assert result.coverage.sufficient is False
    assert external.calls == []
    assert all(stage.stage != EXTERNAL_STAGE for stage in result.trace.stages)


@pytest.mark.asyncio
async def test_external_failure_preserves_local_evidence_and_is_traced() -> None:
    local = FakeBackend(
        {(LOCAL_LIBRARY_STAGE, "concepts"): [chunk("local-1", source_id="library")]}
    )
    external = FakeExternalBackend(
        {
            "concepts": RuntimeError("connector unavailable"),
            "progression": RuntimeError("connector unavailable"),
            "didactics": RuntimeError("connector unavailable"),
            "assessment": RuntimeError("connector unavailable"),
        }
    )
    resolver = SourceResolver(local, external_backend=external)

    result = await resolver.resolve(RequestFixture(source_policy="EXTERNAL_ALLOWED"))

    assert [item.chunk_id for item in result.chunks] == ["local-1"]
    assert result.coverage.sufficient is False
    assert result.trace.external_search_required is False
    assert result.trace.stages[-1].stage == EXTERNAL_STAGE
    assert "Fallaron 4 consultas" in (result.trace.stages[-1].stop_reason or "")
    assert len(result.trace.stages[-1].errors) == 4
    assert sum("RuntimeError" in warning for warning in result.warnings) == 4


@pytest.mark.asyncio
async def test_external_results_require_traceable_web_or_youtube_provenance() -> None:
    external = FakeExternalBackend(
        {
            "concepts": [external_chunk("bad-type", url="https://example.edu/a", source_type="pdf")],
            "progression": [chunk("missing-url")],
            "didactics": [
                external_chunk("youtube", url="https://www.youtube.com/watch?v=abc")
            ],
        }
    )
    resolver = SourceResolver(FakeBackend({}), external_backend=external)

    result = await resolver.resolve(RequestFixture(source_policy="EXTERNAL_ALLOWED"))

    assert [item.chunk_id for item in result.chunks] == ["youtube"]
    assert result.chunks[0].metadata.source_type is SourceType.YOUTUBE
    assert result.trace.external_search_required is False
    assert sum("Resultado externo descartado" in warning for warning in result.warnings) == 2


@pytest.mark.asyncio
async def test_external_deduplication_never_replaces_local_evidence() -> None:
    duplicate_hash = "d" * 64
    local = FakeBackend(
        {
            (LOCAL_LIBRARY_STAGE, "concepts"): [
                chunk("local", source_id="library", content_hash=duplicate_hash)
            ]
        }
    )
    external = FakeExternalBackend(
        {
            "progression": [
                external_chunk(
                    "external-duplicate",
                    url="https://example.edu/duplicate",
                    content_hash=duplicate_hash,
                )
            ]
        }
    )
    resolver = SourceResolver(local, external_backend=external)

    result = await resolver.resolve(RequestFixture(source_policy="EXTERNAL_ALLOWED"))

    assert [item.chunk_id for item in result.chunks] == ["local"]
    assert result.chunks[0].stage == LOCAL_LIBRARY_STAGE
    assert any("duplicados" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_no_sources_does_not_call_backend() -> None:
    backend = FakeBackend({})
    resolver = SourceResolver(backend)

    result = await resolver.resolve(RequestFixture(source_policy="NO_SOURCES"))

    assert result.chunks == []
    assert result.trace.stages == []
    assert backend.calls == []
    assert "sin fuentes" in result.warnings[0]


@pytest.mark.asyncio
async def test_threshold_and_chunk_id_then_content_hash_deduplication() -> None:
    backend = FakeBackend(
        {
            (SELECTED_STAGE, "concepts"): [
                chunk("kept", score=0.8, content_hash="a" * 64),
                chunk("kept", score=0.9, content="different", content_hash="b" * 64),
                chunk("another-id", score=0.85, content_hash="a" * 64),
                chunk("low", score=0.34),
            ]
        }
    )
    resolver = SourceResolver(backend, min_score=0.35)

    result = await resolver.resolve(
        RequestFixture(source_policy="UPLOADED_ONLY", source_ids=["selected"])
    )

    assert [item.chunk_id for item in result.chunks] == ["kept"]
    assert result.chunks[0].score == 0.9
    assert any("1 bajo umbral, 2 duplicados" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_research_queries_run_concurrently() -> None:
    backend = FakeBackend(sufficient_stage(LOCAL_LIBRARY_STAGE), delay=0.01)
    resolver = SourceResolver(backend)

    result = await resolver.resolve(RequestFixture())

    assert result.coverage.sufficient is True
    assert backend.max_active == 4


@pytest.mark.asyncio
async def test_context_is_capped_and_keeps_selected_precedence() -> None:
    responses: dict[tuple[str, str], list[Any]] = {}
    for category in ("concepts", "progression", "didactics", "assessment"):
        responses[(SELECTED_STAGE, category)] = [
            chunk(f"{category}-{index}", score=0.9 - index / 100, source_id="selected")
            for index in range(5)
        ]
    backend = FakeBackend(responses)
    resolver = SourceResolver(backend, max_context_chunks=12)

    result = await resolver.resolve(RequestFixture(source_ids=["selected"]))

    assert len(result.chunks) == 12
    assert all(item.stage == SELECTED_STAGE for item in result.chunks)
    assert any("8 por límite de contexto" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_search_failure_is_explainable_and_other_queries_continue() -> None:
    responses = sufficient_stage(LOCAL_LIBRARY_STAGE)
    responses[(LOCAL_LIBRARY_STAGE, "assessment")] = RuntimeError("qdrant unavailable")
    # Four distinct chunks and three categories still satisfy the configured baseline.
    responses[(LOCAL_LIBRARY_STAGE, "concepts")].append(chunk("c1-extra"))
    backend = FakeBackend(responses)
    resolver = SourceResolver(backend)

    result = await resolver.resolve(RequestFixture())

    assert result.coverage.sufficient is True
    assert any("RuntimeError" in warning for warning in result.warnings)
    assert result.trace.stages[0].coverage_after_stage is not None


@pytest.mark.asyncio
async def test_filtered_adapter_translates_hierarchy_to_rag_payload_filters() -> None:
    class FakeRagService:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        async def search(self, query: str, **kwargs: Any) -> list[Any]:
            self.kwargs = {"query": query, **kwargs}
            return []

    rag = FakeRagService()
    adapter = FilteredSearchBackendAdapter(rag, score_threshold=0.42)

    await adapter.search(
        "consulta",
        limit=7,
        include_source_ids=["a", "b"],
        exclude_source_ids=["x"],
        library_id="docentes",
        course_id="algebra",
    )

    assert rag.kwargs == {
        "query": "consulta",
        "limit": 7,
        "include_filters": {
            "source_id": ["a", "b"],
            "library_id": "docentes",
            "course_id": "algebra",
            "status": "ACTIVE",
        },
        "exclude_filters": {"source_id": ["x"]},
        "score_threshold": 0.42,
    }


@pytest.mark.asyncio
async def test_filtered_adapter_always_adds_active_status_without_override() -> None:
    class FakeRagService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def search(self, query: str, **kwargs: Any) -> list[Any]:
            self.calls.append(kwargs)
            return []

    rag = FakeRagService()
    adapter = FilteredSearchBackendAdapter(rag)

    await adapter.search("consulta", limit=5)
    await adapter.search(
        "consulta filtrada",
        limit=5,
        include_source_ids=["selected"],
        library_id="default",
        course_id="algebra",
    )

    assert rag.calls[0]["include_filters"] == {"status": "ACTIVE"}
    assert rag.calls[1]["include_filters"] == {
        "source_id": ["selected"],
        "library_id": "default",
        "course_id": "algebra",
        "status": "ACTIVE",
    }


@pytest.mark.asyncio
async def test_accepts_the_real_curriculum_request_contract() -> None:
    backend = FakeBackend(sufficient_stage(LOCAL_LIBRARY_STAGE))
    resolver = SourceResolver(backend)
    request = CurriculumRequest(
        topic="Álgebra básica",
        target_level="Secundaria",
        duration_weeks=4,
        hours_per_week=3,
    )

    result = await resolver.resolve(request)

    assert result.coverage.sufficient is True
    assert result.trace.policy.value == "LOCAL_FIRST"
    assert result.trace.final_coverage == result.coverage
