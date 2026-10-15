"""login: admin flag and creation time on users, refresh tokens, server-side secrets

Revision ID: l1m2n3o4p5q6
Revises: k1l2m3n4o5p6
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'l1m2n3o4p5q6'
down_revision = 'k1l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.alter_column('users', 'email', existing_type=sa.String(), nullable=True)

    op.create_table(
        'refresh_tokens',
        sa.Column('id',          sa.Integer(), nullable=False),
        sa.Column('user_uuid',   UUID(as_uuid=True), sa.ForeignKey('users.uuid'), nullable=False),
        sa.Column('token_hash',  sa.String(64), nullable=False),
        sa.Column('expires_at',  sa.DateTime(), nullable=False),
        sa.Column('created_at',  sa.DateTime(), nullable=True),
        sa.Column('revoked_at',  sa.DateTime(), nullable=True),
        sa.Column('replaced_by', sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_refresh_tokens_id',         'refresh_tokens', ['id'],         unique=False)
    op.create_index('ix_refresh_tokens_user_uuid',  'refresh_tokens', ['user_uuid'],  unique=False)
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'], unique=True)

    op.create_table(
        'app_secrets',
        sa.Column('key',   sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade():
    op.drop_table('app_secrets')
    op.drop_index('ix_refresh_tokens_token_hash', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user_uuid', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_id', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.alter_column('users', 'email', existing_type=sa.String(), nullable=False)
    op.drop_column('users', 'created_at')
    op.drop_column('users', 'is_admin')
