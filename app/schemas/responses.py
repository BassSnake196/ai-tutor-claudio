from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.curriculum_schema import CurriculumResponse
from app.schemas.source_resolution import SourceResolutionTrace
from app.schemas.sources import Citation, GroundingStatus


class CurriculumGenerationStatus(StrEnum):
    COMPLETED = "COMPLETED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class TokenUsage(BaseModel):
    """Token counts only; intentionally contains no credentials or monetary estimates."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    other_tokens: int = Field(
        default=0,
        ge=0,
        description="Tokens adicionales informados por el proveedor, por ejemplo razonamiento interno.",
    )
    total_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> "TokenUsage":
        expected = self.prompt_tokens + self.output_tokens + self.other_tokens
        if self.total_tokens != expected:
            raise ValueError("total_tokens must equal prompt_tokens + output_tokens + other_tokens")
        return self


class ModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100)
    calls: int = Field(default=1, ge=1)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class StageLatency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=100)
    latency_ms: int = Field(ge=0)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class TutorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    route: str
    intent: str
    grounding_status: GroundingStatus
    citations: list[Citation] = Field(default_factory=list)
    latency_ms: int = Field(ge=0)


class CurriculumGenerationResponse(BaseModel):
    """Stable envelope for completed runs and expected domain failures."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=200)
    status: CurriculumGenerationStatus
    curriculum: CurriculumResponse | None = None
    grounding_status: GroundingStatus
    source_trace: SourceResolutionTrace
    warnings: list[str] = Field(default_factory=list)
    models_used: list[ModelUsage] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = Field(ge=0)
    stage_latencies: list[StageLatency] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status_payload(self) -> "CurriculumGenerationResponse":
        if self.status is CurriculumGenerationStatus.COMPLETED and self.curriculum is None:
            raise ValueError("COMPLETED requires a curriculum")
        if self.status is not CurriculumGenerationStatus.COMPLETED and self.curriculum is not None:
            raise ValueError("non-completed responses must not include a curriculum")
        if (
            self.status is CurriculumGenerationStatus.INSUFFICIENT_CONTEXT
            and self.grounding_status is not GroundingStatus.INSUFFICIENT_CONTEXT
        ):
            raise ValueError(
                "INSUFFICIENT_CONTEXT status requires matching grounding_status"
            )
        return self
