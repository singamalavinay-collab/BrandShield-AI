from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.guideline import BrandGuideline
    from app.models.submission import ContentSubmission


class ComplianceReport(Base):
    """Automated compliance audit report generated for a content submission."""

    __tablename__ = "compliance_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submission_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    is_compliant: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    total_violations: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    submission: Mapped["ContentSubmission"] = relationship(
        "ContentSubmission",
        back_populates="compliance_reports",
    )
    violations: Mapped[List["RuleViolation"]] = relationship(
        "RuleViolation",
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "total_violations >= 0",
            name="chk_report_total_violations_non_negative",
        ),
    )


class RuleViolation(Base):
    """Specific brand rule infraction detected in content."""

    __tablename__ = "rule_violations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("brand_guidelines.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rule_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    rule_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    flagged_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    char_start: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    char_end: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    explanation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    report: Mapped["ComplianceReport"] = relationship(
        "ComplianceReport",
        back_populates="violations",
    )
    rule: Mapped["BrandGuideline"] = relationship(
        "BrandGuideline",
        back_populates="violations",
    )
    # 1:N relationship supporting multiple evidence citations per violation
    evidence_citations: Mapped[List["EvidenceCitation"]] = relationship(
        "EvidenceCitation",
        back_populates="violation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    suggestions: Mapped[List["CorrectionSuggestion"]] = relationship(
        "CorrectionSuggestion",
        back_populates="violation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "char_start IS NULL OR char_start >= 0",
            name="chk_violation_char_start_non_negative",
        ),
        CheckConstraint(
            "char_end IS NULL OR char_end >= 0",
            name="chk_violation_char_end_non_negative",
        ),
    )


class EvidenceCitation(BaseModel if False else Base):
    """Verifiable proof clause grounding an identified rule violation."""

    __tablename__ = "evidence_citations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    violation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rule_violations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("brand_guidelines.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rule_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    rule_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    source_clause: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    document_name: Mapped[str] = mapped_column(
        String(200),
        default="Official Brand Guidelines",
        nullable=False,
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    violation: Mapped["RuleViolation"] = relationship(
        "RuleViolation",
        back_populates="evidence_citations",
    )
    rule: Mapped["BrandGuideline"] = relationship(
        "BrandGuideline",
        back_populates="evidence_citations",
    )

    __table_args__ = (
        CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="chk_evidence_confidence_range",
        ),
    )


class CorrectionSuggestion(Base):
    """AI-synthesized compliant alternative. Advisory only; cannot approve content."""

    __tablename__ = "correction_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    violation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rule_violations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suggested_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    rationale: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(30),
        default="ai_generated",
        nullable=False,
    )
    diff_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    violation: Mapped["RuleViolation"] = relationship(
        "RuleViolation",
        back_populates="suggestions",
    )
