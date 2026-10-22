"""Hierarchical, policy-aware evidence resolution for curriculum generation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Protocol, Sequence, runtime_checkable
from urllib.parse import urlparse

from app.rag.coverage import assess_coverage
from app.rag.research_queries import (
    CORE_RESEARCH_CATEGORIES,
    ResearchQuery,
    build_research_queries,
)
from app.schemas.source_resolution import (
    CoverageReport,
    EvidenceBundle,
    EvidenceChunk,
    ResearchCategory,
    ResolutionStage,
    ResolutionStageTrace,
    SourceFilters,
    SourcePolicy,
    SourceResolutionTrace,
)
from app.schemas.sources import SourceMetadata, SourceType


SELECTED_STAGE = ResolutionStage.SELECTED
LOCAL_LIBRARY_STAGE = ResolutionStage.LOCAL_LIBRARY
EXTERNAL_STAGE = ResolutionStage.EXTERNAL
ACTIVE_STATUS = "ACTIVE"


@runtime_checkable
class SearchBackend(Protocol):
    """Semantic search boundary required by :class:`SourceResolver`.

    A Qdrant adapter is expected to embed ``query`` and translate these logical
    filters into payload filters.  Keeping that concern behind this protocol
    makes the hierarchy independently testable.
    """

    async def search(
        self,
        query: str,
        *,
        limit: int,
        include_source_ids: Sequence[str] | None = None,
        exclude_source_ids: Sequence[str] | None = None,
        library_id: str | None = None,
        course_id: str | None = None,
    ) -> Sequence[Any]: ...


@runtime_checkable
class ExternalSearchBackend(Protocol):
    """Read-only boundary for one external search connector or aggregator.

    Results may be objects or mappings, but must expose ``content``, ``score``
    and traceable WEB/YOUTUBE provenance (at least an HTTP(S) ``url``).
    """

    async def search(self, query: str, *, limit: int) -> Sequence[Any]: ...


class FilteredSearchBackendAdapter:
    """Adapt ``RagService.search`` payload filters to the logical resolver API."""

    def __init__(self, rag_service: Any, *, score_threshold: float = 0.0) -> None:
        self._rag_service = rag_service
        self._score_threshold = score_threshold

    async def search(
        self,
        query: str,
        *,
        limit: int,
        include_source_ids: Sequence[str] | None = None,
        exclude_source_ids: Sequence[str] | None = None,
        library_id: str | None = None,
        course_id: str | None = None,
    ) -> Sequence[Any]:
        include_filters: dict[str, Any] = {}
        exclude_filters: dict[str, Any] = {}
        if include_source_ids is not None:
            include_filters["source_id"] = list(include_source_ids)
        if exclude_source_ids:
            exclude_filters["source_id"] = list(exclude_source_ids)
        if library_id is not None:
            include_filters["library_id"] = library_id
        if course_id is not None:
            include_filters["course_id"] = course_id
        # The resolver must never surface archived payloads.  Set this last so
        # future additions to logical filters cannot accidentally override it.
        include_filters["status"] = ACTIVE_STATUS
        return await self._rag_service.search(
            query,
            limit=limit,
            include_filters=include_filters or None,
            exclude_filters=exclude_filters or None,
            score_threshold=self._score_threshold,
        )


@dataclass(slots=True)
class _ResolvedChunk:
    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any]
    research_category: ResearchCategory
    research_categories: tuple[ResearchCategory, ...]
    stage: ResolutionStage
    content_hash: str

    @property
    def source_id(self) -> str | None:
        value = self.metadata.get("source_id")
        return str(value) if value is not None else None


@dataclass(slots=True)
class _StageResult:
    chunks: list[_ResolvedChunk] = field(default_factory=list)
    raw_count: int = 0
    below_threshold: int = 0
    errors: list[str] = field(default_factory=list)
    latency_ms: int = 0


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _policy_name(request: Any) -> SourcePolicy:
    policy = _read(request, "source_policy", "LOCAL_FIRST")
    raw = getattr(policy, "value", policy)
    try:
        return SourcePolicy(str(raw).upper())
    except ValueError as exc:
        raise ValueError(f"Política de fuentes no soportada: {raw}.") from exc


def _ordered_unique(values: Sequence[Any] | None) -> tuple[str, ...]:
    result: list[str] = []
    for item in values or ():
        value = str(item).strip()
        if value and value not in result:
            result.append(value)
    return tuple(result)


class SourceResolver:
    """Resolve evidence selected-first, expanding only when policy permits it."""

    def __init__(
        self,
        backend: SearchBackend,
        *,
        external_backend: ExternalSearchBackend | None = None,
        min_score: float = 0.35,
        external_min_score: float = 0.0,
        query_limit: int = 5,
        max_context_chunks: int = 12,
        minimum_categories: int = 3,
        minimum_chunks: int = 4,
    ) -> None:
        if not 0 <= min_score <= 1:
            raise ValueError("min_score debe estar entre 0 y 1.")
        if not 0 <= external_min_score <= 1:
            raise ValueError("external_min_score debe estar entre 0 y 1.")
        if query_limit < 1:
            raise ValueError("query_limit debe ser mayor que cero.")
        if max_context_chunks < minimum_chunks:
            raise ValueError("max_context_chunks no puede ser menor que minimum_chunks.")
        self._backend = backend
        self._external_backend = external_backend
        self._min_score = min_score
        self._external_min_score = external_min_score
        self._query_limit = query_limit
        self._max_context_chunks = max_context_chunks
        self._minimum_categories = minimum_categories
        self._minimum_chunks = minimum_chunks

    async def resolve(self, request: Any) -> EvidenceBundle:
        policy = _policy_name(request)

        source_ids = _ordered_unique(_read(request, "source_ids", ()))
        library_id = str(_read(request, "library_id", "default") or "default")
        raw_course_id = _read(request, "course_id")
        course_id = str(raw_course_id) if raw_course_id else None

        if policy is SourcePolicy.UPLOADED_ONLY and not source_ids:
            raise ValueError("UPLOADED_ONLY requiere al menos un source_id.")
        if policy is SourcePolicy.NO_SOURCES:
            if source_ids:
                raise ValueError("NO_SOURCES no admite source_ids.")
            return self._empty_bundle(
                policy,
                warnings=("La generación fue solicitada sin fuentes; no habrá fundamentación.",),
            )

        queries = build_research_queries(request)
        stages: list[ResolutionStageTrace] = []
        all_chunks: list[_ResolvedChunk] = []
        warnings: list[str] = []
        below_threshold = 0
        selected: _StageResult | None = None

        if source_ids:
            selected = await self._run_stage(
                queries,
                stage=SELECTED_STAGE,
                include_source_ids=source_ids,
            )
            all_chunks.extend(selected.chunks)
            below_threshold += selected.below_threshold
            warnings.extend(selected.errors)

        selected_unique, selected_duplicates = self._deduplicate(all_chunks)
        selected_coverage = self._coverage(selected_unique)
        if selected is not None:
            stages.append(
                self._trace_stage(
                    selected,
                    queries=queries,
                    stage=SELECTED_STAGE,
                    coverage=selected_coverage,
                    include_source_ids=source_ids,
                    stop_reason=(
                        "La selección cubre el mínimo; no se amplía la búsqueda."
                        if selected_coverage.sufficient
                        else "La selección es insuficiente para la cobertura mínima."
                    ),
                )
            )
        should_expand = not selected_coverage.sufficient and policy.allows_local_expansion

        if should_expand:
            local = await self._run_stage(
                queries,
                stage=LOCAL_LIBRARY_STAGE,
                exclude_source_ids=source_ids,
                library_id=library_id,
                course_id=course_id,
            )
            all_chunks.extend(local.chunks)
            below_threshold += local.below_threshold
            combined_unique, _ = self._deduplicate(all_chunks)
            local_coverage = self._coverage(combined_unique)
            stages.append(
                self._trace_stage(
                    local,
                    queries=queries,
                    stage=LOCAL_LIBRARY_STAGE,
                    coverage=local_coverage,
                    exclude_source_ids=source_ids,
                    library_id=library_id,
                    course_id=course_id,
                    stop_reason=(
                        "La biblioteca local completó la cobertura mínima."
                        if local_coverage.sufficient
                        else "La biblioteca local no alcanzó la cobertura mínima."
                    ),
                )
            )
            warnings.extend(local.errors)

        pre_external_unique, _ = self._deduplicate(all_chunks)
        pre_external_coverage = self._coverage(pre_external_unique)
        external_attempted = False
        if (
            policy.allows_external_search
            and not pre_external_coverage.sufficient
            and self._external_backend is not None
        ):
            external_attempted = True
            external = await self._run_external_stage(queries)
            all_chunks.extend(external.chunks)
            below_threshold += external.below_threshold
            externally_combined, _ = self._deduplicate(all_chunks)
            external_coverage = self._coverage(externally_combined)
            stages.append(
                self._trace_stage(
                    external,
                    queries=queries,
                    stage=EXTERNAL_STAGE,
                    coverage=external_coverage,
                    source_types=(SourceType.WEB, SourceType.YOUTUBE),
                    stop_reason=(
                        "La búsqueda externa completó la cobertura mínima."
                        if external_coverage.sufficient
                        else "La búsqueda externa se ejecutó una vez sin alcanzar la cobertura mínima."
                    ),
                )
            )
            warnings.extend(external.errors)

        unique_chunks, duplicate_count = self._deduplicate(all_chunks)
        duplicate_count = max(duplicate_count, selected_duplicates)
        final_chunks = self._limit_context(unique_chunks)
        coverage = self._coverage(final_chunks)
        external_required = (
            policy.allows_external_search
            and not coverage.sufficient
            and not external_attempted
        )

        if not coverage.sufficient:
            if policy is SourcePolicy.UPLOADED_ONLY:
                warnings.append(
                    "Los documentos seleccionados no cubren la evidencia mínima y la política impide ampliar la búsqueda."
                )
            elif external_required:
                warnings.append(
                    "La biblioteca local no cubre la evidencia mínima; no hay un conector externo disponible."
                )
            elif policy.allows_external_search and external_attempted:
                warnings.append(
                    "La búsqueda externa se ejecutó, pero la evidencia total sigue siendo insuficiente."
                )
            else:
                warnings.append("La biblioteca local no cubre la evidencia mínima.")

        capped_count = max(0, len(unique_chunks) - len(final_chunks))
        if below_threshold or duplicate_count or capped_count:
            warnings.append(
                "Descartes de resolución: "
                f"{below_threshold} bajo umbral, {duplicate_count} duplicados y "
                f"{capped_count} por límite de contexto."
            )
        if coverage.sufficient:
            stop_reason = "Se alcanzó la cobertura mínima con fuentes autorizadas."
        elif external_required:
            stop_reason = "La evidencia local es insuficiente; falta un conector para ejecutar búsqueda externa."
        elif policy.allows_external_search and external_attempted:
            stop_reason = "La etapa externa finalizó, pero la evidencia total siguió siendo insuficiente."
        elif policy is SourcePolicy.UPLOADED_ONLY:
            stop_reason = "Evidencia insuficiente; UPLOADED_ONLY impide ampliar la búsqueda."
        else:
            stop_reason = "La evidencia disponible no alcanzó la cobertura mínima."

        trace = SourceResolutionTrace(
            policy=policy,
            stages=stages,
            final_coverage=coverage,
            stop_reason=stop_reason,
            external_search_required=external_required,
        )
        return EvidenceBundle(
            chunks=[self._to_schema_chunk(chunk) for chunk in final_chunks],
            coverage=coverage,
            trace=trace,
            gaps=[f"Falta cobertura de {category.value}." for category in coverage.missing_categories],
            warnings=list(dict.fromkeys(warnings)),
        )

    async def _run_stage(
        self,
        queries: tuple[ResearchQuery, ...],
        *,
        stage: ResolutionStage,
        include_source_ids: tuple[str, ...] = (),
        exclude_source_ids: tuple[str, ...] = (),
        library_id: str | None = None,
        course_id: str | None = None,
    ) -> _StageResult:
        started_at = time.perf_counter()
        calls = [
            self._backend.search(
                query.query,
                limit=self._query_limit,
                include_source_ids=include_source_ids or None,
                exclude_source_ids=exclude_source_ids or None,
                library_id=library_id,
                course_id=course_id,
            )
            for query in queries
        ]
        batches = await asyncio.gather(*calls, return_exceptions=True)
        stage_result = _StageResult()
        for query, batch in zip(queries, batches, strict=True):
            if isinstance(batch, BaseException):
                stage_result.errors.append(
                    f"Falló una búsqueda {stage}/{query.category}: {type(batch).__name__}."
                )
                continue
            stage_result.raw_count += len(batch)
            for result in batch:
                score = float(_read(result, "score", 0.0))
                if score < self._min_score:
                    stage_result.below_threshold += 1
                    continue
                stage_result.chunks.append(self._to_evidence(result, query.category, stage))
        stage_result.latency_ms = max(0, round((time.perf_counter() - started_at) * 1_000))
        return stage_result

    async def _run_external_stage(
        self, queries: tuple[ResearchQuery, ...]
    ) -> _StageResult:
        """Execute the external expansion once, with its queries in parallel."""

        assert self._external_backend is not None
        started_at = time.perf_counter()
        calls = [
            self._external_backend.search(query.query, limit=self._query_limit)
            for query in queries
        ]
        batches = await asyncio.gather(*calls, return_exceptions=True)
        stage_result = _StageResult()
        for query, batch in zip(queries, batches, strict=True):
            if isinstance(batch, BaseException):
                stage_result.errors.append(
                    f"Falló una búsqueda EXTERNAL/{query.category}: {type(batch).__name__}."
                )
                continue
            stage_result.raw_count += len(batch)
            for result in batch:
                score = float(_read(result, "score", 0.0))
                if score < self._external_min_score:
                    stage_result.below_threshold += 1
                    continue
                try:
                    evidence = self._to_external_evidence(result, query.category)
                except ValueError as exc:
                    stage_result.errors.append(
                        f"Resultado externo descartado en {query.category}: {exc}"
                    )
                    continue
                stage_result.chunks.append(evidence)
        stage_result.latency_ms = max(0, round((time.perf_counter() - started_at) * 1_000))
        return stage_result

    @staticmethod
    def _to_evidence(
        result: Any, category: ResearchCategory, stage: ResolutionStage
    ) -> _ResolvedChunk:
        content = str(_read(result, "content", ""))
        metadata = dict(_read(result, "metadata", {}) or {})
        chunk_id = str(_read(result, "chunk_id", metadata.get("chunk_id", "")))
        content_hash = str(metadata.get("content_hash") or "")
        if len(content_hash) < 16:
            normalized = " ".join(content.split()).casefold()
            content_hash = sha256(normalized.encode("utf-8")).hexdigest()
        if not chunk_id:
            chunk_id = f"sha256:{content_hash}"
        return _ResolvedChunk(
            chunk_id=chunk_id,
            content=content,
            score=float(_read(result, "score", 0.0)),
            metadata=metadata,
            research_category=category,
            research_categories=(category,),
            stage=stage,
            content_hash=content_hash,
        )

    @staticmethod
    def _to_external_evidence(
        result: Any, category: ResearchCategory
    ) -> _ResolvedChunk:
        content = str(_read(result, "content", "")).strip()
        if not content:
            raise ValueError("el contenido está vacío.")
        if len(content) > 50_000:
            raise ValueError("el contenido supera el límite de 50 000 caracteres.")
        score = float(_read(result, "score", 0.0))
        if not -1 <= score <= 1:
            raise ValueError("el score está fuera del rango -1..1.")

        metadata = dict(_read(result, "metadata", {}) or {})
        for field_name in (
            "source_id",
            "document_id",
            "title",
            "source_type",
            "language",
            "chunk_index",
            "page_number",
            "timestamp_start",
            "timestamp_end",
            "url",
            "content_hash",
        ):
            field_value = _read(result, field_name)
            if field_value is not None and field_name not in metadata:
                metadata[field_name] = field_value

        url = str(metadata.get("url") or "").strip()
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("falta una URL HTTP(S) trazable.")

        raw_type = metadata.get("source_type")
        if raw_type is None:
            hostname = (parsed_url.hostname or "").casefold()
            source_type = (
                SourceType.YOUTUBE
                if hostname == "youtu.be" or hostname.endswith(".youtube.com") or hostname == "youtube.com"
                else SourceType.WEB
            )
        else:
            try:
                source_type = SourceType(str(getattr(raw_type, "value", raw_type)).casefold())
            except ValueError as exc:
                raise ValueError("source_type no es WEB ni YOUTUBE.") from exc
            if source_type not in {SourceType.WEB, SourceType.YOUTUBE}:
                raise ValueError("source_type no es WEB ni YOUTUBE.")

        normalized = " ".join(content.split()).casefold()
        content_hash = str(metadata.get("content_hash") or "")
        if len(content_hash) < 16:
            content_hash = sha256(normalized.encode("utf-8")).hexdigest()
        source_id = str(metadata.get("source_id") or "").strip()
        if not source_id:
            source_id = f"external:{sha256(url.encode('utf-8')).hexdigest()[:24]}"
        chunk_id = str(_read(result, "chunk_id", metadata.get("chunk_id", ""))).strip()
        if not chunk_id:
            chunk_id = f"external:{content_hash}"
        if len(chunk_id) > 200:
            raise ValueError("chunk_id supera 200 caracteres.")

        metadata.update(
            {
                "source_id": source_id,
                "document_id": metadata.get("document_id") or source_id,
                "library_id": "external",
                "source_type": source_type,
                "url": url,
                "chunk_index": int(metadata.get("chunk_index") or 0),
                "content_hash": content_hash,
            }
        )
        validated_metadata = SourceMetadata.model_validate(
            {
                key: value
                for key, value in metadata.items()
                if key in SourceMetadata.model_fields and value is not None
            }
        )
        return _ResolvedChunk(
            chunk_id=chunk_id,
            content=content,
            score=score,
            metadata=validated_metadata.model_dump(mode="python", exclude_none=True),
            research_category=category,
            research_categories=(category,),
            stage=EXTERNAL_STAGE,
            content_hash=content_hash,
        )

    @staticmethod
    def _deduplicate(chunks: Sequence[_ResolvedChunk]) -> tuple[list[_ResolvedChunk], int]:
        unique: list[_ResolvedChunk] = []
        by_id: dict[str, _ResolvedChunk] = {}
        by_hash: dict[str, _ResolvedChunk] = {}
        duplicate_count = 0
        for chunk in chunks:
            existing = by_id.get(chunk.chunk_id) or by_hash.get(chunk.content_hash)
            if existing is None:
                unique.append(chunk)
                by_id[chunk.chunk_id] = chunk
                by_hash[chunk.content_hash] = chunk
                continue
            duplicate_count += 1
            merged = tuple(
                dict.fromkeys((*existing.research_categories, *chunk.research_categories))
            )
            existing.research_categories = merged
            # Stage priority never changes: SELECTED chunks are processed first.
            if chunk.stage == existing.stage and chunk.score > existing.score:
                existing.score = chunk.score
        return unique, duplicate_count

    def _coverage(self, chunks: Sequence[_ResolvedChunk]) -> CoverageReport:
        return assess_coverage(
            chunks,
            minimum_categories=self._minimum_categories,
            minimum_chunks=self._minimum_chunks,
        )

    def _limit_context(self, chunks: Sequence[_ResolvedChunk]) -> list[_ResolvedChunk]:
        """Keep category representatives, then rank selected evidence first."""

        if len(chunks) <= self._max_context_chunks:
            return list(chunks)

        selected = [chunk for chunk in chunks if chunk.stage == SELECTED_STAGE]
        local = [chunk for chunk in chunks if chunk.stage == LOCAL_LIBRARY_STAGE]
        external = [chunk for chunk in chunks if chunk.stage == EXTERNAL_STAGE]
        chosen: list[_ResolvedChunk] = []
        chosen_ids: set[str] = set()
        covered: set[ResearchCategory] = set()

        for pool in (selected, local, external):
            for category in CORE_RESEARCH_CATEGORIES:
                if category in covered:
                    continue
                candidates = [
                    chunk
                    for chunk in pool
                    if category in chunk.research_categories and chunk.chunk_id not in chosen_ids
                ]
                if candidates:
                    best = max(candidates, key=lambda item: item.score)
                    chosen.append(best)
                    chosen_ids.add(best.chunk_id)
                    covered.update(best.research_categories)

        remaining = sorted(
            (chunk for chunk in chunks if chunk.chunk_id not in chosen_ids),
            key=lambda item: (
                {
                    SELECTED_STAGE: 0,
                    LOCAL_LIBRARY_STAGE: 1,
                    EXTERNAL_STAGE: 2,
                }[item.stage],
                -item.score,
                item.chunk_id,
            ),
        )
        chosen.extend(remaining[: self._max_context_chunks - len(chosen)])
        return chosen[: self._max_context_chunks]

    @staticmethod
    def _trace_stage(
        result: _StageResult,
        *,
        queries: tuple[ResearchQuery, ...],
        stage: ResolutionStage,
        coverage: CoverageReport,
        include_source_ids: tuple[str, ...] = (),
        exclude_source_ids: tuple[str, ...] = (),
        library_id: str | None = None,
        course_id: str | None = None,
        source_types: tuple[SourceType, ...] = (),
        stop_reason: str,
    ) -> ResolutionStageTrace:
        if result.errors:
            stop_reason = f"{stop_reason} Fallaron {len(result.errors)} consultas de esta etapa."
        return ResolutionStageTrace(
            stage=stage,
            queries=[query.query for query in queries],
            filters=SourceFilters(
                source_ids=list(include_source_ids),
                excluded_source_ids=list(exclude_source_ids),
                library_id=library_id,
                course_id=course_id,
                source_types=list(source_types),
            ),
            retrieved_count=result.raw_count,
            accepted_count=len(result.chunks),
            coverage_after_stage=coverage,
            stop_reason=stop_reason,
            latency_ms=result.latency_ms,
            errors=result.errors,
        )

    @staticmethod
    def _to_schema_chunk(chunk: _ResolvedChunk) -> EvidenceChunk:
        raw_metadata = {
            key: value
            for key, value in chunk.metadata.items()
            if key in SourceMetadata.model_fields and value is not None
        }
        raw_metadata.setdefault("source_id", "unknown-source")
        raw_metadata.setdefault("library_id", "default")
        raw_metadata.setdefault("chunk_index", 0)
        raw_metadata["content_hash"] = chunk.content_hash
        metadata = SourceMetadata.model_validate(raw_metadata)
        if metadata.url is not None:
            reference = metadata.url
            if metadata.timestamp_start is not None:
                separator = "&" if "?" in reference else "?"
                reference = f"{reference}{separator}t={metadata.timestamp_start:g}"
            reference = reference[:500]
        elif metadata.page_number is not None:
            reference = f"{metadata.source_id}#page={metadata.page_number}"
        elif metadata.timestamp_start is not None:
            reference = f"{metadata.source_id}#t={metadata.timestamp_start:g}"
        else:
            reference = f"{metadata.source_id}#chunk={chunk.chunk_id}"
        return EvidenceChunk(
            chunk_id=chunk.chunk_id,
            content=chunk.content,
            score=chunk.score,
            category=chunk.research_category,
            stage=chunk.stage,
            metadata=metadata,
            fragment_reference=reference,
        )

    def _empty_bundle(
        self, policy: SourcePolicy, *, warnings: tuple[str, ...]
    ) -> EvidenceBundle:
        coverage = self._coverage(())
        return EvidenceBundle(
            chunks=[],
            coverage=coverage,
            trace=SourceResolutionTrace(
                policy=policy,
                stages=[],
                final_coverage=coverage,
                stop_reason="La política NO_SOURCES omite la resolución de evidencia.",
                external_search_required=False,
            ),
            gaps=[
                f"Falta cobertura de {category.value}."
                for category in coverage.missing_categories
            ],
            warnings=list(warnings),
        )
