"""add users table

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Deliberately NOT adding a foreign key from meetings.user_id -> users.id
    # here. Every meeting created before today has a user_id that's an
    # arbitrary string from the X-User-Id header (e.g. "demo-user"), not a
    # real users.id -- an FK constraint would fail immediately on existing
    # data. A real production migration would backfill/reconcile that data
    # first; documenting the gap here rather than silently working around it.


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")