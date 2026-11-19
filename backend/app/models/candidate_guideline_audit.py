from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, ImmutableAuditError

if TYPE_CHECKING:
    from app.models.candidate_guideline import CandidateGuideline
    from app.models.organization import Organization

JSONB_COMPAT = JSON().with_variant(JSONB, "postgresql")


class CandidateGuidelineAuditEntry(Base):
    """Immutable audit record tracking all candidate guideline governance review actions.

    Architectural Invariants:
    1. Records every Admin APPROVE and REJECT decision with attribution.
    2. Strictly immutable: UPDATE and DELETE are prohibited at both ORM and database trigger levels.
    3. Retains full tenant boundary and candidate guideline foreign keys.
    """

    __tablename__ = "candidate_guideline_audit_entries"

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
    candidate_guideline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_guidelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    actor_type: Mapped[str] = mapped_column(
        String(30),
        default="human",
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
        JSONB_COMPAT,
        default=dict,
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        lazy="selectin",
    )
    candidate_guideline: Mapped["CandidateGuideline"] = relationship(
        "CandidateGuideline",
        back_populates="audit_entries",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "actor_type = 'human'",
            name="chk_cand_audit_human_only",
        ),
        CheckConstraint(
            "action IN ('APPROVE', 'REJECT')",
            name="chk_cand_audit_action",
        ),
        Index("idx_cand_audit_org_time", "organization_id", "timestamp"),
        Index("idx_cand_audit_cand_time", "candidate_guideline_id", "timestamp"),
    )


# Enforce immutability at the ORM layer during flush
@event.listens_for(CandidateGuidelineAuditEntry, "before_update")
def prevent_candidate_audit_update(mapper: Any, connection: Any, target: Any) -> None:
    raise ImmutableAuditError("Candidate guideline audit entries are immutable and cannot be updated.")


@event.listens_for(CandidateGuidelineAuditEntry, "before_delete")
def prevent_candidate_audit_delete(mapper: Any, connection: Any, target: Any) -> None:
    raise ImmutableAuditError("Candidate guideline audit entries are immutable and cannot be deleted.")


# Register database-level triggers on table creation for SQLite and PostgreSQL engines
@event.listens_for(CandidateGuidelineAuditEntry.__table__, "after_create")
def register_candidate_audit_database_triggers(target: Any, connection: Any, **kw: Any) -> None:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_cand_audit_no_update
            BEFORE UPDATE ON candidate_guideline_audit_entries
            BEGIN
                SELECT RAISE(ABORT, 'Candidate guideline audit entries are immutable and cannot be updated at the database level.');
            END;
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_cand_audit_no_delete
            BEFORE DELETE ON candidate_guideline_audit_entries
            BEGIN
                SELECT RAISE(ABORT, 'Candidate guideline audit entries are immutable and cannot be deleted at the database level.');
            END;
            """
        )
    elif dialect == "postgresql":
        connection.exec_driver_sql(
            """
            CREATE OR REPLACE FUNCTION trg_prevent_candidate_audit_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Candidate guideline audit entries are immutable and cannot be updated or deleted at the database level.';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_cand_audit_no_update ON candidate_guideline_audit_entries;")
        connection.exec_driver_sql(
            """
            CREATE TRIGGER trg_cand_audit_no_update
            BEFORE UPDATE ON candidate_guideline_audit_entries
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_candidate_audit_mutation();
            """
        )
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_cand_audit_no_delete ON candidate_guideline_audit_entries;")
        connection.exec_driver_sql(
            """
            CREATE TRIGGER trg_cand_audit_no_delete
            BEFORE DELETE ON candidate_guideline_audit_entries
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_candidate_audit_mutation();
            """
        )
