"""Pydantic contracts used by the offline evaluation harness."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.source_resolution import ResearchCategory, SourcePolicy


class QueryCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    split: Literal["calibration", "dev", "test"] = "dev"
    language: str = Field(default="es", min_length=1)
    source_policy: SourcePolicy = SourcePolicy.LOCAL_FIRST
    source_ids: list[str] = Field(default_factory=list)
    library_id: str | None = None
    course_id: str | None = None
    expected_categories: list[ResearchCategory] = Field(default_factory=list)
    qrels: dict[str, int] = Field(default_factory=dict)
    answerability: Literal["answerable", "ambiguous", "unanswerable"] | None = None
    tags: list[str] = Field(default_factory=list)
    annotation_status: str | None = None
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fields(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        values = dict(values)
        legacy_ids = values.pop("relevant_ids", None)
        if legacy_ids is not None and "qrels" not in values:
            values["qrels"] = {str(identifier): 1 for identifier in legacy_ids}
        legacy_allowed = values.pop("allowed_source_ids", None)
        if legacy_allowed is not None and "source_ids" not in values:
            values["source_ids"] = legacy_allowed
        if "answerable" in values and "answerability" not in values:
            answerable = values.pop("answerable")
            values["answerability"] = "answerable" if answerable else "unanswerable"
        return values

    @field_validator("source_ids", "tags")
    @classmethod
    def unique_nonempty_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("identifiers must not be blank")
        return list(dict.fromkeys(values))

    @field_validator("qrels")
    @classmethod
    def validate_qrels(cls, values: dict[str, int]) -> dict[str, int]:
        if any(not key.strip() for key in values):
            raise ValueError("qrel identifiers must not be blank")
        if any(value not in (0, 1, 2) for value in values.values()):
            raise ValueError("qrel relevance must be 0, 1, or 2")
        return values

    @property
    def relevant_ids(self) -> list[str]:
        return [identifier for identifier, relevance in self.qrels.items() if relevance > 0]

    @property
    def allowed_source_ids(self) -> list[str]:
        return self.source_ids

    @property
    def relevance_judgments(self) -> list["RelevanceJudgment"]:
        return [RelevanceJudgment(result_id=identifier, relevance=relevance) for identifier, relevance in self.qrels.items()]

    @property
    def answerable(self) -> bool | None:
        if self.answerability is None or self.answerability == "ambiguous":
            return None
        return self.answerability == "answerable"


class RelevanceJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=2)


class RankedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(min_length=1)
    source_id: str | None = Field(default=None, min_length=1)
    relevance: int = Field(default=0, ge=0, le=2)


class QueryMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    k: int = Field(ge=1)
    hit: float
    precision: float
    recall: float | None = None
    mrr: float
    ndcg: float | None = None
    source_leakage: float
    abstained: bool
    abstention_correct: bool | None = None
    latency_ms: float | None = Field(default=None, ge=0)


class RunMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_count: int = Field(ge=0)
    evaluated_retrieval_queries: int = Field(ge=0)
    # Retrieval aggregates exclude cases with no known relevant qrels.
    evaluated_recall_queries: int = Field(ge=0)
    hit_at_k: float | None = None
    precision_at_k: float | None = None
    recall_at_k: float | None = None
    mrr_at_k: float | None = None
    ndcg_at_k: float | None = None
    source_leakage_rate: float
    abstention_rate: float
    abstention_accuracy: float | None = None
    latency_p50_ms: float | None = Field(default=None, ge=0)
    latency_p95_ms: float | None = Field(default=None, ge=0)
