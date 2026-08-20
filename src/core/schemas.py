from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApplicationStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    EVALUATED = "EVALUATED"
    SKIPPED = "SKIPPED"
    TAILORED = "TAILORED"
    FORM_MAPPED = "FORM_MAPPED"
    PENDING_HITL = "PENDING_HITL"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"


class JobPosting(BaseModel):
    job_id: str = Field(..., description="Unique deterministic hash of company + title + location")
    platform: str = Field(..., description="e.g. linkedin, greenhouse, lever, ashby")
    company_name: str
    job_title: str
    location: str
    job_url: str
    raw_description: str
    salary_range: Optional[str] = None
    is_remote: bool = False
    discovered_at: datetime = Field(default_factory=utc_now)
    status: ApplicationStatus = Field(default=ApplicationStatus.DISCOVERED)


class MatchEvaluation(BaseModel):
    job_id: str
    fit_score: int = Field(..., ge=0, le=100, description="Semantic match percentage")
    matches_hard_criteria: bool = Field(..., description="Passes location, visa, and level bounds")
    key_matching_skills: List[str] = Field(default_factory=list)
    missing_critical_skills: List[str] = Field(default_factory=list)
    strategic_reasoning: str = Field(..., description="Executive summary of why this role matches")
    evaluated_at: datetime = Field(default_factory=utc_now)


class TailoredRole(BaseModel):
    company: str
    role_title: str
    period: str
    bullets: List[str]


class TailoredResume(BaseModel):
    job_id: str
    executive_summary: str
    tailored_skills: List[str]
    selected_experiences: List[TailoredRole]
    pdf_compiled_path: Optional[str] = None
    tailored_at: datetime = Field(default_factory=utc_now)


class FormFieldMapping(BaseModel):
    field_name: str
    field_type: str = Field(..., description="text, select, radio, checkbox, file, textarea")
    selector: str
    injected_value: Any
    is_ground_truth: bool = True
    confidence_score: float = 1.0


class ApplicationSubmissionRecord(BaseModel):
    job_id: str
    submitted_at: datetime = Field(default_factory=utc_now)
    confirmation_reference: Optional[str] = None
    applied_resume_path: str
    form_answers_payload: Dict[str, Any] = Field(default_factory=dict)