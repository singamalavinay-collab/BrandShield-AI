from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.candidate_guideline_audit import CandidateGuidelineAuditEntry
    from app.models.guideline import BrandGuideline
    from app.models.organization import Organization
    from app.models.submission import ContentSubmission
    from app.models.user import User

JSONB_COMPAT = JSON().with_variant(JSONB, "postgresql")


class CandidateGuideline(Base):
    """AI-extracted brand guideline staged for mandatory human Admin governance.

    Architectural Invariants:
    1. Newly extracted candidate rules are NEVER active by default (review_status = PENDING_APPROVAL).
    2. Only authorized Admin users can approve or reject candidate rules.
    3. Rejected candidates are never added to active brand_guidelines.
    4. Tenant isolation is strictly enforced via organization_id.
    """

    __tablename__ = "candidate_guidelines"

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
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    rule_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        server_default="medium",
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    directive: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    examples_approved: Mapped[List[str]] = mapped_column(
        JSONB_COMPAT,
        default=list,
        nullable=False,
    )
    examples_prohibited: Mapped[List[str]] = mapped_column(
        JSONB_COMPAT,
        default=list,
        nullable=False,
    )
    tags: Mapped[List[str]] = mapped_column(
        JSONB_COMPAT,
        default=list,
        nullable=False,
    )

    # Source reference and document lineage
    source_reference: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    source_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSONB_COMPAT,
        default=dict,
        nullable=False,
    )
    source_submission_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("content_submissions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Extraction and Review Status
    extraction_status: Mapped[str] = mapped_column(
        String(50),
        default="EXTRACTED",
        server_default="EXTRACTED",
        nullable=False,
        index=True,
    )
    review_status: Mapped[str] = mapped_column(
        String(50),
        default="PENDING_APPROVAL",
        server_default="PENDING_APPROVAL",
        nullable=False,
        index=True,
    )

    # Governance Review Details
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    approved_guideline_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("brand_guidelines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="candidate_guidelines",
        lazy="selectin",
    )
    reviewer: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[reviewed_by],
        lazy="selectin",
    )
    promoted_guideline: Mapped[Optional["BrandGuideline"]] = relationship(
        "BrandGuideline",
        foreign_keys=[approved_guideline_id],
        lazy="selectin",
    )
    source_submission: Mapped[Optional["ContentSubmission"]] = relationship(
        "ContentSubmission",
        back_populates="extracted_candidate_guidelines",
        foreign_keys=[source_submission_id],
        lazy="selectin",
    )
    audit_entries: Mapped[List["CandidateGuidelineAuditEntry"]] = relationship(
        "CandidateGuidelineAuditEntry",
        back_populates="candidate_guideline",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "review_status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')",
            name="chk_candidate_review_status",
        ),
        CheckConstraint(
            "review_status != 'APPROVED' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="chk_candidate_approved_has_reviewer_and_time",
        ),
        Index("idx_candidate_guidelines_org_status", "organization_id", "review_status"),
        Index("idx_candidate_guidelines_org_created", "organization_id", "created_at"),
    )
