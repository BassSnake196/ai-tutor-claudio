"""Deterministic evaluation of the source-resolution hierarchy."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from app.rag.source_resolver import EXTERNAL_STAGE, LOCAL_LIBRARY_STAGE, SELECTED_STAGE, SourceResolver


@dataclass(frozen=True)
class FakeChunk:
    chunk_id: str
    score: float
    source_id: str
    status: str = "ACTIVE"
    content: str = "evidencia"

    @property
    def metadata(self) -> dict[str, str]:
        return {"source_id": self.source_id, "status": self.status}


@dataclass
class ScriptedBackend:
    responses: dict[tuple[str, str], list[FakeChunk]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    delay: float = 0.0

    async def search(self, query: str, **kwargs: Any) -> list[FakeChunk]:
        category = _category(query)
        stage = SELECTED_STAGE if kwargs.get("include_source_ids") else LOCAL_LIBRARY_STAGE
        self.calls.append({"stage": stage, "category": category, **kwargs})
        if self.delay:
            await asyncio.sleep(self.delay)
        return list(self.responses.get((stage.value, category), []))


@dataclass
class ScriptedExternal:
    responses: dict[str, list[FakeChunk]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    failures: set[str] = field(default_factory=set)

    async def search(self, query: str, *, limit: int) -> list[FakeChunk]:
        category = _category(query)
        self.calls.append({"category": category, "limit": limit})
        if category in self.failures:
            raise RuntimeError("deterministic external failure")
        return list(self.responses.get(category, []))


@dataclass(frozen=True)
class HierarchyCase:
    case_id: str
    policy: str = "LOCAL_FIRST"
    source_ids: tuple[str, ...] = ()
    expected_relevant_ids: frozenset[str] = frozenset()
    backend: ScriptedBackend = field(default_factory=ScriptedBackend)
    external: ScriptedExternal | None = None
    include_archived: bool = False


@dataclass(frozen=True)
class HierarchyMetrics:
    case_id: str
    stages: tuple[str, ...]
    stop_stage: str | None
    source_leakage: bool
    expansion_unnecessary: bool
    false_coverage: bool
    inactive_accepted: bool
    external_required: bool
    external_executed: bool
    duplicate_count: int
    latency_ms: int

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _category(query: str) -> str:
    if "conceptos fundamentales" in query:
        return "concepts"
    if "secuencia de aprendizaje" in query:
        return "progression"
    if "errores frecuentes" in query:
        return "didactics"
    if "evaluación diagnóstica" in query:
        return "assessment"
    return "requirements"


def _request(case: HierarchyCase) -> SimpleNamespace:
    return SimpleNamespace(
        topic="Álgebra básica",
        target_level="Secundaria",
        source_policy=case.policy,
        source_ids=list(case.source_ids),
        library_id="default",
        course_id="matematicas-secundaria",
        prior_knowledge=[],
        desired_outcomes=[],
        pedagogical_approach="",
        constraints=[],
    )


async def evaluate_case(case: HierarchyCase) -> HierarchyMetrics:
    started = time.perf_counter()
    resolver = SourceResolver(case.backend, external_backend=case.external, min_score=0.35)
    bundle = await resolver.resolve(_request(case))
    stages = tuple(stage.stage.value for stage in bundle.trace.stages)
    stop_stage = stages[-1] if stages else None
    selected_ids = set(case.source_ids)
    leaked = any(
        chunk.metadata.source_id not in selected_ids
        for chunk in bundle.chunks
        if chunk.stage is SELECTED_STAGE
    )
    inactive = any(chunk.metadata.status != "ACTIVE" for chunk in bundle.chunks)
    accepted_ids = {chunk.chunk_id for chunk in bundle.chunks}
    false_coverage = bool(bundle.coverage.sufficient and case.expected_relevant_ids and not (accepted_ids & case.expected_relevant_ids))
    external_executed = EXTERNAL_STAGE.value in stages
    expansion_unnecessary = bool(
        SELECTED_STAGE.value in stages
        and bundle.trace.stages[0].coverage_after_stage is not None
        and bundle.trace.stages[0].coverage_after_stage.sufficient
        and len(stages) > 1
    )
    duplicate_count = sum("duplicados" in warning for warning in bundle.warnings)
    return HierarchyMetrics(
        case_id=case.case_id,
        stages=stages,
        stop_stage=stop_stage,
        source_leakage=leaked,
        expansion_unnecessary=expansion_unnecessary,
        false_coverage=false_coverage,
        inactive_accepted=inactive,
        external_required=bundle.trace.external_search_required,
        external_executed=external_executed,
        duplicate_count=duplicate_count,
        latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
    )


async def evaluate_cases(cases: list[HierarchyCase]) -> list[HierarchyMetrics]:
    return [await evaluate_case(case) for case in cases]
