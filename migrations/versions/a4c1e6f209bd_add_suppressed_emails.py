"""add suppressed_emails (bounce/complaint suppression list)

Revision ID: a4c1e6f209bd
Revises: f3b8d1c05a94
Create Date: 2026-07-23 00:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4c1e6f209bd'
down_revision: Union[str, None] = 'f3b8d1c05a94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'suppressed_emails',
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('reason', sa.String(length=20), nullable=False),
        sa.Column('detail', sa.String(length=500), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('suppressed_emails', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_suppressed_emails_email'), ['email'], unique=True)
        batch_op.create_index(batch_op.f('ix_suppressed_emails_reason'), ['reason'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('suppressed_emails', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_suppressed_emails_reason'))
        batch_op.drop_index(batch_op.f('ix_suppressed_emails_email'))
    op.drop_table('suppressed_emails')
