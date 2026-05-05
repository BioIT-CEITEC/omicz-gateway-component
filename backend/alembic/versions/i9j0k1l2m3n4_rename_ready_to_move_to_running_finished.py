"""rename ready_to_move to running_finished in runs status

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-05-05

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, Sequence[str], None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename ready_to_move → running_finished in runs and runs_status_history."""
    op.execute("UPDATE runs SET status = 'running_finished' WHERE status = 'ready_to_move'")
    op.execute("UPDATE runs_status_history SET status = 'running_finished' WHERE status = 'ready_to_move'")


def downgrade() -> None:
    """Revert running_finished → ready_to_move in runs and runs_status_history."""
    op.execute("UPDATE runs SET status = 'ready_to_move' WHERE status = 'running_finished'")
    op.execute("UPDATE runs_status_history SET status = 'ready_to_move' WHERE status = 'running_finished'")
