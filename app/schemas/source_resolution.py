"""Contracts for hierarchical evidence resolution."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sources import SourceMetadata, SourceType


class SourcePolicy(StrEnum):
    UPLOADED_ONLY = "UPLOADED_ONLY"
    LOCAL_FIRST = "LOCAL_FIRST"
    EXTERNAL_ALLOWED = "EXTERNAL_ALLOWED"
    NO_SOURCES = "NO_SOURCES"

    @property
    def allows_local_expansion(self) -> bool:
        return self in {self.LOCAL_FIRST, self.EXTERNAL_ALLOWED}

    @property
    def allows_external_search(self) -> bool:
        return self is self.EXTERNAL_ALLOWED


class ResolutionStage(StrEnum):
    SELECTED = "SELECTED"
    LOCAL_LIBRARY = "LOCAL_LIBRARY"
    EXTERNAL = "EXTERNAL"


class ResearchCategory(StrEnum):
    CONCEPTS = "CONCEPTS"
    PROGRESSION = "PROGRESSION"
    DIDACTICS = "DIDACTICS"
    ASSESSMENT = "ASSESSMENT"
    CURRICULUM_REQUIREMENTS = "CURRICULUM_REQUIREMENTS"


class SourceFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ids: list[str] = Field(default_factory=list)
    excluded_source_ids: list[str] = Field(default_factory=list)
    library_id: str | None = Field(default=None, min_length=1, max_length=100)
    course_id: str | None = Field(default=None, min_length=1, max_length=100)
    source_types: list[SourceType] = Field(default_factory=list)


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_categories: list[ResearchCategory] = Field(min_length=1)
    covered_categories: list[ResearchCategory] = Field(default_factory=list)
    missing_categories: list[ResearchCategory] = Field(default_factory=list)
    score: float = Field(ge=0, le=1)
    sufficient: bool
    unique_chunks: int = Field(ge=0)


class ResolutionStageTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: ResolutionStage
    attempted: bool = True
    queries: list[str] = Field(default_factory=list)
    filters: SourceFilters = Field(default_factory=SourceFilters)
    retrieved_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    coverage_after_stage: CoverageReport | None = None
    latency_ms: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)
    stop_reason: str | None = Field(default=None, max_length=1_000)


class SourceResolutionTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: SourcePolicy
    stages: list[ResolutionStageTrace] = Field(default_factory=list)
    final_coverage: CoverageReport | None = None
    stop_reason: str = Field(min_length=1, max_length=1_000)
    external_search_required: bool = False


class EvidenceChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50_000)
    score: float = Field(ge=-1, le=1)
    category: ResearchCategory
    stage: ResolutionStage
    metadata: SourceMetadata
    fragment_reference: str = Field(min_length=1, max_length=500)


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunks: list[EvidenceChunk] = Field(default_factory=list, max_length=12)
    coverage: CoverageReport
    trace: SourceResolutionTrace
    gaps: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
