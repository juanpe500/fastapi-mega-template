"""add users.purged_at for GDPR anonymisation tombstone

Revision ID: e2a7c9d4b810
Revises: c79ca0af23ec
Create Date: 2026-07-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2a7c9d4b810'
down_revision: Union[str, None] = 'c79ca0af23ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_purged_at'), ['purged_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_purged_at'))
        batch_op.drop_column('purged_at')
