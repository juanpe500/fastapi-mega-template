"""add error_logs.request_id correlation id

Revision ID: f3b8d1c05a94
Revises: e2a7c9d4b810
Create Date: 2026-07-23 00:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3b8d1c05a94'
down_revision: Union[str, None] = 'e2a7c9d4b810'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('error_logs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('request_id', sa.String(length=64), nullable=False,
                      server_default='')
        )
        batch_op.create_index(batch_op.f('ix_error_logs_request_id'),
                              ['request_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('error_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_error_logs_request_id'))
        batch_op.drop_column('request_id')
