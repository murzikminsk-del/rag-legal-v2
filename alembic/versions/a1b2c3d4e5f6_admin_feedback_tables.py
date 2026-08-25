"""admin and feedback tables

Revision ID: a1b2c3d4e5f6
Revises: dc590fe16b30
Create Date: 2026-08-25 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'dc590fe16b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chats', sa.Column('updated_at', sa.DateTime(), nullable=True))

    op.create_table(
        'broadcast_queue',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('interface', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    op.create_table(
        'message_feedback',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('message_id', sa.Uuid(), nullable=False),
        sa.Column('owner_external_id', sa.Text(), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint('owner_external_id', 'message_id',
                            name='uq_feedback_owner_message'),
    )


def downgrade() -> None:
    op.drop_table('message_feedback')
    op.drop_table('broadcast_queue')
    op.drop_column('chats', 'updated_at')