"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- clients ---
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column("divar_user_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_number"),
        sa.UniqueConstraint("divar_user_id"),
        sa.CheckConstraint(
            "phone_number IS NOT NULL OR divar_user_id IS NOT NULL",
            name="ck_clients_has_identifier",
        ),
    )
    op.create_index(op.f("ix_clients_phone_number"), "clients", ["phone_number"])
    op.create_index(op.f("ix_clients_divar_user_id"), "clients", ["divar_user_id"])

    # --- oauth_tokens ---
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("divar_access_token", sa.Text(), nullable=False),
        sa.Column("divar_refresh_token", sa.Text(), nullable=False),
        sa.Column(
            "token_expires_at", sa.DateTime(timezone=True), nullable=False
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
        sa.UniqueConstraint("client_id"),
    )
    op.create_index(
        op.f("ix_oauth_tokens_client_id"), "oauth_tokens", ["client_id"]
    )

    # --- otp_codes ---
    op.create_table(
        "otp_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_otp_codes_phone_number"), "otp_codes", ["phone_number"]
    )

    # --- refresh_tokens ---
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_refresh_tokens_client_id"), "refresh_tokens", ["client_id"]
    )

    # --- posts ---
    op.create_table(
        "posts",
        sa.Column("post_token", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("post_token"),
    )
    op.create_index(op.f("ix_posts_client_id"), "posts", ["client_id"])

    # --- products ---
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("item_name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
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
            "client_id", "normalized_name", name="uq_products_client_normalized"
        ),
    )
    op.create_index(
        op.f("ix_products_client_id"), "products", ["client_id"]
    )

    # --- conversations ---
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column(
            "divar_conversation_id", sa.String(length=255), nullable=False
        ),
        sa.Column("current_state", sa.String(length=50), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            "client_id",
            "divar_conversation_id",
            name="uq_conversations_client_divar",
        ),
    )
    op.create_index(
        op.f("ix_conversations_client_id"), "conversations", ["client_id"]
    )

    # --- sender_type_enum ---
    sender_type_enum = postgresql.ENUM(
        "user", "bot", "human_agent", name="sender_type_enum", create_type=False
    )
    sender_type_enum.create(op.get_bind(), checkfirst=True)

    # --- messages ---
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column(
            "divar_message_id", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "sender_type",
            sender_type_enum,
            nullable=False,
        ),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("divar_message_id"),
    )
    op.create_index(
        op.f("ix_messages_conversation_id"), "messages", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("messages")
    postgresql.ENUM(name="sender_type_enum").drop(op.get_bind(), checkfirst=True)
    op.drop_table("conversations")
    op.drop_table("products")
    op.drop_table("posts")
    op.drop_table("refresh_tokens")
    op.drop_table("otp_codes")
    op.drop_table("oauth_tokens")
    op.drop_table("clients")
