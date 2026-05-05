"""change type_id to type_uuid in sequencers

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-22 00:03:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add the new type_uuid column (nullable for now)
    op.add_column('sequencers',
        sa.Column('type_uuid', postgresql.UUID(as_uuid=True), nullable=True)
    )

    # 2. Populate type_uuid from existing type_id via join with sequencers_types
    op.execute("""
        UPDATE sequencers
        SET type_uuid = sequencers_types.uuid
        FROM sequencers_types
        WHERE sequencers.type_id = sequencers_types.id
    """)

    # 3. Drop the old integer FK column
    op.drop_constraint('sequencers_type_id_fkey', 'sequencers', type_='foreignkey')
    op.drop_column('sequencers', 'type_id')

    # 4. Add FK constraint from type_uuid to sequencers_types.uuid
    op.create_foreign_key(
        'sequencers_type_uuid_fkey',
        'sequencers', 'sequencers_types',
        ['type_uuid'], ['uuid']
    )

    # 5. Add index
    op.create_index('ix_sequencers_type_uuid', 'sequencers', ['type_uuid'])


def downgrade() -> None:
    op.drop_index('ix_sequencers_type_uuid', table_name='sequencers')
    op.drop_constraint('sequencers_type_uuid_fkey', 'sequencers', type_='foreignkey')

    op.add_column('sequencers',
        sa.Column('type_id', sa.Integer(), nullable=True)
    )

    op.execute("""
        UPDATE sequencers
        SET type_id = sequencers_types.id
        FROM sequencers_types
        WHERE sequencers.type_uuid = sequencers_types.uuid
    """)

    op.drop_column('sequencers', 'type_uuid')

    op.create_foreign_key(
        'sequencers_type_id_fkey',
        'sequencers', 'sequencers_types',
        ['type_id'], ['id']
    )
