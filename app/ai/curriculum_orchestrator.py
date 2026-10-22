"""End-to-end orchestration for structured, source-aware curricula."""

import asyncio
import logging
import time
from uuid import uuid4
from typing import Any

from app.agents.critic_agent import CurriculumCritic, SemanticCurriculumCritic
from app.agents.curriculum_agent import CurriculumAgent
from app.agents.teaching_agent import TeachingAgent
from app.ai.interfaces.llm import LLMProviderError, TokenUsage as ProviderTokenUsage
from app.ai.registry import ModelRegistry
from app.rag.source_resolver import SourceResolver
from app.schemas.curriculum_schema import CurriculumDraft
from app.schemas.requests import CurriculumRequest
from app.schemas.responses import (
    CurriculumGenerationResponse,
    CurriculumGenerationStatus,
    ModelUsage,
    StageLatency,
    TokenUsage,
)
from app.schemas.source_resolution import SourcePolicy
from app.schemas.sources import GroundingStatus


logger = logging.getLogger(__name__)


class CurriculumOrchestrator:
    def __init__(
        self,
        registry: ModelRegistry,
        resolver: SourceResolver,
        critic: CurriculumCritic | None = None,
        source_catalog: Any | None = None,
        semantic_audit_enabled: bool = False,
    ) -> None:
        self._registry = registry
        self._resolver = resolver
        self._critic = critic or CurriculumCritic()
        self._source_catalog = source_catalog
        self._semantic_audit_enabled = semantic_audit_enabled

    async def generate(self, request: CurriculumRequest) -> CurriculumGenerationResponse:
        started_at = time.perf_counter()
        request_id = f"cur-{uuid4().hex}"
        warnings: list[str] = []
        stage_latencies: list[StageLatency] = []
        model_usage: list[ModelUsage] = []

        logger.info(
            "curriculum_generation_started request_id=%s source_policy=%s selected_sources=%d",
            request_id,
            request.source_policy.value,
            len(request.source_ids),
        )

        await self._verify_selected_sources(request)

        stage_started = time.perf_counter()
        evidence = await self._resolver.resolve(request)
        stage_latencies.append(
            StageLatency(stage="source_resolution", latency_ms=self._elapsed_ms(stage_started))
        )
        warnings.extend(evidence.warnings)

        cache_external = getattr(self._source_catalog, "cache_external_evidence", None)
        if callable(cache_external) and any(
            chunk.stage.value == "EXTERNAL" for chunk in evidence.chunks
        ):
            stage_started = time.perf_counter()
            try:
                cached_count, cache_warnings = await cache_external(
                    evidence,
                    library_id=request.library_id,
                    course_id=request.course_id,
                )
            except Exception as exc:
                warnings.append(
                    "La evidencia externa se usará en esta ejecución, pero no pudo guardarse "
                    f"en Qdrant ({type(exc).__name__})."
                )
            else:
                warnings.extend(cache_warnings)
                if cached_count:
                    warnings.append(
                        f"Se almacenaron {cached_count} fuentes externas en la biblioteca autorizada."
                    )
            stage_latencies.append(
                StageLatency(
                    stage="external_evidence_cache",
                    latency_ms=self._elapsed_ms(stage_started),
                )
            )

        if request.source_policy is not SourcePolicy.NO_SOURCES and not evidence.coverage.sufficient:
            logger.info(
                "curriculum_generation_stopped request_id=%s status=%s coverage_score=%.3f tokens=0",
                request_id,
                CurriculumGenerationStatus.INSUFFICIENT_CONTEXT.value,
                evidence.coverage.score,
            )
            return CurriculumGenerationResponse(
                request_id=request_id,
                status=CurriculumGenerationStatus.INSUFFICIENT_CONTEXT,
                grounding_status=GroundingStatus.INSUFFICIENT_CONTEXT,
                source_trace=evidence.trace,
                warnings=list(dict.fromkeys(warnings)),
                latency_ms=self._elapsed_ms(started_at),
                stage_latencies=stage_latencies,
            )

        cloud_model = self._registry.cloud_llm()
        curriculum_agent = CurriculumAgent(cloud_model)
        teaching_agent = TeachingAgent(cloud_model)

        stage_started = time.perf_counter()
        architecture = await curriculum_agent.design(request, evidence)
        architecture_usage = self._usage(architecture.usage)
        model_usage.append(
            ModelUsage(
                provider="google",
                model=architecture.model,
                role="curriculum_architect",
                token_usage=architecture_usage,
            )
        )
        stage_latencies.append(
            StageLatency(
                stage="curriculum_architecture",
                latency_ms=self._elapsed_ms(stage_started),
                token_usage=architecture_usage,
            )
        )
        locked_draft, hour_warning = self._normalize_hours(architecture.value, request)
        if hour_warning:
            warnings.append(hour_warning)

        final_draft = locked_draft
        stage_started = time.perf_counter()
        try:
            teaching = await teaching_agent.enrich(request, locked_draft, evidence)
        except LLMProviderError as exc:
            warnings.append(
                "El enriquecimiento didáctico cloud no estuvo disponible; se conservó el borrador curricular: "
                f"{exc}"
            )
            stage_latencies.append(
                StageLatency(stage="didactic_enrichment", latency_ms=self._elapsed_ms(stage_started))
            )
        else:
            final_draft = teaching.value
            teaching_usage = self._usage(teaching.usage)
            model_usage.append(
                ModelUsage(
                    provider="google",
                    model=teaching.model,
                    role="teaching_enrichment",
                    token_usage=teaching_usage,
                )
            )
            stage_latencies.append(
                StageLatency(
                    stage="didactic_enrichment",
                    latency_ms=self._elapsed_ms(stage_started),
                    token_usage=teaching_usage,
                )
            )

        stage_started = time.perf_counter()
        audit = self._critic.finalize(request, final_draft, evidence)
        warnings.extend(audit.warnings)
        final_curriculum = audit.curriculum
        stage_latencies.append(
            StageLatency(stage="curriculum_audit", latency_ms=self._elapsed_ms(stage_started))
        )

        if self._semantic_audit_enabled:
            stage_started = time.perf_counter()
            try:
                semantic_critic = SemanticCurriculumCritic(
                    self._registry.semantic_critic_llm()
                )
                semantic_report = await semantic_critic.audit(final_curriculum, evidence)
            except Exception as exc:
                warnings.append(
                    "La auditoría semántica local no pudo completarse; se conserva la auditoría determinística: "
                    f"{type(exc).__name__}."
                )
            else:
                final_curriculum = SemanticCurriculumCritic.apply_downgrade(
                    final_curriculum,
                    semantic_report,
                )
                warnings.extend(
                    f"Crítico {finding.severity.value} en {finding.location}: {finding.issue}"
                    for finding in semantic_report.findings
                )
                model_usage.append(
                    ModelUsage(
                        provider="ollama",
                        model=self._registry.local_model_name,
                        role="semantic_critic",
                        token_usage=self._usage(semantic_critic.last_usage),
                    )
                )
            stage_latencies.append(
                StageLatency(stage="semantic_audit", latency_ms=self._elapsed_ms(stage_started))
            )
        total_usage = self._sum_usage([item.token_usage for item in model_usage])
        response = CurriculumGenerationResponse(
            request_id=request_id,
            status=CurriculumGenerationStatus.COMPLETED,
            curriculum=final_curriculum,
            grounding_status=final_curriculum.grounding_status,
            source_trace=evidence.trace,
            warnings=list(dict.fromkeys(warnings)),
            models_used=model_usage,
            token_usage=total_usage,
            latency_ms=self._elapsed_ms(started_at),
            stage_latencies=stage_latencies,
        )
        logger.info(
            "curriculum_generation_completed request_id=%s grounding=%s models=%s total_tokens=%d latency_ms=%d",
            request_id,
            response.grounding_status.value,
            ",".join(item.role for item in model_usage),
            response.token_usage.total_tokens,
            response.latency_ms,
        )
        return response

    @staticmethod
    def _normalize_hours(
        draft: CurriculumDraft,
        request: CurriculumRequest,
    ) -> tuple[CurriculumDraft, str | None]:
        target = request.duration_weeks * request.hours_per_week
        current = sum(unit.estimated_hours for unit in draft.syllabus_units)
        if current <= 0 or abs(current - target) <= 0.01:
            return draft, None

        factor = target / current
        units = []
        allocated = 0.0
        for index, unit in enumerate(draft.syllabus_units):
            if index == len(draft.syllabus_units) - 1:
                hours = round(target - allocated, 2)
            else:
                hours = round(unit.estimated_hours * factor, 2)
                allocated += hours
            units.append(unit.model_copy(update={"estimated_hours": max(hours, 0.01)}))
        return (
            draft.model_copy(update={"syllabus_units": units}),
            f"La carga horaria generada ({current:g} h) se normalizó a {target:g} h.",
        )

    @staticmethod
    def _usage(value: ProviderTokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=value.prompt_tokens,
            output_tokens=value.output_tokens,
            other_tokens=value.other_tokens,
            total_tokens=value.total_tokens,
        )

    @staticmethod
    def _sum_usage(usages: list[TokenUsage]) -> TokenUsage:
        prompt = sum(item.prompt_tokens for item in usages)
        output = sum(item.output_tokens for item in usages)
        other = sum(item.other_tokens for item in usages)
        return TokenUsage(
            prompt_tokens=prompt,
            output_tokens=output,
            other_tokens=other,
            total_tokens=prompt + output + other,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, round((time.perf_counter() - started_at) * 1_000))

    async def _verify_selected_sources(self, request: CurriculumRequest) -> None:
        if not request.source_ids or self._source_catalog is None:
            return
        records = await asyncio.gather(
            *(self._source_catalog.get_source(source_id) for source_id in request.source_ids)
        )
        missing = [source_id for source_id, record in zip(request.source_ids, records, strict=True) if record is None]
        if missing:
            raise SelectedSourcesNotFoundError(missing)


class SelectedSourcesNotFoundError(ValueError):
    def __init__(self, source_ids: list[str]) -> None:
        self.source_ids = source_ids
        super().__init__("No existen las fuentes seleccionadas: " + ", ".join(source_ids))
