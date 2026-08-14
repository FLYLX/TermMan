"""Drop item handler agent profile

Revision ID: f3a9c1e5d207
Revises: c4e8f1a2b3d4
Create Date: 2026-08-14 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "f3a9c1e5d207"
down_revision = "c4e8f1a2b3d4"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        column.get("name") == column_name
        for column in inspector.get_columns(table_name)
    )


def upgrade() -> None:
    if _has_column("itemhandler", "agent_profile"):
        op.drop_column("itemhandler", "agent_profile")


def downgrade() -> None:
    if not _has_column("itemhandler", "agent_profile"):
        op.add_column(
            "itemhandler",
            sa.Column("agent_profile", sa.JSON(), nullable=True),
        )
    op.execute("UPDATE itemhandler SET agent_profile = '{}' WHERE agent_profile IS NULL")
