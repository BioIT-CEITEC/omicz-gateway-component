"""create runs_status_history table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'runs_status_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_uuid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['run_uuid'], ['runs.uuid']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_runs_status_history_id'), 'runs_status_history', ['id'], unique=False)
    op.create_index(op.f('ix_runs_status_history_uuid'), 'runs_status_history', ['uuid'], unique=True)
    op.create_index(op.f('ix_runs_status_history_run_uuid'), 'runs_status_history', ['run_uuid'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_runs_status_history_run_uuid'), table_name='runs_status_history')
    op.drop_index(op.f('ix_runs_status_history_uuid'), table_name='runs_status_history')
    op.drop_index(op.f('ix_runs_status_history_id'), table_name='runs_status_history')
    op.drop_table('runs_status_history')
