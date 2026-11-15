from datetime import datetime, timezone
from typing import TYPE_CHECKING, List
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.invitation import TeamInvitation
    from app.models.organization import Organization
    from app.models.review import ReviewDecision
    from app.models.submission import ContentSubmission


class User(Base):
    """User account entity representing human actors and their permissions."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        default="CREATOR",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
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

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="users",
        foreign_keys=[organization_id],
        lazy="selectin",
    )
    authored_submissions: Mapped[List["ContentSubmission"]] = relationship(
        "ContentSubmission",
        back_populates="author",
        lazy="selectin",
    )
    reviews_conducted: Mapped[List["ReviewDecision"]] = relationship(
        "ReviewDecision",
        back_populates="reviewer",
        lazy="selectin",
    )
    sent_invitations: Mapped[List["TeamInvitation"]] = relationship(
        "TeamInvitation",
        back_populates="inviter",
        foreign_keys="TeamInvitation.inviter_id",
        lazy="selectin",
    )
