from typing import Literal
from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class DatabaseReadiness(BaseModel):
    database: str
    database_user: str
    vector_version: str
    sources_table: bool
    chunks_table: bool
    migrations_table: bool


class ReadinessResponse(BaseModel):
    status: Literal["ok"]
    service: str
    database: DatabaseReadiness

class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(
        min_length=1,
        max_length=32,
    )

    @field_validator("texts")
    @classmethod
    def validate_texts(
        cls,
        texts: list[str],
    ) -> list[str]:
        for index, text in enumerate(texts):
            if not text.strip():
                raise ValueError(
                    f"texts[{index}] cannot be empty"
                )

        return texts


class EmbeddingResponse(BaseModel):
    status: Literal["ok"]
    model: str
    dimensions: int
    count: int
    normalized: bool
    elapsed_ms: float
    embeddings: list[list[float]]


class EmbeddingStatusResponse(BaseModel):
    status: Literal[
        "loaded",
        "not_loaded",
    ]
    model: str
    device: str
    dimensions: int
    max_length: int