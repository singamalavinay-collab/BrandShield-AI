from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.candidate_guideline import CandidateGuideline
    from app.models.compliance import ClaimVerification
    from app.models.guideline import BrandGuideline
    from app.models.invitation import TeamInvitation
    from app.models.review import AuditEntry
    from app.models.submission import ContentSubmission
    from app.models.user import User


class Organization(Base):
    """Tenant boundary entity isolating all organization-owned brand data."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        unique=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", use_alter=True, name="fk_organizations_owner_id"),
        nullable=True,
        index=True,
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

    # Relationships
    users: Mapped[List["User"]] = relationship(
        "User",
        back_populates="organization",
        foreign_keys="User.organization_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    guidelines: Mapped[List["BrandGuideline"]] = relationship(
        "BrandGuideline",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    candidate_guidelines: Mapped[List["CandidateGuideline"]] = relationship(
        "CandidateGuideline",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    claim_verifications: Mapped[List["ClaimVerification"]] = relationship(
        "ClaimVerification",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="select",
    )
    submissions: Mapped[List["ContentSubmission"]] = relationship(
        "ContentSubmission",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    invitations: Mapped[List["TeamInvitation"]] = relationship(
        "TeamInvitation",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    audit_entries: Mapped[List["AuditEntry"]] = relationship(
        "AuditEntry",
        foreign_keys="AuditEntry.organization_id",
        lazy="selectin",
    )
