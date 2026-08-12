"""make divar_conversation_id globally unique

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # services/chatbot.py._lookup_conversation is the chatbot's entry point and
    # keys on divar_conversation_id alone — it cannot filter by client_id, since
    # resolving client_id is its whole job. Without global uniqueness, two rows
    # sharing a divar_conversation_id across clients would make its
    # scalar_one_or_none() raise MultipleResultsFound.
    #
    # 0001's composite (client_id, divar_conversation_id) is deliberately KEPT:
    # it is the named ON CONFLICT target that turns a redelivered webhook into a
    # silent DO NOTHING no-op. This constraint is the one that raises instead,
    # when a *different* client claims a conversation that is already owned.
    #
    # No backfill/dedup: if live data already violates this, the migration fails
    # loudly and correctly — picking a winner between two tenants' rows is not a
    # decision a migration should make silently.
    op.create_unique_constraint(
        "uq_conversations_divar_conversation_id",
        "conversations",
        ["divar_conversation_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_conversations_divar_conversation_id",
        "conversations",
        type_="unique",
    )
