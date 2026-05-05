"""rename completed to ready_to_move in runs status

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename completed → ready_to_move in runs and runs_status_history."""
    op.execute("UPDATE runs SET status = 'ready_to_move' WHERE status = 'completed'")
    op.execute("UPDATE runs_status_history SET status = 'ready_to_move' WHERE status = 'completed'")


def downgrade() -> None:
    """Revert ready_to_move → completed in runs and runs_status_history."""
    op.execute("UPDATE runs SET status = 'completed' WHERE status = 'ready_to_move'")
    op.execute("UPDATE runs_status_history SET status = 'completed' WHERE status = 'ready_to_move'")
