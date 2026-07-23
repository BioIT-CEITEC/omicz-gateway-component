"""add progress to runs

Revision ID: f1a2b3c4d5e6
Revises: e15dd8d1750a
Create Date: 2026-07-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'e15dd8d1750a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('runs', sa.Column('progress', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('runs', 'progress')
