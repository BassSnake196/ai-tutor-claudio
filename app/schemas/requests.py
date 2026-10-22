from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.source_resolution import SourcePolicy


def _strip_non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must not be blank")
    return value


NonEmptyText = Annotated[str, AfterValidator(_strip_non_empty)]
SourceIdentifier = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"),
]


class TutorQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=12_000)
    requires_sources: bool = False


class CurriculumRequest(BaseModel):
    """Parameters and source permissions for one curriculum generation run."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "topic": "Álgebra básica",
                "target_level": "Secundaria",
                "duration_weeks": 4,
                "hours_per_week": 3,
                "prior_knowledge": ["Aritmética con números enteros"],
                "desired_outcomes": ["Resolver ecuaciones lineales de una incógnita"],
                "pedagogical_approach": "Aprendizaje basado en problemas",
                "constraints": ["Sin calculadora durante la evaluación"],
                "source_ids": ["algebra-institucional-2026"],
                "library_id": "default",
                "course_id": "matematicas-secundaria",
                "source_policy": "LOCAL_FIRST",
            }
        },
    )

    topic: NonEmptyText = Field(max_length=500)
    target_level: NonEmptyText = Field(max_length=200)
    duration_weeks: int = Field(ge=1, le=52)
    hours_per_week: float = Field(gt=0, le=40)
    prior_knowledge: list[NonEmptyText] = Field(default_factory=list, max_length=100)
    desired_outcomes: list[NonEmptyText] = Field(default_factory=list, max_length=100)
    pedagogical_approach: NonEmptyText | None = Field(default=None, max_length=500)
    constraints: list[NonEmptyText] = Field(default_factory=list, max_length=100)
    source_ids: list[SourceIdentifier] = Field(default_factory=list, max_length=100)
    library_id: SourceIdentifier = "default"
    course_id: SourceIdentifier | None = None
    source_policy: SourcePolicy = SourcePolicy.LOCAL_FIRST

    @field_validator("source_ids")
    @classmethod
    def deduplicate_source_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_source_policy(self) -> "CurriculumRequest":
        if self.source_policy is SourcePolicy.UPLOADED_ONLY and not self.source_ids:
            raise ValueError("UPLOADED_ONLY requires at least one source_id")
        if self.source_policy is SourcePolicy.NO_SOURCES and self.source_ids:
            raise ValueError("NO_SOURCES does not accept source_ids")
        return self
