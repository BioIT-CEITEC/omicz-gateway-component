"""baseline stub — represents the existing DB schema before alembic files were lost

Revision ID: i9j0k1l2m3n4
Revises:
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Sequence, Union

revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
