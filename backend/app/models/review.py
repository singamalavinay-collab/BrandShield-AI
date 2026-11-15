from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, ImmutableAuditError

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.submission import ContentSubmission
    from app.models.user import User


class ReviewDecision(Base):
    """Human governance review decision for a content submission."""

    __tablename__ = "review_decisions"

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
        default=1,
        nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    feedback: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    edited_content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    submission: Mapped["ContentSubmission"] = relationship(
        "ContentSubmission",
        back_populates="review_decisions",
        foreign_keys=[submission_id],
        lazy="selectin",
    )
    reviewer: Mapped["User"] = relationship(
        "User",
        back_populates="reviews_conducted",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "action != 'edit_and_approve' OR (edited_content IS NOT NULL AND length(trim(edited_content)) > 0)",
            name="chk_review_edit_content",
        ),
        CheckConstraint(
            "action NOT IN ('reject', 'request_revision') OR (feedback IS NOT NULL AND length(trim(feedback)) > 0)",
            name="chk_review_feedback",
        ),
    )


class AuditEntry(Base):
    """Immutable ledger record tracking all governance events and state transitions."""

    __tablename__ = "audit_entries"

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
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_submissions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    previous_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    new_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    action_type: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    actor_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    actor_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    details: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "new_status != 'approved' OR actor_type = 'human'",
            name="chk_audit_human_approval_only",
        ),
        Index("idx_audit_org_sub_time", "organization_id", "submission_id", "timestamp"),
    )


# Enforce Immutability of AuditEntry at the ORM layer during flush
@event.listens_for(AuditEntry, "before_update")
def prevent_audit_update(mapper: Any, connection: Any, target: Any) -> None:
    raise ImmutableAuditError("Audit entries are immutable and cannot be updated.")


@event.listens_for(AuditEntry, "before_delete")
def prevent_audit_delete(mapper: Any, connection: Any, target: Any) -> None:
    raise ImmutableAuditError("Audit entries are immutable and cannot be deleted.")


# Register database-level triggers on table creation (for SQLite in-memory tests and PostgreSQL engines)
@event.listens_for(AuditEntry.__table__, "after_create")
def register_audit_database_triggers(target: Any, connection: Any, **kw: Any) -> None:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_entries_no_update
            BEFORE UPDATE ON audit_entries
            BEGIN
                SELECT RAISE(ABORT, 'Audit entries are immutable and cannot be updated at the database level.');
            END;
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_entries_no_delete
            BEFORE DELETE ON audit_entries
            BEGIN
                SELECT RAISE(ABORT, 'Audit entries are immutable and cannot be deleted at the database level.');
            END;
            """
        )
    elif dialect == "postgresql":
        # Execute PostgreSQL DDL as discrete, individual statements for driver compatibility
        connection.exec_driver_sql(
            """
            CREATE OR REPLACE FUNCTION trg_prevent_audit_entries_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Audit entries are immutable and cannot be updated or deleted at the database level.';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_audit_entries_no_update ON audit_entries;")
        connection.exec_driver_sql(
            """
            CREATE TRIGGER trg_audit_entries_no_update
            BEFORE UPDATE ON audit_entries
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_audit_entries_mutation();
            """
        )
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_audit_entries_no_delete ON audit_entries;")
        connection.exec_driver_sql(
            """
            CREATE TRIGGER trg_audit_entries_no_delete
            BEFORE DELETE ON audit_entries
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_audit_entries_mutation();
            """
        )
