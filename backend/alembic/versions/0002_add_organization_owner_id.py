"""Add owner_id to organizations table.

Revision ID: 0002_add_organization_owner_id
Revises: 0001_initial_core_schema
Create Date: 2026-11-14 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_add_organization_owner_id"
down_revision: Union[str, None] = "0001_initial_core_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.Uuid(), nullable=True))
        batch_op.create_index("ix_organizations_owner_id", ["owner_id"])
        batch_op.create_foreign_key(
            "fk_organizations_owner_id",
            "users",
            ["owner_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_constraint("fk_organizations_owner_id", type_="foreignkey")
        batch_op.drop_index("ix_organizations_owner_id")
        batch_op.drop_column("owner_id")
