"""Add cascade delete relationships

Revision ID: 1a31ce608336
Revises: d98dd8ec85a3
Create Date: 2024-07-31 22:24:34.447891

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '1a31ce608336'
down_revision = 'd98dd8ec85a3'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite doesn't support ALTER COLUMN to change nullable constraint directly
    # We need to recreate the table with the correct foreign key constraint
    
    # Create new item table with CASCADE delete
    op.create_table(
        'item_new',
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('owner_id', sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ['owner_id'],
            ['user.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Copy data from old item table to new item table
    op.execute('INSERT INTO item_new (id, title, description, owner_id) SELECT id, title, description, owner_id FROM item')
    
    # Drop old item table and rename new one
    op.drop_table('item')
    op.rename_table('item_new', 'item')


def downgrade():
    # Revert to original foreign key without CASCADE
    
    # Create original item table
    op.create_table(
        'item_old',
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('owner_id', sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ['owner_id'],
            ['user.id'],
        ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Copy data back to original item table
    op.execute('INSERT INTO item_old (id, title, description, owner_id) SELECT id, title, description, owner_id FROM item')
    
    # Drop current item table and rename old one
    op.drop_table('item')
    op.rename_table('item_old', 'item')