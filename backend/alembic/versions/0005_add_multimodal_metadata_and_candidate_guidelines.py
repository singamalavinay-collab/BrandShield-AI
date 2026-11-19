"""Add multimodal submission metadata and candidate guidelines staging table (Phase 0C).

Revision ID: 0005_add_multimodal_metadata_and_candidate_guidelines
Revises: 0004_protect_audit_history_and_archival
Create Date: 2026-11-19 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0005_add_multimodal_metadata_and_candidate_guidelines"
down_revision: Union[str, None] = "0004_protect_audit_history_and_archival"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else "sqlite"

    # Widen alembic_version.version_num on PostgreSQL if needed
    if dialect == "postgresql":
        op.execute("ALTER TABLE IF EXISTS alembic_version ALTER COLUMN version_num TYPE VARCHAR(128);")

    # Select JSON column type based on engine dialect
    json_col_type = postgresql.JSONB() if dialect == "postgresql" else sa.JSON()

    # 1. Extend content_submissions with multimodal metadata columns
    with op.batch_alter_table("content_submissions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "media_type",
                sa.String(length=50),
                nullable=False,
                server_default="text",
            )
        )
        batch_op.add_column(
            sa.Column(
                "file_hash_sha256",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "mime_type",
                sa.String(length=100),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "file_size_bytes",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "multimodal_metadata",
                json_col_type,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.create_index("ix_content_submissions_media_type", ["media_type"])
        batch_op.create_index("ix_content_submissions_file_hash_sha256", ["file_hash_sha256"])
        batch_op.create_index(
            "idx_submissions_org_media_type",
            ["organization_id", "media_type"],
        )

    # 2. Create candidate_guidelines table
    op.create_table(
        "candidate_guidelines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("rule_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("directive", sa.Text(), nullable=False),
        sa.Column("examples_approved", json_col_type, nullable=False),
        sa.Column("examples_prohibited", json_col_type, nullable=False),
        sa.Column("tags", json_col_type, nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("source_metadata", json_col_type, nullable=False),
        sa.Column("source_submission_id", sa.Uuid(), nullable=True),
        sa.Column("extraction_status", sa.String(length=50), nullable=False, server_default="EXTRACTED"),
        sa.Column("review_status", sa.String(length=50), nullable=False, server_default="PENDING_APPROVAL"),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("approved_guideline_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_guideline_id"], ["brand_guidelines.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_submission_id"], ["content_submissions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "review_status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')",
            name="chk_candidate_review_status",
        ),
        sa.CheckConstraint(
            "review_status != 'APPROVED' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="chk_candidate_approved_has_reviewer_and_time",
        ),
    )

    op.create_index("ix_candidate_guidelines_id", "candidate_guidelines", ["id"])
    op.create_index("ix_candidate_guidelines_organization_id", "candidate_guidelines", ["organization_id"])
    op.create_index("ix_candidate_guidelines_rule_type", "candidate_guidelines", ["rule_type"])
    op.create_index("ix_candidate_guidelines_review_status", "candidate_guidelines", ["review_status"])
    op.create_index("ix_candidate_guidelines_extraction_status", "candidate_guidelines", ["extraction_status"])
    op.create_index("ix_candidate_guidelines_source_submission_id", "candidate_guidelines", ["source_submission_id"])
    op.create_index(
        "idx_candidate_guidelines_org_status",
        "candidate_guidelines",
        ["organization_id", "review_status"],
    )
    op.create_index(
        "idx_candidate_guidelines_org_created",
        "candidate_guidelines",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    # 1. Drop candidate_guidelines table and all its constraints/indexes
    op.drop_table("candidate_guidelines")

    # 2. Revert content_submissions additions
    with op.batch_alter_table("content_submissions") as batch_op:
        batch_op.drop_index("idx_submissions_org_media_type")
        batch_op.drop_index("ix_content_submissions_file_hash_sha256")
        batch_op.drop_index("ix_content_submissions_media_type")
        batch_op.drop_column("multimodal_metadata")
        batch_op.drop_column("file_size_bytes")
        batch_op.drop_column("mime_type")
        batch_op.drop_column("file_hash_sha256")
        batch_op.drop_column("media_type")
