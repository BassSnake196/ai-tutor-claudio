from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentIngestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    source_type: str
    chunk_count: int = Field(ge=1)


class DocumentSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=5, ge=1, le=20)


class DocumentSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any]
