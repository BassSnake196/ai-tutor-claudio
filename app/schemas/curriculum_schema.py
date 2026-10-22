from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sources import Citation, GroundingStatus


class EvaluationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)


class CurriculumUnitDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_number: int = Field(ge=1)
    unit_name: str = Field(min_length=1)
    estimated_hours: float = Field(gt=0)
    subtopics: list[str] = Field(min_length=1)
    didactic_explanation: str = Field(min_length=1)
    practical_activities: list[str] = Field(default_factory=list)
    evaluation_questions: list[EvaluationQuestion] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    learning_outcomes: list[str] = Field(default_factory=list)
    essential_concepts: list[str] = Field(default_factory=list)
    common_misconceptions: list[str] = Field(default_factory=list)
    guided_activity: str | None = Field(default=None, min_length=1)
    independent_activity: str | None = Field(default=None, min_length=1)
    formative_assessment: str | None = Field(default=None, min_length=1)
    evidence_of_learning: list[str] = Field(default_factory=list)
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class SyllabusUnit(CurriculumUnitDraft):
    """Audited unit. It keeps compatibility with the original public schema."""

    citations: list[Citation] = Field(default_factory=list)


class CurriculumDraft(BaseModel):
    """Unreviewed curriculum output; it deliberately has no grounding claim."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    topic_title: str = Field(min_length=1)
    target_level: str = Field(min_length=1)
    pedagogical_approach: str = Field(min_length=1)
    learning_objectives: list[str] = Field(min_length=1)
    syllabus_units: list[CurriculumUnitDraft] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)


class CurriculumResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    topic_title: str = Field(min_length=1)
    target_level: str = Field(min_length=1)
    pedagogical_approach: str = Field(min_length=1)
    learning_objectives: list[str] = Field(min_length=1)
    syllabus_units: list[SyllabusUnit] = Field(min_length=1)
    grounding_status: GroundingStatus
