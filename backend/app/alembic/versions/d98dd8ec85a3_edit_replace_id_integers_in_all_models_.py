"""Edit replace id integers in all models to use UUID instead

Revision ID: d98dd8ec85a3
Revises: 9c0a54914c78
Create Date: 2024-07-19 04:08:04.000976

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'd98dd8ec85a3'
down_revision = '9c0a54914c78'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite doesn't support CREATE EXTENSION, remove that line
    # SQLite also doesn't support ALTER COLUMN to set NOT NULL directly
    # We need to use a different approach
    
    # Create new user table with UUID column
    op.create_table(
        'user_new',
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_superuser', sa.Boolean(), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('id', sa.String(36), nullable=False, default=sa.text("(lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))))")),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_new_email_unique', 'user_new', ['email'], unique=True)
    
    # Copy data from old user table to new user table with UUIDs
    op.execute('''
        INSERT INTO user_new (email, is_active, is_superuser, full_name, id, hashed_password)
        SELECT email, is_active, is_superuser, full_name, 
               (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
               hashed_password
        FROM "user"
    ''')
    
    # Create new item table with UUID columns
    op.create_table(
        'item_new',
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('id', sa.String(36), nullable=False, default=sa.text("(lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))))")),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('owner_id', sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ['owner_id'],
            ['user_new.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Copy data from old item table to new item table with UUIDs
    op.execute('''
        INSERT INTO item_new (title, description, id, owner_id)
        SELECT i.title, i.description, 
               (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
               u.id
        FROM item i
        JOIN user_new u ON i.owner_id = (SELECT id FROM "user" WHERE rowid = i.owner_id)
    ''')
    
    # Drop old tables
    op.drop_table('item')
    op.drop_table('user')
    
    # Rename new tables
    op.rename_table('user_new', 'user')
    op.rename_table('item_new', 'item')


def downgrade():
    # Reverse the upgrade process - create tables with integer IDs
    
    # Create original user table with integer ID
    op.create_table(
        'user_old',
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_superuser', sa.Boolean(), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_old_email_unique', 'user_old', ['email'], unique=True)
    
    # Copy data back to original user table with sequential IDs
    op.execute('''
        INSERT INTO user_old (email, is_active, is_superuser, full_name, id, hashed_password)
        SELECT email, is_active, is_superuser, full_name, rowid, hashed_password
        FROM "user"
    ''')
    
    # Create original item table with integer ID
    op.create_table(
        'item_old',
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['owner_id'],
            ['user_old.id'],
        ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Copy data back to original item table
    op.execute('''
        INSERT INTO item_old (title, description, id, owner_id)
        SELECT i.title, i.description, rowid, u.id
        FROM item i
        JOIN user_old u ON i.owner_id = u.id
    ''')
    
    # Drop current tables
    op.drop_table('item')
    op.drop_table('user')
    
    # Rename old tables
    op.rename_table('user_old', 'user')
    op.rename_table('item_old', 'item')