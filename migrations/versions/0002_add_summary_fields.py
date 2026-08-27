"""add key_decisions and action_items columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("key_decisions", postgresql.JSONB(), nullable=True))
    op.add_column("meetings", sa.Column("action_items", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "action_items")
    op.drop_column("meetings", "key_decisions")