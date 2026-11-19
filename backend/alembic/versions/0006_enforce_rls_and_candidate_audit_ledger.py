"""Enforce PostgreSQL RLS on candidate guidelines and create immutable candidate audit ledger (Phase 0C Remediation).

Revision ID: 0006_enforce_rls_and_candidate_audit_ledger
Revises: 0005_add_multimodal_metadata_and_candidate_guidelines
Create Date: 2026-11-19 14:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0006_enforce_rls_and_candidate_audit_ledger"
down_revision: Union[str, None] = "0005_add_multimodal_metadata_and_candidate_guidelines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else "sqlite"
    json_col_type = postgresql.JSONB() if dialect == "postgresql" else sa.JSON()

    # 1. Create candidate_guideline_audit_entries table
    op.create_table(
        "candidate_guideline_audit_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_guideline_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("actor_type", sa.String(length=30), nullable=False, server_default="human"),
        sa.Column("actor_name", sa.String(length=150), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("details", json_col_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_guideline_id"], ["candidate_guidelines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("actor_type = 'human'", name="chk_cand_audit_human_only"),
        sa.CheckConstraint("action IN ('APPROVE', 'REJECT')", name="chk_cand_audit_action"),
    )

    op.create_index(
        "ix_candidate_guideline_audit_entries_id",
        "candidate_guideline_audit_entries",
        ["id"],
    )
    op.create_index(
        "ix_candidate_guideline_audit_entries_organization_id",
        "candidate_guideline_audit_entries",
        ["organization_id"],
    )
    op.create_index(
        "ix_candidate_guideline_audit_entries_candidate_guideline_id",
        "candidate_guideline_audit_entries",
        ["candidate_guideline_id"],
    )
    op.create_index(
        "ix_candidate_guideline_audit_entries_timestamp",
        "candidate_guideline_audit_entries",
        ["timestamp"],
    )
    op.create_index(
        "idx_cand_audit_org_time",
        "candidate_guideline_audit_entries",
        ["organization_id", "timestamp"],
    )
    op.create_index(
        "idx_cand_audit_cand_time",
        "candidate_guideline_audit_entries",
        ["candidate_guideline_id", "timestamp"],
    )

    # 2. PostgreSQL-specific security controls: RLS & Immutability Triggers
    if dialect == "postgresql":
        # A. Enforce and Force Row-Level Security on candidate_guidelines
        # FORCE ROW LEVEL SECURITY ensures the application role (even table owner neondb_owner) cannot bypass
        op.execute("ALTER TABLE candidate_guidelines ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE candidate_guidelines FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS candidate_guidelines_tenant_isolation ON candidate_guidelines;")
        op.execute("""
            CREATE POLICY candidate_guidelines_tenant_isolation ON candidate_guidelines
                FOR ALL
                TO PUBLIC
                USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
                WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
        """)

        # B. Enforce and Force Row-Level Security on candidate_guideline_audit_entries
        op.execute("ALTER TABLE candidate_guideline_audit_entries ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE candidate_guideline_audit_entries FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS candidate_guideline_audit_tenant_isolation ON candidate_guideline_audit_entries;")
        op.execute("""
            CREATE POLICY candidate_guideline_audit_tenant_isolation ON candidate_guideline_audit_entries
                FOR ALL
                TO PUBLIC
                USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
                WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
        """)

        # C. Database-level immutability triggers for candidate_guideline_audit_entries
        op.execute("""
            CREATE OR REPLACE FUNCTION trg_prevent_candidate_audit_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Candidate guideline audit entries are immutable and cannot be updated or deleted at the database level.';
            END;
            $$ LANGUAGE plpgsql;
        """)
        op.execute("DROP TRIGGER IF EXISTS trg_cand_audit_no_update ON candidate_guideline_audit_entries;")
        op.execute("""
            CREATE TRIGGER trg_cand_audit_no_update
            BEFORE UPDATE ON candidate_guideline_audit_entries
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_candidate_audit_mutation();
        """)
        op.execute("DROP TRIGGER IF EXISTS trg_cand_audit_no_delete ON candidate_guideline_audit_entries;")
        op.execute("""
            CREATE TRIGGER trg_cand_audit_no_delete
            BEFORE DELETE ON candidate_guideline_audit_entries
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_candidate_audit_mutation();
        """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else "sqlite"

    if dialect == "postgresql":
        # 1. Drop immutability triggers
        op.execute("DROP TRIGGER IF EXISTS trg_cand_audit_no_update ON candidate_guideline_audit_entries;")
        op.execute("DROP TRIGGER IF EXISTS trg_cand_audit_no_delete ON candidate_guideline_audit_entries;")
        op.execute("DROP FUNCTION IF EXISTS trg_prevent_candidate_audit_mutation();")

        # 2. Disable and drop RLS on candidate_guideline_audit_entries
        op.execute("DROP POLICY IF EXISTS candidate_guideline_audit_tenant_isolation ON candidate_guideline_audit_entries;")
        op.execute("ALTER TABLE candidate_guideline_audit_entries NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE candidate_guideline_audit_entries DISABLE ROW LEVEL SECURITY;")

        # 3. Disable and drop RLS on candidate_guidelines
        op.execute("DROP POLICY IF EXISTS candidate_guidelines_tenant_isolation ON candidate_guidelines;")
        op.execute("ALTER TABLE candidate_guidelines NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE candidate_guidelines DISABLE ROW LEVEL SECURITY;")

    # 4. Drop candidate_guideline_audit_entries table
    op.drop_table("candidate_guideline_audit_entries")
