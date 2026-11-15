"""Initial core relational schema for BrandShield AI.

Revision ID: 0001_initial_core_schema
Revises: 
Create Date: 2026-11-13 21:42:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_initial_core_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Organizations
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_organizations_id", "organizations", ["id"])
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # 2. Users
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="CREATOR"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # 3. Brand Guidelines
    op.create_table(
        "brand_guidelines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("rule_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("directive", sa.Text(), nullable=False),
        sa.Column("examples_approved", sa.JSON(), nullable=False),
        sa.Column("examples_prohibited", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_guidelines_id", "brand_guidelines", ["id"])
    op.create_index("ix_brand_guidelines_organization_id", "brand_guidelines", ["organization_id"])
    op.create_index("ix_brand_guidelines_rule_type", "brand_guidelines", ["rule_type"])
    op.create_index("ix_brand_guidelines_is_active", "brand_guidelines", ["is_active"])
    op.create_index("idx_guidelines_org_active", "brand_guidelines", ["organization_id", "is_active"])
    op.create_index("idx_guidelines_org_type", "brand_guidelines", ["organization_id", "rule_type"])

    # 4. Content Submissions
    op.create_table(
        "content_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("target_channel", sa.String(length=50), nullable=False),
        sa.Column("target_audience", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("latest_review_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status != 'approved' OR latest_review_id IS NOT NULL", name="chk_submission_approved_has_review"),
        sa.CheckConstraint("version >= 1", name="chk_submission_version_positive"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_submissions_id", "content_submissions", ["id"])
    op.create_index("ix_content_submissions_organization_id", "content_submissions", ["organization_id"])
    op.create_index("ix_content_submissions_author_id", "content_submissions", ["author_id"])
    op.create_index("ix_content_submissions_status", "content_submissions", ["status"])
    op.create_index("idx_submissions_org_status", "content_submissions", ["organization_id", "status"])

    # 5. Compliance Reports
    op.create_table(
        "compliance_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("submission_version", sa.Integer(), nullable=False),
        sa.Column("is_compliant", sa.Boolean(), nullable=False),
        sa.Column("total_violations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("total_violations >= 0", name="chk_report_total_violations_non_negative"),
        sa.ForeignKeyConstraint(["submission_id"], ["content_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_compliance_reports_id", "compliance_reports", ["id"])
    op.create_index("ix_compliance_reports_submission_id", "compliance_reports", ["submission_id"])

    # 6. Rule Violations
    op.create_table(
        "rule_violations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_name", sa.String(length=200), nullable=False),
        sa.Column("rule_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("flagged_text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("char_start IS NULL OR char_start >= 0", name="chk_violation_char_start_non_negative"),
        sa.CheckConstraint("char_end IS NULL OR char_end >= 0", name="chk_violation_char_end_non_negative"),
        sa.ForeignKeyConstraint(["report_id"], ["compliance_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["brand_guidelines.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rule_violations_id", "rule_violations", ["id"])
    op.create_index("ix_rule_violations_report_id", "rule_violations", ["report_id"])
    op.create_index("ix_rule_violations_rule_id", "rule_violations", ["rule_id"])

    # 7. Evidence Citations (1:N from RuleViolation, supporting multiple citations per violation)
    op.create_table(
        "evidence_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("violation_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_name", sa.String(length=200), nullable=False),
        sa.Column("rule_type", sa.String(length=50), nullable=False),
        sa.Column("source_clause", sa.Text(), nullable=False),
        sa.Column("document_name", sa.String(length=200), nullable=False, server_default="Official Brand Guidelines"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("confidence_score >= 0.0 AND confidence_score <= 1.0", name="chk_evidence_confidence_range"),
        sa.ForeignKeyConstraint(["rule_id"], ["brand_guidelines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["violation_id"], ["rule_violations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_citations_id", "evidence_citations", ["id"])
    op.create_index("ix_evidence_citations_violation_id", "evidence_citations", ["violation_id"])
    op.create_index("ix_evidence_citations_rule_id", "evidence_citations", ["rule_id"])

    # 8. Correction Suggestions
    op.create_table(
        "correction_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("violation_id", sa.Uuid(), nullable=False),
        sa.Column("suggested_text", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="ai_generated"),
        sa.Column("diff_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["violation_id"], ["rule_violations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_correction_suggestions_id", "correction_suggestions", ["id"])
    op.create_index("ix_correction_suggestions_violation_id", "correction_suggestions", ["violation_id"])

    # 9. Review Decisions
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("submission_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("edited_content", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "action != 'edit_and_approve' OR (edited_content IS NOT NULL AND length(trim(edited_content)) > 0)",
            name="chk_review_edit_content",
        ),
        sa.CheckConstraint(
            "action NOT IN ('reject', 'request_revision') OR (feedback IS NOT NULL AND length(trim(feedback)) > 0)",
            name="chk_review_feedback",
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submission_id"], ["content_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_decisions_id", "review_decisions", ["id"])
    op.create_index("ix_review_decisions_submission_id", "review_decisions", ["submission_id"])
    op.create_index("ix_review_decisions_reviewer_id", "review_decisions", ["reviewer_id"])

    # Link ContentSubmission.latest_review_id foreign key constraint
    op.create_foreign_key(
        "fk_submission_latest_review",
        "content_submissions",
        "review_decisions",
        ["latest_review_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )

    # 10. Audit Entries (Immutable Ledger)
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("previous_status", sa.String(length=50), nullable=False),
        sa.Column("new_status", sa.String(length=50), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("actor_type", sa.String(length=30), nullable=False),
        sa.Column("actor_name", sa.String(length=150), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("new_status != 'approved' OR actor_type = 'human'", name="chk_audit_human_approval_only"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["content_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_entries_id", "audit_entries", ["id"])
    op.create_index("ix_audit_entries_organization_id", "audit_entries", ["organization_id"])
    op.create_index("ix_audit_entries_submission_id", "audit_entries", ["submission_id"])
    op.create_index("ix_audit_entries_timestamp", "audit_entries", ["timestamp"])
    op.create_index("idx_audit_org_sub_time", "audit_entries", ["organization_id", "submission_id", "timestamp"])


def downgrade() -> None:
    # Drop circular foreign key first
    op.drop_constraint("fk_submission_latest_review", "content_submissions", type_="foreignkey")

    # Drop tables in reverse dependency order
    op.drop_table("audit_entries")
    op.drop_table("review_decisions")
    op.drop_table("correction_suggestions")
    op.drop_table("evidence_citations")
    op.drop_table("rule_violations")
    op.drop_table("compliance_reports")
    op.drop_table("content_submissions")
    op.drop_table("brand_guidelines")
    op.drop_table("users")
    op.drop_table("organizations")
