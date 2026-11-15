from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List, Optional
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.compliance import EvidenceCitation, RuleViolation
    from app.models.organization import Organization


class BrandGuideline(Base):
    """Brand guideline rule prescribing approved terminology, tone, and policies."""

    __tablename__ = "brand_guidelines"

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
        JSON,
        default=list,
        nullable=False,
    )
    examples_prohibited: Mapped[List[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    tags: Mapped[List[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
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
        back_populates="guidelines",
    )
    violations: Mapped[List["RuleViolation"]] = relationship(
        "RuleViolation",
        back_populates="rule",
    )
    evidence_citations: Mapped[List["EvidenceCitation"]] = relationship(
        "EvidenceCitation",
        back_populates="rule",
    )

    __table_args__ = (
        Index("idx_guidelines_org_active", "organization_id", "is_active"),
        Index("idx_guidelines_org_type", "organization_id", "rule_type"),
    )
