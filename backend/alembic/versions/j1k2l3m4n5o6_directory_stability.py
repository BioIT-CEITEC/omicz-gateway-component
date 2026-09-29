"""directory_stability completion method

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'j1k2l3m4n5o6'
down_revision = 'i1j2k3l4m5n6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sequencers_types',
        sa.Column('dir_stability_minutes', sa.Integer(), nullable=True, server_default='10'))
    op.add_column('sequencers_types',
        sa.Column('run_stability_minutes', sa.Integer(), nullable=True, server_default='60'))

    op.add_column('runs', sa.Column('activity_fingerprint', sa.String(), nullable=True))
    op.add_column('runs', sa.Column('last_change_at', sa.DateTime(), nullable=True))

    op.create_table(
        'run_directories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_uuid', postgresql.UUID(as_uuid=True), sa.ForeignKey('runs.uuid'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False, server_default='waiting'),
        sa.Column('fingerprint', sa.String(), nullable=True),
        sa.Column('stable_since', sa.DateTime(), nullable=True),
        sa.Column('file_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('progress', sa.Text(), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('run_uuid', 'name', name='uq_run_directories_run_name'),
    )
    op.create_index('ix_run_directories_id', 'run_directories', ['id'])
    op.create_index('ix_run_directories_uuid', 'run_directories', ['uuid'], unique=True)
    op.create_index('ix_run_directories_run_uuid', 'run_directories', ['run_uuid'])

    op.create_table(
        'run_files',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('run_uuid', postgresql.UUID(as_uuid=True), sa.ForeignKey('runs.uuid'), nullable=False),
        sa.Column('rel_path', sa.String(), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('mtime_ns', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('uploaded', sa.Boolean(), nullable=False, server_default='false'),
        sa.UniqueConstraint('run_uuid', 'rel_path', name='uq_run_files_run_path'),
    )
    op.create_index('ix_run_files_id', 'run_files', ['id'])
    op.create_index('ix_run_files_run_uuid', 'run_files', ['run_uuid'])


def downgrade():
    op.drop_index('ix_run_files_run_uuid', table_name='run_files')
    op.drop_index('ix_run_files_id', table_name='run_files')
    op.drop_table('run_files')
    op.drop_index('ix_run_directories_run_uuid', table_name='run_directories')
    op.drop_index('ix_run_directories_uuid', table_name='run_directories')
    op.drop_index('ix_run_directories_id', table_name='run_directories')
    op.drop_table('run_directories')
    op.drop_column('runs', 'last_change_at')
    op.drop_column('runs', 'activity_fingerprint')
    op.drop_column('sequencers_types', 'run_stability_minutes')
    op.drop_column('sequencers_types', 'dir_stability_minutes')
