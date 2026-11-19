from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.candidate_guideline import CandidateGuideline
    from app.models.compliance import ComplianceReport
    from app.models.organization import Organization
    from app.models.review import AuditEntry, ReviewDecision
    from app.models.user import User


class ContentSubmission(Base):
    """Content draft submitted for brand compliance evaluation."""

    __tablename__ = "content_submissions"

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
    author_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(250),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    target_channel: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    target_audience: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="draft",
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    latest_review_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(
            "review_decisions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_submission_latest_review",
        ),
        nullable=True,
    )
    metadata_payload: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
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
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Multimodal Submission Metadata (Phase 0C)
    media_type: Mapped[str] = mapped_column(
        String(50),
        default="text",
        server_default="text",
        nullable=False,
        index=True,
    )
    file_hash_sha256: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    mime_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    file_size_bytes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    multimodal_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="submissions",
        lazy="selectin",
    )
    author: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="authored_submissions",
        lazy="selectin",
    )
    compliance_reports: Mapped[List["ComplianceReport"]] = relationship(
        "ComplianceReport",
        back_populates="submission",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    review_decisions: Mapped[List["ReviewDecision"]] = relationship(
        "ReviewDecision",
        back_populates="submission",
        foreign_keys="ReviewDecision.submission_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    latest_review: Mapped[Optional["ReviewDecision"]] = relationship(
        "ReviewDecision",
        foreign_keys=[latest_review_id],
        post_update=True,
        lazy="selectin",
    )
    audit_entries: Mapped[List["AuditEntry"]] = relationship(
        "AuditEntry",
        foreign_keys="AuditEntry.submission_id",
        lazy="selectin",
    )
    extracted_candidate_guidelines: Mapped[List["CandidateGuideline"]] = relationship(
        "CandidateGuideline",
        back_populates="source_submission",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "status != 'approved' OR latest_review_id IS NOT NULL",
            name="chk_submission_approved_has_review",
        ),
        CheckConstraint(
            "version >= 1",
            name="chk_submission_version_positive",
        ),
        Index("idx_submissions_org_status", "organization_id", "status"),
        Index("idx_submissions_org_media_type", "organization_id", "media_type"),
    )
