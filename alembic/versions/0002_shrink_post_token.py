"""shrink post_token from varchar(255) to varchar(20)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "posts",
        "post_token",
        existing_type=sa.String(length=255),
        type_=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "posts",
        "post_token",
        existing_type=sa.String(length=20),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
