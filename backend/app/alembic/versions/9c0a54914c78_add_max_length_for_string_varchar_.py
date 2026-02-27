"""Add max length for string(varchar) fields in User and Items models

Revision ID: 9c0a54914c78
Revises: e2412789c190
Create Date: 2024-06-17 14:42:44.639457

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '9c0a54914c78'
down_revision = 'e2412789c190'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite doesn't support ALTER COLUMN to change column type
    # We need to create new tables with the correct column types and copy data
    
    # Create new user table with correct column lengths
    op.create_table(
        'user_new',
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_superuser', sa.Boolean(), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_new_email'), 'user_new', ['email'], unique=True)
    
    # Copy data from old user table to new user table
    op.execute('INSERT INTO user_new (id, email, is_active, is_superuser, full_name, hashed_password) SELECT id, email, is_active, is_superuser, full_name, hashed_password FROM "user"')
    
    # Drop old user table and rename new one
    op.drop_table('user')
    op.rename_table('user_new', 'user')
    
    # Create new item table with correct column lengths
    op.create_table(
        'item_new',
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['owner_id'],
            ['user.id'],
        ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Copy data from old item table to new item table
    op.execute('INSERT INTO item_new (id, title, description, owner_id) SELECT id, title, description, owner_id FROM item')
    
    # Drop old item table and rename new one
    op.drop_table('item')
    op.rename_table('item_new', 'item')


def downgrade():
    # Revert to original column lengths without constraints
    
    # Create original user table
    op.create_table(
        'user_old',
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_superuser', sa.Boolean(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_old_email'), 'user_old', ['email'], unique=True)
    
    # Copy data back to original user table
    op.execute('INSERT INTO user_old (id, email, is_active, is_superuser, full_name, hashed_password) SELECT id, email, is_active, is_superuser, full_name, hashed_password FROM "user"')
    
    # Drop current user table and rename old one
    op.drop_table('user')
    op.rename_table('user_old', 'user')
    
    # Create original item table
    op.create_table(
        'item_old',
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
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