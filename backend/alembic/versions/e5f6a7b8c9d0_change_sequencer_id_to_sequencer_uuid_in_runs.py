"""change sequencer_id to sequencer_uuid in runs

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop the unique constraint that references sequencer_id
    op.drop_constraint('uq_runs_sequencer_name', 'runs', type_='unique')

    # 2. Add the new sequencer_uuid column (nullable for now so existing rows are fine)
    op.add_column('runs',
        sa.Column('sequencer_uuid', postgresql.UUID(as_uuid=True), nullable=True)
    )

    # 3. Populate sequencer_uuid from sequencers.uuid via join on sequencer_id
    op.execute("""
        UPDATE runs
        SET sequencer_uuid = sequencers.uuid
        FROM sequencers
        WHERE runs.sequencer_id = sequencers.id
    """)

    # 4. Drop the old integer FK column (PostgreSQL auto-named the constraint)
    op.drop_constraint('runs_sequencer_id_fkey', 'runs', type_='foreignkey')
    op.drop_column('runs', 'sequencer_id')

    # 5. Now that all rows have a value, make sequencer_uuid NOT NULL
    op.alter_column('runs', 'sequencer_uuid', nullable=False)

    # 6. Add FK from sequencer_uuid to sequencers.uuid
    op.create_foreign_key(
        'runs_sequencer_uuid_fkey',
        'runs', 'sequencers',
        ['sequencer_uuid'], ['uuid']
    )

    # 7. Recreate the unique constraint using the new column
    op.create_unique_constraint('uq_runs_sequencer_name', 'runs', ['sequencer_uuid', 'name'])

    # 8. Add index
    op.create_index('ix_runs_sequencer_uuid', 'runs', ['sequencer_uuid'])


def downgrade() -> None:
    op.drop_index('ix_runs_sequencer_uuid', table_name='runs')
    op.drop_constraint('uq_runs_sequencer_name', 'runs', type_='unique')
    op.drop_constraint('runs_sequencer_uuid_fkey', 'runs', type_='foreignkey')

    op.add_column('runs',
        sa.Column('sequencer_id', sa.Integer(), nullable=True)
    )

    op.execute("""
        UPDATE runs
        SET sequencer_id = sequencers.id
        FROM sequencers
        WHERE runs.sequencer_uuid = sequencers.uuid
    """)

    op.drop_column('runs', 'sequencer_uuid')

    op.alter_column('runs', 'sequencer_id', nullable=False)

    op.create_foreign_key(
        'runs_sequencer_id_fkey',
        'runs', 'sequencers',
        ['sequencer_id'], ['id']
    )

    op.create_unique_constraint('uq_runs_sequencer_name', 'runs', ['sequencer_id', 'name'])
