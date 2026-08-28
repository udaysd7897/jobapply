from enum import Enum

from pydantic import BaseModel, Field


class RoleType(str, Enum):
    AI_ENGINEER = "ai_engineer"
    ML_ENGINEER = "ml_engineer"


class Portal(str, Enum):
    WORKDAY = "workday"
    GREENHOUSE = "greenhouse"
    OTHER = "other"


class JobContext(BaseModel):
    """Output of the JD-fetch agent (PLAN.md Phase 1); input to resume
    customization (Phase 2) and the autofill agent (Phase 4c).
    See docs/examples/job_context.json."""

    job_id: str = Field(description="Stable slug identifying this job, used as the key across all other contracts")
    job_url: str
    portal: Portal
    company: str
    title: str
    jd_text: str = Field(description="Raw job description text as extracted from the page")
    role_type: RoleType = Field(
        description="AI Engineer or ML Engineer; ambiguous titles default to AI Engineer per REQUIREMENT.md"
    )


class ExperienceEdit(BaseModel):
    target: str = Field(description="Which experience entry the added line goes under, e.g. 'harmony' or 'fanatics_swe2'")
    added_line: str


class TailoredResume(BaseModel):
    """Output of the resume customization agent (PLAN.md Phase 2).
    See docs/examples/tailored_resume.json."""

    job_id: str
    resume_file: str
    base_resume_version: str
    experience_edit: ExperienceEdit
    skills_added: list[str] = Field(max_length=2)


class FilledField(BaseModel):
    field_id: str
    label: str
    value: str | None
    source: str = Field(description="'static' (from the demographic JSON) or 'semantic_search'")
    confidence: float = Field(ge=0.0, le=1.0)


class FieldMap(BaseModel):
    """Output of the autofill agent's field-mapping step (PLAN.md Phase 4c).
    See docs/examples/field_map.json."""

    job_id: str
    portal: Portal
    fields: list[FilledField]


class JobResult(BaseModel):
    job_id: str
    company: str
    title: str
    status: str = Field(description="'applied', 'escalated', or 'errored'")
    reason: str | None = None


class RunSummary(BaseModel):
    """Sent to the human escalation channel after a full run completes
    (PLAN.md Phase 7). See docs/examples/run_summary.json."""

    run_id: str
    started_at: str
    finished_at: str
    total_jobs: int
    counts: dict[str, int]
    jobs: list[JobResult]
