"""add uuid to all tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-22 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() auto-populates existing rows
    op.add_column('users',
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()'))
    )
    op.create_index('ix_users_uuid', 'users', ['uuid'], unique=True)

    op.add_column('sequencers',
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()'))
    )
    op.create_index('ix_sequencers_uuid', 'sequencers', ['uuid'], unique=True)

    op.add_column('runs',
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()'))
    )
    op.create_index('ix_runs_uuid', 'runs', ['uuid'], unique=True)

    op.add_column('sequencers_types',
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()'))
    )
    op.create_index('ix_sequencers_types_uuid', 'sequencers_types', ['uuid'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_sequencers_types_uuid', table_name='sequencers_types')
    op.drop_column('sequencers_types', 'uuid')

    op.drop_index('ix_runs_uuid', table_name='runs')
    op.drop_column('runs', 'uuid')

    op.drop_index('ix_sequencers_uuid', table_name='sequencers')
    op.drop_column('sequencers', 'uuid')

    op.drop_index('ix_users_uuid', table_name='users')
    op.drop_column('users', 'uuid')
