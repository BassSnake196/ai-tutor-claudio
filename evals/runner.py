"""Isolated, dependency-light retrieval evaluation runner."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import platform
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

PRODUCTION_COLLECTION = "tutor_documents"


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    relevant_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    answerable: bool | None = None
    qrels: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RankedCandidate:
    candidate_id: str
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryResult:
    case_id: str
    query: str
    candidates: tuple[RankedCandidate, ...]
    latency_ms: float
    error: str | None = None


class RetrievalBackend(Protocol):
    """Small injectable contract; implementations may return sync or async results."""

    def search(self, query: str, *, limit: int, score_threshold: float | None) -> Iterable[Any]: ...


def _candidate(value: Any) -> RankedCandidate:
    if isinstance(value, RankedCandidate):
        return value
    if isinstance(value, Mapping):
        identifier = value.get("candidate_id", value.get("id", value.get("chunk_id")))
        return RankedCandidate(str(identifier), float(value.get("score", 0.0)), dict(value.get("metadata", {})))
    identifier = getattr(value, "candidate_id", getattr(value, "chunk_id", getattr(value, "id", None)))
    return RankedCandidate(str(identifier), float(getattr(value, "score", 0.0)), dict(getattr(value, "metadata", {}) or {}))


class RetrievalRunner:
    def __init__(self, backend: RetrievalBackend | Callable[..., Any], *, collection: str,
                 model: str = "unknown", config: Mapping[str, Any] | None = None,
                 k: int = 5, threshold: float | None = None, seed: int = 0) -> None:
        if collection == PRODUCTION_COLLECTION:
            raise ValueError("refusing to evaluate production collection tutor_documents")
        if k < 1:
            raise ValueError("k must be >= 1")
        self.backend, self.collection, self.model = backend, collection, model
        self.config, self.k, self.threshold, self.seed = dict(config or {}), k, threshold, seed

    def manifest(self, *, run_id: str | None = None) -> dict[str, Any]:
        random.seed(self.seed)
        now = datetime.now(timezone.utc).isoformat()
        return {"run_id": run_id or hashlib.sha256(now.encode()).hexdigest()[:12], "created_at": now,
                "model": self.model, "collection": self.collection, "k": self.k,
                "score_threshold": self.threshold, "seed": self.seed, "config": self.config,
                "hardware": {"platform": platform.platform(), "processor": platform.processor(),
                              "python": platform.python_version(), "cpu_count": os.cpu_count()}}

    async def run(self, cases: Sequence[RetrievalCase], *, run_id: str | None = None) -> tuple[dict[str, Any], list[QueryResult]]:
        results: list[QueryResult] = []
        for case in cases:
            started = time.perf_counter()
            try:
                value = self.backend.search(case.query, limit=self.k, score_threshold=self.threshold) if hasattr(self.backend, "search") else self.backend(case.query, limit=self.k, score_threshold=self.threshold)
                if inspect.isawaitable(value):
                    value = await value
                candidates = tuple(_candidate(item) for item in value)[: self.k]
                results.append(QueryResult(case.case_id, case.query, candidates, (time.perf_counter() - started) * 1000))
            except Exception as exc:  # preserve per-query evidence while keeping the run inspectable
                results.append(QueryResult(case.case_id, case.query, (), (time.perf_counter() - started) * 1000, f"{type(exc).__name__}: {exc}"))
        manifest = self.manifest(run_id=run_id)
        manifest["case_count"] = len(cases)
        try:
            from .metrics import aggregate_run, evaluate_query
            from .schemas import QueryCase, RankedResult
            query_metrics = []
            for case, result in zip(cases, results, strict=True):
                qrels = dict(case.qrels) or {
                    identifier: 1 for identifier in case.relevant_ids
                }
                qcase = QueryCase(
                    query_id=case.case_id,
                    query=case.query,
                    qrels=qrels,
                    source_ids=list(case.metadata.get("allowed_source_ids", [])),
                    answerability=(
                        None
                        if case.answerable is None
                        else "answerable" if case.answerable else "unanswerable"
                    ),
                )
                ranked = [RankedResult(result_id=item.candidate_id,
                    source_id=item.metadata.get("source_id")) for item in result.candidates]
                query_metrics.append(evaluate_query(qcase, ranked, k=self.k,
                    abstained=not result.candidates, latency_ms=result.latency_ms))
            manifest["metrics"] = aggregate_run(query_metrics, k=self.k).model_dump()
            manifest["query_metrics"] = [item.model_dump() for item in query_metrics]
        except (ImportError, ModuleNotFoundError):
            pass
        return manifest, results


def case_from_mapping(value: Mapping[str, Any]) -> RetrievalCase:
    qrels = {
        str(identifier): int(grade)
        for identifier, grade in dict(value.get("qrels", {})).items()
    }
    relevant = value.get(
        "relevant_ids",
        value.get("relevant", [identifier for identifier, grade in qrels.items() if grade > 0]),
    )
    metadata = dict(value.get("metadata", {}))
    metadata.setdefault("allowed_source_ids", list(value.get("source_ids", ())))
    answerability = value.get("answerability")
    if answerability == "answerable":
        answerable: bool | None = True
    elif answerability == "unanswerable":
        answerable = False
    else:
        answerable = value.get("answerable")
    return RetrievalCase(
        str(value.get("case_id", value.get("query_id"))),
        str(value["query"]),
        tuple(map(str, relevant)),
        metadata,
        answerable,
        qrels,
    )
