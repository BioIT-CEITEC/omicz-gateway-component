"""add exclusions to sequencers

Revision ID: c3d4e5f6a7b8
Revises: b25ed21abb6a
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b25ed21abb6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sequencers', sa.Column('exclusions', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('sequencers', 'exclusions')
