from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import RuleType, SeverityLevel


class CandidateReviewStatus(str, Enum):
    """Review states for AI-extracted candidate guidelines."""
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CandidateExtractionStatus(str, Enum):
    """Extraction outcomes for guideline parsing from documents."""
    EXTRACTED = "EXTRACTED"
    PARSED = "PARSED"
    FAILED = "FAILED"


class CandidateGuidelineBase(BaseModel):
    """Core attributes for an AI-extracted candidate brand guideline."""

    name: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Clear title of the candidate guideline rule",
    )
    rule_type: RuleType = Field(
        ...,
        description="Category of the rule (e.g. terminology, tone, messaging pillar)",
    )
    severity: SeverityLevel = Field(
        default=SeverityLevel.MEDIUM,
        description="Violation severity level when this rule is breached",
    )
    description: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Detailed explanation of the candidate rule context and rationale",
    )
    directive: str = Field(
        ...,
        min_length=5,
        max_length=4000,
        description="Explicit normative instruction or rule requirement",
    )
    examples_approved: List[str] = Field(
        default_factory=list,
        description="Exemplary compliant phrases adhering to this candidate guideline",
    )
    examples_prohibited: List[str] = Field(
        default_factory=list,
        description="Exemplary non-compliant phrases violating this candidate guideline",
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Categorical tags for filtering and retrieval",
    )
    source_reference: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Document filename or clause citation where the rule was identified",
    )
    source_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structural metadata such as page number, paragraph index, or file hash",
    )

    @field_validator("name", "directive", "description", mode="before")
    @classmethod
    def strip_and_validate_non_empty(cls, v: str) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Field cannot be empty or contain only whitespace.")
            return stripped
        return v


class CandidateGuidelineCreate(CandidateGuidelineBase):
    """Payload schema for staging an AI-extracted candidate guideline."""

    source_submission_id: Optional[UUID] = Field(
        default=None,
        description="Optional ID of the source document submission that originated this candidate",
    )


class CandidateGuidelineReviewAction(BaseModel):
    """Payload schema for an Admin human governance decision on a candidate guideline."""

    action: Literal["APPROVE", "REJECT"] = Field(
        ...,
        description="Governance action: APPROVE promotes candidate to active rule, REJECT permanently declines",
    )
    review_notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Administrative rationale or feedback accompanying the review decision",
    )
    modified_name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=200,
        description="Optional refined title if modified during Admin approval",
    )
    modified_directive: Optional[str] = Field(
        default=None,
        min_length=5,
        max_length=4000,
        description="Optional refined directive instruction if modified during Admin approval",
    )


class CandidateGuidelineResponse(CandidateGuidelineBase):
    """Full representation of a staged candidate guideline record."""

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique UUID identifier for this candidate guideline",
    )
    organization_id: UUID = Field(
        ...,
        description="Tenant organization boundary",
    )
    extraction_status: str = Field(
        default=CandidateExtractionStatus.EXTRACTED.value,
        description="Document extraction status",
    )
    review_status: str = Field(
        default=CandidateReviewStatus.PENDING_APPROVAL.value,
        description="Governance review status: PENDING_APPROVAL, APPROVED, or REJECTED",
    )
    reviewed_by: Optional[UUID] = Field(
        default=None,
        description="Admin reviewer user ID if reviewed",
    )
    reviewed_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the governance decision",
    )
    review_notes: Optional[str] = Field(
        default=None,
        description="Reviewer notes or rationale",
    )
    approved_guideline_id: Optional[UUID] = Field(
        default=None,
        description="UUID of the activated BrandGuideline if approved",
    )
    source_submission_id: Optional[UUID] = Field(
        default=None,
        description="UUID of the originating submission if applicable",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC last update timestamp",
    )

    model_config = ConfigDict(from_attributes=True)


class CandidateGuidelineAuditEntryResponse(BaseModel):
    """Immutable audit record representing an Admin governance decision on a candidate guideline."""

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique UUID identifier for this audit ledger entry",
    )
    organization_id: UUID = Field(
        ...,
        description="Tenant organization boundary",
    )
    candidate_guideline_id: UUID = Field(
        ...,
        description="UUID of the affected candidate guideline",
    )
    action: str = Field(
        ...,
        description="Governance review action (APPROVE or REJECT)",
    )
    actor_id: str = Field(
        ...,
        description="User identifier of the Admin reviewer",
    )
    actor_type: str = Field(
        default="human",
        description="Classification of the actor (strictly human)",
    )
    actor_name: str = Field(
        ...,
        description="Full name of the Admin reviewer",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Reviewer rationale or comments",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Execution details including promoted guideline ID or modifications",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the immutable audit record",
    )

    model_config = ConfigDict(from_attributes=True)

