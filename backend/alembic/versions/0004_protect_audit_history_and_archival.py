"""Protect audit history and add submission archival.

Revision ID: 0004_protect_audit_history_and_archival
Revises: 0003_add_team_invitations_table
Create Date: 2026-11-14 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_protect_audit_history_and_archival"
down_revision: Union[str, None] = "0003_add_team_invitations_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

naming_convention = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade() -> None:
    # 1. Add archival columns to content_submissions with server default for backward compatibility
    with op.batch_alter_table("content_submissions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_archived",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "archived_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_index("ix_content_submissions_is_archived", ["is_archived"])

    # 2. Hardening: Update audit_entries foreign keys from CASCADE to RESTRICT
    with op.batch_alter_table("audit_entries", naming_convention=naming_convention) as batch_op:
        batch_op.drop_constraint(
            "fk_audit_entries_organization_id_organizations",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_audit_entries_submission_id_content_submissions",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_audit_entries_organization_id",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_audit_entries_submission_id",
            "content_submissions",
            ["submission_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    # 3. Add database-level immutability triggers (discrete statements for driver compatibility)
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else "sqlite"

    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_entries_no_update
            BEFORE UPDATE ON audit_entries
            BEGIN
                SELECT RAISE(ABORT, 'Audit entries are immutable and cannot be updated at the database level.');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_entries_no_delete
            BEFORE DELETE ON audit_entries
            BEGIN
                SELECT RAISE(ABORT, 'Audit entries are immutable and cannot be deleted at the database level.');
            END;
            """
        )
    elif dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION trg_prevent_audit_entries_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Audit entries are immutable and cannot be updated or deleted at the database level.';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute("DROP TRIGGER IF EXISTS trg_audit_entries_no_update ON audit_entries;")
        op.execute(
            """
            CREATE TRIGGER trg_audit_entries_no_update
            BEFORE UPDATE ON audit_entries
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_audit_entries_mutation();
            """
        )
        op.execute("DROP TRIGGER IF EXISTS trg_audit_entries_no_delete ON audit_entries;")
        op.execute(
            """
            CREATE TRIGGER trg_audit_entries_no_delete
            BEFORE DELETE ON audit_entries
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_audit_entries_mutation();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else "sqlite"

    # 1. Drop database-level immutability triggers
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_entries_no_delete;")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_entries_no_update;")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_entries_no_delete ON audit_entries;")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_entries_no_update ON audit_entries;")
        op.execute("DROP FUNCTION IF EXISTS trg_prevent_audit_entries_mutation();")

    # 2. Revert audit_entries foreign keys
    with op.batch_alter_table("audit_entries", naming_convention=naming_convention) as batch_op:
        batch_op.drop_constraint("fk_audit_entries_submission_id", type_="foreignkey")
        batch_op.drop_constraint("fk_audit_entries_organization_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_audit_entries_organization_id_organizations",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_audit_entries_submission_id_content_submissions",
            "content_submissions",
            ["submission_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # 3. Drop archival columns from content_submissions
    with op.batch_alter_table("content_submissions") as batch_op:
        batch_op.drop_index("ix_content_submissions_is_archived")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("is_archived")
