from datetime import datetime, timezone
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import RuleType, SeverityLevel


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

    model_config = ConfigDict(from_attributes=True)
