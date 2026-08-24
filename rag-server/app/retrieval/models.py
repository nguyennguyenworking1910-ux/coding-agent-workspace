from pydantic import BaseModel, Field, field_validator
from typing import Literal


class SearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=2000,
        description="Search query text",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of results to return",
    )
    candidate_k: int = Field(
        default=40,
        ge=5,
        le=200,
        description="Number of candidates to consider before ranking",
    )
    source_types: list[str] = Field(
        default_factory=list,
        description="Filter by source types (empty = no filter)",
    )
    source_keys: list[str] = Field(
        default_factory=list,
        description="Filter by source keys (empty = no filter)",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query cannot be blank")
        return v

    @field_validator("candidate_k")
    @classmethod
    def validate_candidate_k(cls, v: int, info) -> int:
        if "top_k" in info.data and v < info.data["top_k"]:
            raise ValueError(
                "candidate_k must be >= top_k"
            )
        return v


class SearchResult(BaseModel):
    rank: int
    source_key: str
    source_type: str
    title: str
    parent_chunk_id: str
    parent_chunk_index: int
    content: str
    score: float
    vector_score: float
    text_score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    result_count: int
    embedding_model: str
    elapsed_ms: int
