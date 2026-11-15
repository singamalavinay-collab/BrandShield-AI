from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import RuleType, SeverityLevel


class GuidelineBase(BaseModel):
    """Core attributes for a brand guideline rule."""

    name: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Clear title of the brand guideline rule",
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
        description="Detailed explanation of the rule context and rationale",
    )
    directive: str = Field(
        ...,
        min_length=5,
        max_length=4000,
        description="Explicit normative instruction or rule requirement",
    )
    examples_approved: List[str] = Field(
        default_factory=list,
        description="Exemplary compliant phrases adhering to this guideline",
    )
    examples_prohibited: List[str] = Field(
        default_factory=list,
        description="Exemplary non-compliant phrases violating this guideline",
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Categorical tags for filtering and retrieval",
    )
    is_active: bool = Field(
        default=True,
        description="Whether this guideline is currently active in verification scans",
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


class GuidelineCreate(GuidelineBase):
    """Payload schema for registering a new brand guideline."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Standard Product Capitalization",
                "rule_type": "terminology",
                "severity": "high",
                "description": "Always capitalize BrandShield AI with camelCase in official copy.",
                "directive": "The product name must be written strictly as 'BrandShield AI'. Never write 'brandshield' or 'Brandshield AI'.",
                "examples_approved": [
                    "BrandShield AI accelerates compliance reviews.",
                ],
                "examples_prohibited": [
                    "brandshield ai is fast.",
                    "Use BrandShield ai today.",
                ],
                "tags": ["branding", "product_names", "official_terms"],
                "is_active": True,
            }
        }
    )


class GuidelineUpdate(BaseModel):
    """Payload schema for partially updating an existing brand guideline."""

    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    rule_type: Optional[RuleType] = None
    severity: Optional[SeverityLevel] = None
    description: Optional[str] = Field(default=None, min_length=5, max_length=2000)
    directive: Optional[str] = Field(default=None, min_length=5, max_length=4000)
    examples_approved: Optional[List[str]] = None
    examples_prohibited: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None

    @field_validator("name", "directive", "description", mode="before")
    @classmethod
    def strip_optional_text(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Field cannot be empty or contain only whitespace.")
            return stripped
        return v


class GuidelineResponse(GuidelineBase):
    """Complete representation of a brand guideline record."""

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique UUID identifier for this guideline",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC last updated timestamp",
    )

    model_config = ConfigDict(from_attributes=True)
