"""Add team_invitations table.

Revision ID: 0003_add_team_invitations_table
Revises: 0002_add_organization_owner_id
Create Date: 2026-11-14 11:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_add_team_invitations_table"
down_revision: Union[str, None] = "0002_add_organization_owner_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "team_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("inviter_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="PENDING", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('CREATOR', 'REVIEWER')", name="chk_invitation_role"),
        sa.CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'REVOKED', 'EXPIRED')", name="chk_invitation_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inviter_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_team_invitations_id", "team_invitations", ["id"], unique=False)
    op.create_index("ix_team_invitations_organization_id", "team_invitations", ["organization_id"], unique=False)
    op.create_index("ix_team_invitations_inviter_id", "team_invitations", ["inviter_id"], unique=False)
    op.create_index("ix_team_invitations_email", "team_invitations", ["email"], unique=False)
    op.create_index("ix_team_invitations_token_hash", "team_invitations", ["token_hash"], unique=True)
    op.create_index("ix_team_invitations_status", "team_invitations", ["status"], unique=False)
    op.create_index("ix_team_invitations_expires_at", "team_invitations", ["expires_at"], unique=False)
    op.create_index("idx_invitation_org_status", "team_invitations", ["organization_id", "status"], unique=False)
    op.create_index("idx_invitation_email_org", "team_invitations", ["email", "organization_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_invitation_email_org", table_name="team_invitations")
    op.drop_index("idx_invitation_org_status", table_name="team_invitations")
    op.drop_index("ix_team_invitations_expires_at", table_name="team_invitations")
    op.drop_index("ix_team_invitations_status", table_name="team_invitations")
    op.drop_index("ix_team_invitations_token_hash", table_name="team_invitations")
    op.drop_index("ix_team_invitations_email", table_name="team_invitations")
    op.drop_index("ix_team_invitations_inviter_id", table_name="team_invitations")
    op.drop_index("ix_team_invitations_organization_id", table_name="team_invitations")
    op.drop_index("ix_team_invitations_id", table_name="team_invitations")
    op.drop_table("team_invitations")
