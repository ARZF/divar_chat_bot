import os

# Set required settings before importing application modules.
os.environ.setdefault("DIVAR_API_KEY", "test_api_key")
os.environ.setdefault("DIVAR_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("DIVAR_REFRESH_TOKEN", "test_refresh_token")
os.environ.setdefault("DIVAR_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("DIVAR_IDENTIFICATION_KEY", "test_identification_key")
os.environ.setdefault("DIVAR_APP_SLUG", "test_app_slug")
os.environ.setdefault("DIVAR_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("DIVAR_REDIRECT_URI", "https://example.com/callback")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key")
os.environ.setdefault("OTP_HMAC_KEY", "test_otp_hmac_key")

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from models.client import Client
from models.conversation import Conversation
from models.post import Post
import services.chatbot as chatbot


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    """Allow the production PostgreSQL JSONB model to be tested on SQLite."""
    return "JSON"


class _SQLiteInsertAdapter:
    """Adapt chatbot.py's PostgreSQL upsert to SQLite for unit tests."""

    def __init__(self, model):
        self.statement = sqlite_insert(model)

    def values(self, **values):
        self.statement = self.statement.values(**values)
        return self

    def on_conflict_do_nothing(self, *, constraint=None):
        return self.statement.on_conflict_do_nothing(
            index_elements=[
                Conversation.client_id,
                Conversation.divar_conversation_id,
            ]
        )


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [Client.__table__, Post.__table__, Conversation.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Client.metadata.create_all(
                sync_connection, tables=tables
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def db(session_factory):
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_post(db):
    """A real seller and registered post used by /start resolution tests."""
    client = Client(phone_number="09120000001")
    db.add(client)
    await db.flush()
    post = Post(post_token="TEST_POST_TOKEN", client_id=client.id)
    db.add(post)
    await db.commit()
    return client, post


@pytest.fixture
def sqlite_upsert(monkeypatch):
    monkeypatch.setattr(
        chatbot,
        "pg_insert",
        lambda model: _SQLiteInsertAdapter(model),
    )


@pytest.mark.asyncio
async def test_parse_start_message_supports_all_touchpoints():
    assert chatbot.parse_start_message("/start MY_POST token-1") == (
        "MY_POST",
        "token-1",
    )
    assert chatbot.parse_start_message("/start MY_DIVAR") == ("MY_DIVAR", None)
    assert chatbot.parse_start_message("/start DIVAR_PRO") == ("DIVAR_PRO", None)
    assert chatbot.parse_start_message("/start CHAT conversation-1") == (
        "CHAT",
        "conversation-1",
    )
    assert chatbot.parse_start_message("/start DEMAND_POST token-2") == (
        "DEMAND_POST",
        "token-2",
    )
    assert chatbot.parse_start_message("price iphone") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("touchpoint", ["MY_POST", "DEMAND_POST"])
async def test_start_post_touchpoints_resolve_to_seeded_client(
    db, seeded_post, sqlite_upsert, touchpoint
):
    client, post = seeded_post

    resolved_client_id = await chatbot._resolve_new_conversation(
        db,
        "conversation-resolved",
        f"/start {touchpoint} {post.post_token}",
    )

    assert resolved_client_id == client.id
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.divar_conversation_id == "conversation-resolved"
            )
        )
    ).scalar_one()
    assert conversation.client_id == client.id


@pytest.mark.asyncio
async def test_unresolved_start_does_not_persist_conversation(db, seeded_post):
    resolved_client_id = await chatbot._resolve_new_conversation(
        db,
        "conversation-unresolved",
        "/start MY_POST unknown-token",
    )

    assert resolved_client_id is None
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.divar_conversation_id == "conversation-unresolved"
            )
        )
    ).scalar_one_or_none()
    assert conversation is None


@pytest.mark.asyncio
async def test_bare_touchpoint_does_not_persist_conversation(db, seeded_post):
    resolved_client_id = await chatbot._resolve_new_conversation(
        db,
        "conversation-bare-touchpoint",
        "/start MY_DIVAR",
    )

    assert resolved_client_id is None
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.divar_conversation_id == "conversation-bare-touchpoint"
            )
        )
    ).scalar_one_or_none()
    assert conversation is None


@pytest.mark.asyncio
async def test_non_start_message_has_no_client_fallback(db, seeded_post):
    resolved_client_id = await chatbot._resolve_new_conversation(
        db,
        "conversation-without-start",
        "قیمت آیفون چنده؟",
    )

    assert resolved_client_id is None
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.divar_conversation_id == "conversation-without-start"
            )
        )
    ).scalar_one_or_none()
    assert conversation is None


@pytest.mark.asyncio
async def test_subsequent_message_uses_existing_conversation(db, seeded_post):
    client, _ = seeded_post
    conversation = Conversation(
        client_id=client.id,
        divar_conversation_id="conversation-existing",
        current_state="START",
    )
    db.add(conversation)
    await db.commit()

    loaded = await chatbot._lookup_conversation(db, "conversation-existing")

    assert loaded is not None
    assert loaded.client_id == client.id