"""partial unique index on sequencer type name

Revision ID: g7h8i9j0k1l2
Revises: a7b8c9d0e1f2
Create Date: 2026-04-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old global unique constraint on name.
    # The constraint was created as sa.UniqueConstraint('name') on the original
    # 'sequencertypes' table, so PostgreSQL auto-named it 'sequencertypes_name_key'.
    # The table was later renamed to 'sequencers_types' but the constraint name didn't change.
    op.drop_constraint('sequencertypes_name_key', 'sequencers_types', type_='unique')

    # Create partial unique index — uniqueness only enforced on non-deleted rows
    # This allows re-using the same name after a record is soft-deleted
    op.execute("""
        CREATE UNIQUE INDEX uq_sequencers_types_name_active
        ON sequencers_types (name)
        WHERE is_deleted = false
    """)


def downgrade() -> None:
    op.drop_index('uq_sequencers_types_name_active', table_name='sequencers_types')
    op.create_unique_constraint('sequencertypes_name_key', 'sequencers_types', ['name'])
