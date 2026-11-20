from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ClaimStatus, RiskLevel, RuleType, SeverityLevel


class EvidenceCitation(BaseModel):
    """Verifiable evidence citation extracted from approved brand guidelines."""

    rule_id: UUID = Field(
        ...,
        description="UUID of the brand guideline rule cited as evidence",
    )
    rule_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Name of the cited brand guideline rule",
    )
    rule_type: RuleType = Field(
        ...,
        description="Category of the cited rule",
    )
    source_clause: str = Field(
        ...,
        min_length=3,
        description="Verbatim text clause or standard extracted from brand documentation",
    )
    document_name: str = Field(
        default="Official Brand Guidelines",
        min_length=1,
        description="Title or origin of the reference source document",
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of evidence alignment (0.0 to 1.0)",
    )

    @field_validator("source_clause", "rule_name", mode="before")
    @classmethod
    def strip_and_validate_citation(cls, v: str) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Evidence citation clause and rule name cannot be empty.")
            return stripped
        return v


class CorrectionSuggestion(BaseModel):
    """AI-synthesized compliant alternative preserving authorial intent.
    
    IMPORTANT: Kept strictly segregated from human review decisions.
    """

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this correction suggestion",
    )
    suggested_text: str = Field(
        ...,
        min_length=1,
        description="Compliant phrasing suggested by the AI agent",
    )
    rationale: str = Field(
        ...,
        min_length=3,
        description="Explanation of how this suggestion resolves the rule violation",
    )
    source: Literal["ai_generated", "rule_derived", "human_edited"] = Field(
        default="ai_generated",
        description="Explicit provenance marker indicating whether this is rule-derived, AI-synthesized, or human-edited",
    )
    diff_summary: Optional[str] = Field(
        default=None,
        description="Summary of text modifications introduced by the suggestion",
    )

    @field_validator("suggested_text", "rationale", mode="before")
    @classmethod
    def strip_and_validate_suggestion(cls, v: str) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Suggestion text and rationale cannot be empty.")
            return stripped
        return v


class ViolationDetail(BaseModel):
    """Structured report of an identified brand guideline violation."""

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this violation instance",
    )
    rule_id: UUID = Field(
        ...,
        description="UUID of the rule violated",
    )
    rule_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Name of the violated rule",
    )
    rule_type: RuleType = Field(
        ...,
        description="Type of rule violated",
    )
    severity: SeverityLevel = Field(
        ...,
        description="Severity rating of the violation",
    )
    flagged_text: str = Field(
        ...,
        min_length=1,
        description="Exact violating excerpt located in the submission",
    )
    char_start: Optional[int] = Field(
        default=None,
        ge=0,
        description="Zero-indexed start position in content",
    )
    char_end: Optional[int] = Field(
        default=None,
        ge=0,
        description="Zero-indexed end position in content",
    )
    explanation: str = Field(
        ...,
        min_length=5,
        description="Clear explanation of why the flagged text breaches the policy",
    )
    evidence: EvidenceCitation = Field(
        ...,
        description="Verifiable source clause evidence supporting this violation finding",
    )
    ai_suggestions: List[CorrectionSuggestion] = Field(
        default_factory=list,
        description="AI-generated compliant alternatives for reviewer inspection",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this violation was logged",
    )

    model_config = ConfigDict(from_attributes=True)

    @field_validator("flagged_text", "explanation", mode="before")
    @classmethod
    def strip_text(cls, v: str) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Flagged text and explanation cannot be empty.")
            return stripped
        return v


class ClaimVerificationCreate(BaseModel):
    """Schema for staging or evaluating a claim verification."""

    claim_text: str = Field(
        ...,
        min_length=1,
        description="Extracted claim text evaluated against brand knowledge",
    )
    status: ClaimStatus = Field(
        ...,
        description="Verification verdict category (VERIFIED, UNSUPPORTED, OUTDATED, CONTRADICTORY, NEEDS_HUMAN_REVIEW)",
    )
    evidence: Optional[str] = Field(
        default=None,
        description="Verifiable source clause or excerpt from brand knowledge",
    )
    source_reference: Optional[str] = Field(
        default=None,
        description="Document section, clause, or paragraph lineage identifier",
    )
    document_name: Optional[str] = Field(
        default=None,
        description="Title or origin of the reference source document",
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the verification verdict (0.0 to 1.0)",
    )
    uncertainty_notes: Optional[str] = Field(
        default=None,
        description="Explicit explanation of ambiguity, missing context, or why human review is required",
    )
    is_escalated: bool = Field(
        default=False,
        description="Whether this claim triggers mandatory escalation",
    )

    model_config = ConfigDict(from_attributes=True)


class ClaimVerificationResponse(BaseModel):
    """Structured report of an extracted factual claim verification (Phase 1)."""

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this claim verification entry",
    )
    organization_id: UUID = Field(
        ...,
        description="Tenant organization UUID",
    )
    report_id: UUID = Field(
        ...,
        description="Associated compliance report UUID",
    )
    claim_text: str = Field(
        ...,
        min_length=1,
        description="Extracted claim text evaluated against brand knowledge",
    )
    status: ClaimStatus = Field(
        ...,
        description="Verification verdict category (VERIFIED, UNSUPPORTED, OUTDATED, CONTRADICTORY, NEEDS_HUMAN_REVIEW)",
    )
    evidence: Optional[str] = Field(
        default=None,
        description="Verifiable source clause or excerpt from brand knowledge",
    )
    source_reference: Optional[str] = Field(
        default=None,
        description="Document section, clause, or paragraph lineage identifier",
    )
    document_name: Optional[str] = Field(
        default=None,
        description="Title or origin of the reference source document",
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the verification verdict (0.0 to 1.0)",
    )
    uncertainty_notes: Optional[str] = Field(
        default=None,
        description="Explicit explanation of ambiguity, missing context, or why human review is required",
    )
    is_escalated: bool = Field(
        default=False,
        description="Whether this claim triggers mandatory escalation",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when verification was conducted",
    )

    model_config = ConfigDict(from_attributes=True)


class ComplianceReport(BaseModel):
    """Overall compliance analysis report synthesized for a content submission."""

    submission_id: UUID = Field(
        ...,
        description="UUID of the analyzed submission",
    )
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the compliance audit completion",
    )
    total_violations: int = Field(
        ...,
        ge=0,
        description="Total count of identified violations",
    )
    violations: List[ViolationDetail] = Field(
        default_factory=list,
        description="List of detailed violation records",
    )
    is_compliant: bool = Field(
        ...,
        description="True if zero violations were detected; False otherwise",
    )
    summary: str = Field(
        ...,
        description="Executive summary of the compliance inspection outcome",
    )

    # Risk Assessment Fields (Phase 1, Milestone 1)
    risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Risk assessment score clamped between 0 and 100",
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.LOW,
        description="Categorical risk band (LOW, MEDIUM, HIGH, CRITICAL)",
    )
    is_escalated: bool = Field(
        default=False,
        description="Flag indicating whether submission requires escalated admin governance",
    )
    channel_multiplier: float = Field(
        default=1.0,
        gt=0.0,
        description="Applied channel risk multiplier",
    )
    audience_multiplier: float = Field(
        default=1.0,
        gt=0.0,
        description="Applied audience risk multiplier",
    )
    risk_breakdown: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed breakdown of base scores and multipliers",
    )

    # Claim Verifications (Phase 1, Milestone 1)
    claim_verifications: List[ClaimVerificationResponse] = Field(
        default_factory=list,
        description="Verified factual claims evaluated for this submission",
    )

    model_config = ConfigDict(from_attributes=True)
