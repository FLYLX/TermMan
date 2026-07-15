"""Add item handler model parameters

Revision ID: c4e8f1a2b3d4
Revises: b7c4d8e9f012
Create Date: 2026-07-15 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "c4e8f1a2b3d4"
down_revision = "b7c4d8e9f012"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        column.get("name") == column_name
        for column in inspector.get_columns(table_name)
    )


def upgrade() -> None:
    if not _has_column("itemhandler", "model_parameters"):
        op.add_column(
            "itemhandler",
            sa.Column("model_parameters", sa.JSON(), nullable=True),
        )
    op.execute(
        "UPDATE itemhandler SET model_parameters = '{}' "
        "WHERE model_parameters IS NULL"
    )


def downgrade() -> None:
    if _has_column("itemhandler", "model_parameters"):
        op.drop_column("itemhandler", "model_parameters")
