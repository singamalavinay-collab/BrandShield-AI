from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class TeamInvitation(Base):
    """Organization-scoped team member invitation entity."""

    __tablename__ = "team_invitations"

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
    inviter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="PENDING",
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="invitations",
        lazy="selectin",
    )
    inviter: Mapped["User"] = relationship(
        "User",
        back_populates="sent_invitations",
        foreign_keys=[inviter_id],
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('CREATOR', 'REVIEWER')",
            name="chk_invitation_role",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'ACCEPTED', 'REVOKED', 'EXPIRED')",
            name="chk_invitation_status",
        ),
        Index("idx_invitation_org_status", "organization_id", "status"),
        Index("idx_invitation_email_org", "email", "organization_id"),
    )
