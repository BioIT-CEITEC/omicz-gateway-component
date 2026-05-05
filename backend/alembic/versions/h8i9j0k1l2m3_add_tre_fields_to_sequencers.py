"""add sent_to_tre and delete_after_confirmation to sequencers

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-05-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, Sequence[str], None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Controls whether zipping+moving to TRE is triggered automatically
    # or waits for a manual button click after run_finished.
    # Values: 'auto' | 'manual'
    op.add_column('sequencers',
        sa.Column('sent_to_tre', sa.String(), nullable=False, server_default='manual')
    )

    # Controls whether zip deletion is triggered automatically
    # or waits for a manual button click after confirmation.
    # Values: 'auto' | 'manual'
    op.add_column('sequencers',
        sa.Column('delete_after_confirmation', sa.String(), nullable=False, server_default='manual')
    )


def downgrade() -> None:
    op.drop_column('sequencers', 'delete_after_confirmation')
    op.drop_column('sequencers', 'sent_to_tre')
