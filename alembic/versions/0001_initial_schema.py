"""squashed initial schema (migrations 0001-0005 + step 20 listing columns)

Revision ID: 0001
Revises:
Create Date: 2026-08-29

This single baseline REPLACES the former five-migration chain:
  0001_initial_schema
  0002_shrink_post_token                (post_token varchar(255) -> varchar(20);
                                         added posts.is_available)
  0003_make_conversation_state_required (conversations.current_state NOT NULL,
                                         server_default 'START')
  0004_globally_unique_divar_conversation_id
  0005_add_post_conversation_memory     (post_conversations / post_messages
                                         and their enums)
It also folds in the listing columns on posts from steps 20-21:
the Divar-sourced metadata (title, category, chat_enabled, is_phone_hidden,
last_synced_at — all nullable, written only by services/divar_listings.py),
`present_on_divar` (sync-owned listing existence on Divar), and
`is_available` (seller-owned chatbot toggle, §3.8.4 — never written by sync).

The history was collapsed because NO migration in the old chain has ever run
against a real production database: the project is pre-production and the
database is wiped and recreated on every redeploy, so there are no
alembic_version rows in the wild pointing at the old revision ids.
DO NOT squash this file's history again: once a real production deployment
exists, squashing strands every deployed alembic_version row and requires
manual stamping. From that point on, only additive migrations on top of this
baseline.

Verification note (2026-08-29): this baseline was verified structurally —
an `alembic upgrade head` / `alembic downgrade base` round-trip against a
throwaway SQLite database, plus a manual column/constraint/index/enum diff
against the five deleted migrations' cumulative result and the model files.
It was NOT verified against a live Postgres instance; the first
`alembic upgrade head` run on Railway's Postgres after this change ships is
the real verification moment.
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
    # --- enums (explicit create, as in the old 0001/0005; no-op on
    # non-Postgres dialects so the SQLite round-trip verification works) ---
    sender_type_enum = postgresql.ENUM(
        "user", "bot", "human_agent", name="sender_type_enum", create_type=False
    )
    sender_type_enum.create(op.get_bind(), checkfirst=True)

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

    # JSONB is Postgres-only; the sa.JSON variant exists solely so the SQLite
    # round-trip verification can execute this migration end to end. On
    # Postgres the column is exactly the JSONB the old chain produced.
    jsonb = postgresql.JSONB(astext_type=sa.Text()).with_variant(
        sa.JSON(), "sqlite"
    )

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
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default="0"
        ),
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

    # --- posts (0001 + 0002's shrink/is_available + steps 20-21's listing
    # columns; the Divar-sourced columns are nullable because a post can be
    # registered before its first listing sync; present_on_divar/is_available
    # are the two single-owner flags — sync presence vs. seller toggle) ---
    op.create_table(
        "posts",
        sa.Column("post_token", sa.String(length=20), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column(
            "is_available",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "present_on_divar",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("chat_enabled", sa.Boolean(), nullable=True),
        sa.Column("is_phone_hidden", sa.Boolean(), nullable=True),
        sa.Column(
            "last_synced_at", sa.DateTime(timezone=True), nullable=True
        ),
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
        sa.Column(
            "current_state",
            sa.String(length=50),
            nullable=False,
            server_default="START",
        ),
        sa.Column("metadata", jsonb, nullable=True),
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
        # Kept DISTINCT from the composite above (old 0004's reasoning):
        # the composite (client_id, divar_conversation_id) is the named
        # ON CONFLICT target that turns a redelivered webhook into a silent
        # DO NOTHING no-op; this global one is what RAISES when a different
        # client claims a conversation another tenant already owns. Without
        # global uniqueness, _lookup_conversation — which keys on
        # divar_conversation_id alone because resolving client_id is its
        # whole job — cannot safely use scalar_one_or_none().
        sa.UniqueConstraint(
            "divar_conversation_id",
            name="uq_conversations_divar_conversation_id",
        ),
    )
    op.create_index(
        op.f("ix_conversations_client_id"), "conversations", ["client_id"]
    )

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
        sa.Column("payload", jsonb, nullable=True),
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

    # --- post_conversations (old 0005) ---
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

    # --- post_messages (old 0005) ---
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
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("products")
    op.drop_table("posts")
    op.drop_table("refresh_tokens")
    op.drop_table("otp_codes")
    op.drop_table("oauth_tokens")
    op.drop_table("clients")
    postgresql.ENUM(
        name="post_sender_type_enum"
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        name="post_conversation_state_enum"
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="sender_type_enum").drop(op.get_bind(), checkfirst=True)
