"""Add risk assessment fields to compliance reports and create claim_verifications table (Phase 1, Milestone 1).

Revision ID: 0007_add_risk_assessment_and_claim_verification
Revises: 0006_enforce_rls_and_candidate_audit_ledger
Create Date: 2026-11-19 18:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0007_add_risk_assessment_and_claim_verification"
down_revision: Union[str, None] = "0006_enforce_rls_and_candidate_audit_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else "sqlite"
    json_col_type = postgresql.JSONB() if dialect == "postgresql" else sa.JSON()
    false_default = sa.text("false" if dialect == "postgresql" else "0")

    # 1. Add risk assessment fields to compliance_reports
    with op.batch_alter_table("compliance_reports") as batch_op:
        batch_op.add_column(
            sa.Column("risk_score", sa.Float(), nullable=False, server_default="0.0")
        )
        batch_op.add_column(
            sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="LOW")
        )
        batch_op.add_column(
            sa.Column("is_escalated", sa.Boolean(), nullable=False, server_default=false_default)
        )
        batch_op.add_column(
            sa.Column("channel_multiplier", sa.Float(), nullable=False, server_default="1.0")
        )
        batch_op.add_column(
            sa.Column("audience_multiplier", sa.Float(), nullable=False, server_default="1.0")
        )
        batch_op.add_column(
            sa.Column("risk_breakdown", json_col_type, nullable=False, server_default=sa.text("'{}'"))
        )
        batch_op.create_index("ix_compliance_reports_risk_level", ["risk_level"])
        batch_op.create_index("ix_compliance_reports_is_escalated", ["is_escalated"])

    # Add check constraints on compliance_reports if PostgreSQL
    if dialect == "postgresql":
        op.create_check_constraint(
            "chk_report_risk_score_range",
            "compliance_reports",
            "risk_score >= 0.0 AND risk_score <= 100.0",
        )
        op.create_check_constraint(
            "chk_report_risk_level",
            "compliance_reports",
            "risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
        )
        op.create_check_constraint(
            "chk_report_multipliers_positive",
            "compliance_reports",
            "channel_multiplier > 0.0 AND audience_multiplier > 0.0",
        )

    # 2. Create claim_verifications table
    op.create_table(
        "claim_verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("document_name", sa.String(length=200), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("uncertainty_notes", sa.Text(), nullable=True),
        sa.Column("is_escalated", sa.Boolean(), nullable=False, server_default=false_default),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["compliance_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('VERIFIED', 'UNSUPPORTED', 'OUTDATED', 'CONTRADICTORY', 'NEEDS_HUMAN_REVIEW')",
            name="chk_claim_status",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="chk_claim_confidence_range",
        ),
        sa.CheckConstraint(
            "length(trim(claim_text)) > 0",
            name="chk_claim_text_non_empty",
        ),
    )

    op.create_index("ix_claim_verifications_id", "claim_verifications", ["id"])
    op.create_index("ix_claim_verifications_organization_id", "claim_verifications", ["organization_id"])
    op.create_index("ix_claim_verifications_report_id", "claim_verifications", ["report_id"])
    op.create_index("ix_claim_verifications_status", "claim_verifications", ["status"])
    op.create_index("idx_claim_verifications_org_status", "claim_verifications", ["organization_id", "status"])
    op.create_index("idx_claim_verifications_report_escalated", "claim_verifications", ["report_id", "is_escalated"])

    # 3. PostgreSQL-Specific Security Controls: Tenant Cross-Check Trigger, RLS, and Least-Privilege Grants
    if dialect == "postgresql":
        # A. Database-level trigger to guarantee a claim cannot reference a report belonging to another organization
        op.execute("""
            CREATE OR REPLACE FUNCTION trg_check_claim_verification_org()
            RETURNS TRIGGER AS $$
            DECLARE
                v_report_org_id UUID;
            BEGIN
                SELECT s.organization_id INTO v_report_org_id
                FROM compliance_reports r
                JOIN content_submissions s ON s.id = r.submission_id
                WHERE r.id = NEW.report_id;

                IF v_report_org_id IS NULL THEN
                    RAISE EXCEPTION 'Referenced compliance report % does not exist or has no valid submission organization.', NEW.report_id;
                END IF;

                IF NEW.organization_id != v_report_org_id THEN
                    RAISE EXCEPTION 'Cross-tenant violation: claim organization_id % does not match report organization_id %.', NEW.organization_id, v_report_org_id;
                END IF;

                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        op.execute("DROP TRIGGER IF EXISTS trg_claim_verification_org_match ON claim_verifications;")
        op.execute("""
            CREATE TRIGGER trg_claim_verification_org_match
            BEFORE INSERT OR UPDATE ON claim_verifications
            FOR EACH ROW EXECUTE FUNCTION trg_check_claim_verification_org();
        """)

        # B. Enforce and Force Row-Level Security on claim_verifications
        op.execute("ALTER TABLE claim_verifications ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE claim_verifications FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS claim_verifications_tenant_isolation ON claim_verifications;")
        op.execute("""
            CREATE POLICY claim_verifications_tenant_isolation ON claim_verifications
                FOR ALL
                TO PUBLIC
                USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
                WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
        """)

        # C. Grant granular least-privilege DML to runtime role brandshield_app if present
        # Immutability invariant: claims are immutable records of compliance verification.
        # SELECT, INSERT, DELETE are granted (DELETE is required for ON DELETE CASCADE when parent report is deleted).
        # UPDATE and TRUNCATE are explicitly NOT granted.
        op.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'brandshield_app') THEN
                    GRANT SELECT, INSERT, DELETE ON claim_verifications TO brandshield_app;
                END IF;
            END
            $$;
        """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else "sqlite"

    if dialect == "postgresql":
        # 1. Revoke privileges and drop security controls
        op.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'brandshield_app') THEN
                    REVOKE ALL ON claim_verifications FROM brandshield_app;
                END IF;
            END
            $$;
        """)
        op.execute("DROP POLICY IF EXISTS claim_verifications_tenant_isolation ON claim_verifications;")
        op.execute("ALTER TABLE claim_verifications NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE claim_verifications DISABLE ROW LEVEL SECURITY;")
        op.execute("DROP TRIGGER IF EXISTS trg_claim_verification_org_match ON claim_verifications;")
        op.execute("DROP FUNCTION IF EXISTS trg_check_claim_verification_org();")

        # 2. Drop check constraints on compliance_reports
        op.drop_constraint("chk_report_risk_score_range", "compliance_reports", type_="check")
        op.drop_constraint("chk_report_risk_level", "compliance_reports", type_="check")
        op.drop_constraint("chk_report_multipliers_positive", "compliance_reports", type_="check")

    # 3. Drop claim_verifications table
    op.drop_table("claim_verifications")

    # 4. Revert columns on compliance_reports
    with op.batch_alter_table("compliance_reports") as batch_op:
        batch_op.drop_index("ix_compliance_reports_is_escalated")
        batch_op.drop_index("ix_compliance_reports_risk_level")
        batch_op.drop_column("risk_breakdown")
        batch_op.drop_column("audience_multiplier")
        batch_op.drop_column("channel_multiplier")
        batch_op.drop_column("is_escalated")
        batch_op.drop_column("risk_level")
        batch_op.drop_column("risk_score")
