# Pydantic schemas (raw job validation + explainable AI output)
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl


class RawJob(BaseModel):
    """Output of extractors before cleaning & LLM evaluation."""
    source: str = Field(..., description="e.g., 'greenhouse', 'lever', 'indeed'")
    url: HttpUrl
    title: str
    company_raw: str
    location: Optional[str] = None
    is_remote: bool = False
    description: str
    posted_at_raw: Optional[str] = None  # e.g., "2 hours ago" or ISO string
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LLMMatchResult(BaseModel):
    """Strict JSON schema enforced on the LLM output."""
    match_score: int = Field(..., ge=0, le=100, description="0-100 fit score against resume")
    role_family: str = Field(..., description="e.g., 'AI/ML', 'Data Science', 'Backend', 'QA'")
    is_fresher_friendly: bool = Field(..., description="True if 0-1 years experience required")
    matching_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    reasoning: str = Field(..., max_length=400, description="Concise 1-2 sentence explanation")


class ProcessedJob(BaseModel):
    """Final canonical record stored in SQLite and displayed in app.py."""
    url: str
    source: str
    title: str
    company_canonical: str
    company_raw: str
    location: Optional[str] = None
    is_remote: bool = False
    posted_at: datetime
    collected_at: datetime
    match_score: int
    role_family: str
    is_fresher_friendly: bool
    matching_skills: List[str]
    missing_skills: List[str]
    reasoning: str
    llm_provider_used: str  # Tracks which tier succeeded (gemini / groq / openrouter)