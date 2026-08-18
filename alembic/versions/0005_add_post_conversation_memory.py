"""add isolated post conversation memory

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    post_conversation_state_enum = postgresql.ENUM(
        "NEW",
        "ACTIVE",
        name="post_conversation_state_enum",
        create_type=False,
    )
    post_conversation_state_enum.create(op.get_bind(), checkfirst=True)

    post_sender_type_enum = postgresql.ENUM(
        "buyer",
        "bot",
        name="post_sender_type_enum",
        create_type=False,
    )
    post_sender_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "post_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column(
            "divar_conversation_id", sa.String(length=255), nullable=False
        ),
        sa.Column("post_token", sa.String(length=255), nullable=False),
        sa.Column(
            "current_state",
            post_conversation_state_enum,
            nullable=False,
            server_default="NEW",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "divar_conversation_id",
            name="uq_post_conversations_divar_conversation_id",
        ),
    )
    op.create_index(
        op.f("ix_post_conversations_client_id"),
        "post_conversations",
        ["client_id"],
    )

    op.create_table(
        "post_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_conversation_id", sa.Integer(), nullable=False),
        sa.Column("divar_message_id", sa.String(length=255), nullable=True),
        sa.Column(
            "sender_type",
            post_sender_type_enum,
            nullable=False,
        ),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["post_conversation_id"],
            ["post_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "divar_message_id",
            name="uq_post_messages_divar_message_id",
        ),
    )
    op.create_index(
        op.f("ix_post_messages_post_conversation_id"),
        "post_messages",
        ["post_conversation_id"],
    )


def downgrade() -> None:
    op.drop_table("post_messages")
    op.drop_table("post_conversations")
    postgresql.ENUM(
        name="post_sender_type_enum"
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        name="post_conversation_state_enum"
    ).drop(op.get_bind(), checkfirst=True)
