"""baseline — creates all initial tables

Revision ID: i9j0k1l2m3n4
Revises:
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op


revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        'users',
        sa.Column('id',              sa.Integer(),  nullable=False),
        sa.Column('uuid',            UUID(as_uuid=True), nullable=False),
        sa.Column('username',        sa.String(),   nullable=False),
        sa.Column('email',           sa.String(),   nullable=False),
        sa.Column('hashed_password', sa.String(),   nullable=False),
        sa.Column('is_active',       sa.Boolean(),  nullable=True),
        sa.Column('is_deleted',      sa.Boolean(),  nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_id',       'users', ['id'],       unique=False)
    op.create_index('ix_users_uuid',     'users', ['uuid'],     unique=True)
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_email',    'users', ['email'],    unique=True)

    # ------------------------------------------------------------------
    # sequencers_types
    # Note: table was historically auto-named "sequencertypes" before
    # __tablename__ was set explicitly; the id index kept the old name
    # "ix_sequencertypes_id". b25ed21abb6a drops that name and creates
    # the new "ix_sequencers_types_id", so we must create it with the
    # old name here.
    # ------------------------------------------------------------------
    op.create_table(
        'sequencers_types',
        sa.Column('id',           sa.Integer(),  nullable=False),
        sa.Column('uuid',         UUID(as_uuid=True), nullable=False),
        sa.Column('name',         sa.String(),   nullable=False),
        # completion_signal was NOT NULL at baseline; d1e2f3a4b5c6 makes it nullable
        sa.Column('completion_signal', sa.String(), nullable=False),
        sa.Column('signal_match', sa.String(),   nullable=False, server_default='exact'),
        sa.Column('is_deleted',   sa.Boolean(),  nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid', name='uq_sequencers_types_uuid'),
    )
    # old name — b25ed21abb6a drops this and creates ix_sequencers_types_id
    op.create_index('ix_sequencertypes_id',           'sequencers_types', ['id'],   unique=False)
    op.create_index('ix_sequencers_types_uuid',       'sequencers_types', ['uuid'], unique=True)
    # partial unique index — b25ed21abb6a drops this too
    op.create_index(
        'uq_sequencers_types_name_active',
        'sequencers_types', ['name'],
        unique=True,
        postgresql_where=sa.text('is_deleted = false'),
    )

    # ------------------------------------------------------------------
    # sequencers
    # ------------------------------------------------------------------
    op.create_table(
        'sequencers',
        sa.Column('id',                       sa.Integer(),  nullable=False),
        sa.Column('uuid',                     UUID(as_uuid=True), nullable=False),
        sa.Column('name',                     sa.String(),   nullable=False),
        sa.Column('slug',                     sa.String(),   nullable=False),
        sa.Column('location',                 sa.String(),   nullable=False),
        sa.Column('author_id',                sa.Integer(),  nullable=True),
        sa.Column('type_uuid',                UUID(as_uuid=True), nullable=True),
        sa.Column('status',                   sa.String(),   nullable=False, server_default='active'),
        sa.Column('sent_to_tre',              sa.String(),   nullable=False, server_default='manual'),
        sa.Column('delete_after_confirmation', sa.String(),  nullable=False, server_default='manual'),
        sa.Column('is_deleted',               sa.Boolean(),  nullable=False, server_default='false'),
        sa.Column('created_at',               sa.DateTime(), nullable=True),
        sa.Column('updated_at',               sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.ForeignKeyConstraint(['type_uuid'], ['sequencers_types.uuid']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sequencers_id',   'sequencers', ['id'],   unique=False)
    op.create_index('ix_sequencers_uuid', 'sequencers', ['uuid'], unique=True)
    op.create_index('ix_sequencers_name', 'sequencers', ['name'], unique=False)
    op.create_index('ix_sequencers_slug', 'sequencers', ['slug'], unique=False)
    # indexes that b25ed21abb6a drops
    op.create_index('ix_sequencers_type_uuid', 'sequencers', ['type_uuid'], unique=False)
    op.create_index(
        'uq_sequencers_name_active',
        'sequencers', ['name'],
        unique=True,
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.create_index(
        'uq_sequencers_slug_active',
        'sequencers', ['slug'],
        unique=True,
        postgresql_where=sa.text('is_deleted = false'),
    )

    # ------------------------------------------------------------------
    # runs
    # Note: no 'progress' (added f1a2b3c4d5e6) or 'checksum_file' (added
    # 0b237ed2d834) at baseline.
    # ------------------------------------------------------------------
    op.create_table(
        'runs',
        sa.Column('id',             sa.Integer(),  nullable=False),
        sa.Column('uuid',           UUID(as_uuid=True), nullable=False),
        sa.Column('name',           sa.String(),   nullable=False),
        sa.Column('sequencer_uuid', UUID(as_uuid=True), nullable=False),
        sa.Column('status',         sa.String(),   nullable=False, server_default='running'),
        sa.Column('is_deleted',     sa.Boolean(),  nullable=False, server_default='false'),
        sa.Column('created_at',     sa.DateTime(), nullable=True),
        sa.Column('updated_at',     sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sequencer_uuid'], ['sequencers.uuid']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_runs_id',   'runs', ['id'],   unique=False)
    op.create_index('ix_runs_uuid', 'runs', ['uuid'], unique=True)
    # b25ed21abb6a drops these two
    op.create_index('ix_runs_sequencer_uuid', 'runs', ['sequencer_uuid'], unique=False)
    op.create_unique_constraint('uq_runs_sequencer_name', 'runs', ['sequencer_uuid', 'name'])

    # ------------------------------------------------------------------
    # runs_status_history
    # Note: no 'detail' column at baseline — b25ed21abb6a adds it.
    # ------------------------------------------------------------------
    op.create_table(
        'runs_status_history',
        sa.Column('id',         sa.Integer(),  nullable=False),
        sa.Column('uuid',       UUID(as_uuid=True), nullable=False),
        sa.Column('run_uuid',   UUID(as_uuid=True), nullable=False),
        sa.Column('status',     sa.String(),   nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['run_uuid'], ['runs.uuid']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_runs_status_history_id',       'runs_status_history', ['id'],       unique=False)
    op.create_index('ix_runs_status_history_uuid',     'runs_status_history', ['uuid'],     unique=True)
    op.create_index('ix_runs_status_history_run_uuid', 'runs_status_history', ['run_uuid'], unique=False)


def downgrade() -> None:
    op.drop_table('runs_status_history')
    op.drop_table('runs')
    op.drop_table('sequencers')
    op.drop_table('sequencers_types')
    op.drop_table('users')
