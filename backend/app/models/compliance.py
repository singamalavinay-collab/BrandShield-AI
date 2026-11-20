from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    event,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.guideline import BrandGuideline
    from app.models.organization import Organization
    from app.models.submission import ContentSubmission

JSONB_COMPAT = JSON().with_variant(JSONB, "postgresql")


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

    # Risk Assessment Fields (Phase 1, Milestone 1)
    risk_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        server_default="0.0",
        nullable=False,
    )
    risk_level: Mapped[str] = mapped_column(
        String(20),
        default="LOW",
        server_default="LOW",
        nullable=False,
        index=True,
    )
    is_escalated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        index=True,
    )
    channel_multiplier: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        server_default="1.0",
        nullable=False,
    )
    audience_multiplier: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        server_default="1.0",
        nullable=False,
    )
    risk_breakdown: Mapped[Dict[str, Any]] = mapped_column(
        JSONB_COMPAT,
        default=dict,
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
    claim_verifications: Mapped[List["ClaimVerification"]] = relationship(
        "ClaimVerification",
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "total_violations >= 0",
            name="chk_report_total_violations_non_negative",
        ),
        CheckConstraint(
            "risk_score >= 0.0 AND risk_score <= 100.0",
            name="chk_report_risk_score_range",
        ),
        CheckConstraint(
            "risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="chk_report_risk_level",
        ),
        CheckConstraint(
            "channel_multiplier > 0.0 AND audience_multiplier > 0.0",
            name="chk_report_multipliers_positive",
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


class EvidenceCitation(Base):
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


class ClaimVerification(Base):
    """Factual claim extracted from content and evaluated against brand knowledge."""

    __tablename__ = "claim_verifications"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claim_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )
    evidence: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    source_reference: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    document_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        default=None,
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        server_default="1.0",
        nullable=False,
    )
    uncertainty_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    is_escalated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
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
        back_populates="claim_verifications",
    )
    organization: Mapped["Organization"] = relationship(
        "Organization",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('VERIFIED', 'UNSUPPORTED', 'OUTDATED', 'CONTRADICTORY', 'NEEDS_HUMAN_REVIEW')",
            name="chk_claim_status",
        ),
        CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="chk_claim_confidence_range",
        ),
        CheckConstraint(
            "length(trim(claim_text)) > 0",
            name="chk_claim_text_non_empty",
        ),
        Index("idx_claim_verifications_org_status", "organization_id", "status"),
        Index("idx_claim_verifications_report_escalated", "report_id", "is_escalated"),
    )


# Enforce cross-tenant integrity at the ORM layer during flush (INSERT and UPDATE)
@event.listens_for(ClaimVerification, "before_insert")
@event.listens_for(ClaimVerification, "before_update")
def validate_claim_verification_tenant_integrity(mapper: Any, connection: Any, target: ClaimVerification) -> None:
    """Ensure claim organization_id strictly matches the report's submission organization_id on insert and update."""
    from app.models.submission import ContentSubmission

    stmt = (
        select(ContentSubmission.organization_id)
        .join(ComplianceReport, ComplianceReport.submission_id == ContentSubmission.id)
        .where(ComplianceReport.id == target.report_id)
    )
    report_org_id = connection.scalar(stmt)
    if report_org_id is not None and target.organization_id != report_org_id:
        raise ValueError(
            f"Cross-tenant integrity violation: ClaimVerification organization_id ({target.organization_id}) "
            f"does not match referenced report organization_id ({report_org_id})."
        )


# Register SQLite database triggers for in-memory / local test suites
@event.listens_for(ClaimVerification.__table__, "after_create")
def register_claim_verification_triggers(target: Any, connection: Any, **kw: Any) -> None:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        # SQLite does not support multiple events (BEFORE INSERT OR UPDATE) in a single trigger,
        # so separate triggers are registered for INSERT and UPDATE parity.
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_claim_verification_org_match
            BEFORE INSERT ON claim_verifications
            BEGIN
                SELECT RAISE(ABORT, 'Cross-tenant violation: claim organization does not match report organization.')
                WHERE NEW.organization_id != (
                    SELECT s.organization_id
                    FROM compliance_reports r
                    JOIN content_submissions s ON s.id = r.submission_id
                    WHERE r.id = NEW.report_id
                );
            END;
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_claim_verification_org_match_update
            BEFORE UPDATE ON claim_verifications
            BEGIN
                SELECT RAISE(ABORT, 'Cross-tenant violation: claim organization does not match report organization.')
                WHERE NEW.organization_id != (
                    SELECT s.organization_id
                    FROM compliance_reports r
                    JOIN content_submissions s ON s.id = r.submission_id
                    WHERE r.id = NEW.report_id
                );
            END;
            """
        )
