"""Model-level regression tests.

SQLite's dynamic typing silently accepts any string into an Enum column, so
a name-vs-value serialization bug in a Python enum column never fails on the
test database — it only explodes on real Postgres with an invalid-enum-value
error. messages.payload/conversations.metadata are JSONB, so the tables
cannot even be created on SQLite; these tests therefore pin the wire format
at the bind-processor seam (exactly what an INSERT would send), not via a
table round-trip.
"""

from sqlalchemy.dialects import sqlite

from models.message import Message, SenderType


def test_sender_type_persists_values_not_names():
    """Regression: SenderType must serialize to 'user'/'bot'/'human_agent'
    (the values the sender_type_enum Postgres type accepts), not the member
    NAMES ('USER'/...), which would fail every INSERT on real Postgres.

    Mirrors the values_callable pattern already used by PostSenderType
    (models/post_message.py) and PostConversationState
    (models/post_conversation.py).
    """
    sender_type = Message.__table__.c.sender_type

    # The Enum's value list is what CREATE TYPE / validation use.
    assert sender_type.type.enums == [m.value for m in SenderType]

    # The bind processor is what an INSERT actually sends to the database.
    process = sender_type.type.bind_processor(sqlite.dialect())
    for member in SenderType:
        assert process(member) == member.value
