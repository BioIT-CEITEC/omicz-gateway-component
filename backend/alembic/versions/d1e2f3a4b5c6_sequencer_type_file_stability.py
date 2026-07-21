"""sequencer_type_file_stability

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sequencers_types',
        sa.Column('completion_method', sa.String(), nullable=False, server_default='signal'))

    op.alter_column('sequencers_types', 'completion_signal', nullable=True)

    op.add_column('sequencers_types',
        sa.Column('stability_files', sa.JSON(), nullable=True))

    op.add_column('sequencers_types',
        sa.Column('stability_threshold_minutes', sa.Integer(), nullable=True, server_default='10'))


def downgrade():
    op.drop_column('sequencers_types', 'stability_threshold_minutes')
    op.drop_column('sequencers_types', 'stability_files')
    op.alter_column('sequencers_types', 'completion_signal', nullable=False)
    op.drop_column('sequencers_types', 'completion_method')
