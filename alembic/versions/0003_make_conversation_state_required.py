"""make conversation state required

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-09 14:10:33.934061

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 0001 created this column nullable; adding a server_default does not
    # backfill existing rows, so SET NOT NULL would fail on any NULL left over.
    op.execute(
        "UPDATE conversations SET current_state = 'START' WHERE current_state IS NULL"
    )
    op.alter_column(
        "conversations",
        "current_state",
        existing_type=sa.String(length=50),
        existing_nullable=True,
        nullable=False,
        server_default="START",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "conversations",
        "current_state",
        existing_type=sa.String(length=50),
        existing_nullable=False,
        nullable=True,
        server_default=None,
    )