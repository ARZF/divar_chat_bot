# Env vars for config.py are set by the root conftest.py before collection.
import inspect
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from config import settings
from logging_config import client_id_var, conversation_id_var
from models.client import Client
from models.conversation import Conversation
from models.oauth_token import OAuthToken
from models.post import Post
from models.post_conversation import PostConversation
from models.post_message import PostMessage, PostSenderType
from models.enums import PostConversationState
from models.product import Product
import services.chatbot as chatbot
import services.chatbot_conversation as chatbot_conversation
import services.oauth_refresh as oauth_refresh
import services.post_conversation as post_conversation
import services.price_lookup as pl
from services.price_lookup import normalize_text
from services.state_machine import INTENT_EVENTS, ConversationState, transition

# Test client_id used by the price-cache fixture (mirrors tests/test_price_lookup.py)
CID = 1


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    """Allow the production PostgreSQL JSONB model to be tested on SQLite."""
    return "JSON"


class _SQLiteInsertAdapter:
    """Adapt chatbot.py's PostgreSQL upsert to SQLite for unit tests."""

    def __init__(self, model):
        self.model = model
        self.statement = sqlite_insert(model)

    def values(self, **values):
        self.statement = self.statement.values(**values)
        return self

    def on_conflict_do_nothing(self, *, constraint=None):
        if self.model is Conversation:
            index_elements = [
                Conversation.client_id,
                Conversation.divar_conversation_id,
            ]
        elif self.model is PostConversation:
            index_elements = [PostConversation.divar_conversation_id]
        else:
            index_elements = [PostMessage.divar_message_id]
        return self.statement.on_conflict_do_nothing(index_elements=index_elements)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Client.__table__,
        Post.__table__,
        Conversation.__table__,
        PostConversation.__table__,
        PostMessage.__table__,
        OAuthToken.__table__,
        Product.__table__,
    ]
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


def _patch_session_local(monkeypatch, factory):
    """Point every module that opens its own session at *factory*.

    All three import AsyncSessionLocal independently, so all three need
    patching — an unpatched one would open a real production session.
    """
    for module in (chatbot_conversation, post_conversation, oauth_refresh):
        monkeypatch.setattr(module, "AsyncSessionLocal", factory)


@pytest.fixture
def sqlite_upsert(monkeypatch):
    # Both orchestration modules import pg_insert independently, so both need
    # patching — this is not redundant, do not collapse it to one call.
    for module in (chatbot_conversation, post_conversation):
        monkeypatch.setattr(
            module,
            "pg_insert",
            lambda model: _SQLiteInsertAdapter(model),
        )


@pytest.fixture
def catalog():
    """Seed the per-client price cache, then always tear it down.

    CID is shared with tests/test_price_lookup.py, so the pop is mandatory —
    a leaked entry would silently change that module's expectations.
    """
    pl._cache[CID] = pl.ClientPriceCache(
        prices={"iphone 13": 35000000, "iphone 14": 42000000},
        canonical_names={"iphone 13": "iPhone 13", "iphone 14": "iPhone 14"},
        product_names=["iphone 13", "iphone 14"],
    )
    yield
    pl._cache.pop(CID, None)


class TestParseStartMessage:
    def test_my_post_with_token(self):
        assert chatbot.parse_start_message("/start MY_POST tok123") == (
            "MY_POST",
            "tok123",
        )

    def test_demand_post_with_token(self):
        assert chatbot.parse_start_message("/start DEMAND_POST tok456") == (
            "DEMAND_POST",
            "tok456",
        )

    def test_chat_with_token(self):
        assert chatbot.parse_start_message("/start CHAT convid") == ("CHAT", "convid")

    def test_bare_my_divar_has_no_token(self):
        assert chatbot.parse_start_message("/start MY_DIVAR") == ("MY_DIVAR", None)

    def test_bare_divar_pro_has_no_token(self):
        assert chatbot.parse_start_message("/start DIVAR_PRO") == ("DIVAR_PRO", None)

    def test_unknown_touchpoint_returns_none(self):
        assert chatbot.parse_start_message("/start BOGUS x") is None

    def test_non_start_text_returns_none(self):
        assert chatbot.parse_start_message("hello") is None
        assert chatbot.parse_start_message("price iphone") is None

    def test_empty_string_returns_none(self):
        assert chatbot.parse_start_message("") is None

    def test_surrounding_whitespace_is_stripped(self):
        assert chatbot.parse_start_message("  /start MY_DIVAR  ") == ("MY_DIVAR", None)


@pytest.mark.asyncio
@pytest.mark.parametrize("touchpoint", ["MY_POST", "DEMAND_POST"])
async def test_start_post_touchpoints_resolve_to_seeded_client(
    db, seeded_post, sqlite_upsert, touchpoint
):
    client, post = seeded_post

    resolved = await chatbot._resolve_new_conversation(
        db,
        "conversation-resolved",
        f"/start {touchpoint} {post.post_token}",
    )

    assert resolved is not None
    conv, is_new = resolved
    assert is_new is True
    assert conv.client_id == client.id
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


@pytest.mark.asyncio
async def test_persisted_state_parses_back_into_the_enum(
    db, seeded_post, sqlite_upsert
):
    """Whatever gets written must round-trip through ConversationState.

    Guards the casing mismatch: a lowercase enum against an uppercase stored
    literal raises ValueError here, before any state-machine wiring exists.
    """
    _, post = seeded_post

    await chatbot._resolve_new_conversation(
        db,
        "conversation-state-roundtrip",
        f"/start MY_POST {post.post_token}",
    )

    loaded = await chatbot._lookup_conversation(db, "conversation-state-roundtrip")

    assert ConversationState(loaded.current_state) is ConversationState.START


@pytest.mark.asyncio
async def test_redelivered_upsert_reports_not_new(db, seeded_post, sqlite_upsert):
    """`is_new` must come from the upsert's rowcount, not from the entry lookup.

    Second call stands in for a redelivered webhook that reached the INSERT after
    another delivery already won it: same row back, but `is_new` False.
    """
    client, post = seeded_post
    start = f"/start MY_POST {post.post_token}"

    first = await chatbot._resolve_new_conversation(db, "conv-redelivered", start)
    second = await chatbot._resolve_new_conversation(db, "conv-redelivered", start)

    assert first[1] is True
    assert second[1] is False
    assert second[0].client_id == client.id


# ---------------------------------------------------------------------------
# Intent router helpers — all receive text already run through normalize_text,
# so the tests normalize first to mirror handle_bot_reply's real call path.
# ---------------------------------------------------------------------------
class TestMatchIntent:
    def test_persian_price_keyword(self):
        assert chatbot._match_intent(normalize_text("قیمت آیفون")) == "PRICE"

    def test_english_price_keyword(self):
        assert chatbot._match_intent(normalize_text("price iphone")) == "PRICE"

    def test_warranty_keyword(self):
        assert chatbot._match_intent(normalize_text("گارانتی")) == "WARRANTY"

    def test_support_keyword(self):
        assert chatbot._match_intent(normalize_text("پشتیبانی")) == "SUPPORT"

    def test_greeting_has_no_intent(self):
        assert chatbot._match_intent(normalize_text("سلام")) is None

    def test_empty_text_has_no_intent(self):
        assert chatbot._match_intent("") is None


class TestIsPureGreeting:
    def test_persian_greeting(self):
        assert chatbot._is_pure_greeting(normalize_text("سلام")) is True

    def test_english_greeting(self):
        assert chatbot._is_pure_greeting(normalize_text("hi")) is True

    def test_greeting_plus_intent_is_not_pure(self):
        assert chatbot._is_pure_greeting(normalize_text("سلام قیمت")) is False

    def test_empty_text_is_not_a_greeting(self):
        assert chatbot._is_pure_greeting("") is False


class TestExtractProductName:
    def test_price_keyword_is_stripped(self):
        result = chatbot._extract_product_name(normalize_text("قیمت آیفون ۱۳"))
        assert "قیمت" not in result
        # normalize_text transliterates آیفون -> iphone and ۱۳ -> 13
        assert result.split() == ["iphone", "13"]

    def test_keyword_only_leaves_nothing(self):
        assert chatbot._extract_product_name(normalize_text("قیمت")) == ""

    def test_filtered_filler_words_are_stripped(self):
        result = chatbot._extract_product_name(normalize_text("سلام قیمت iphone چنده"))
        assert result.split() == ["iphone"]


# ---------------------------------------------------------------------------
# _handle_price_intent — signature is (db, client_id, normalized_text)
# ---------------------------------------------------------------------------
class TestHandlePriceIntent:
    @pytest.mark.asyncio
    async def test_no_product_name_returns_prompt(self, db, catalog):
        reply = await chatbot._handle_price_intent(db, CID, normalize_text("قیمت"))
        assert reply == settings.PRICE_PROMPT_MESSAGE

    @pytest.mark.asyncio
    async def test_single_substring_match_reports_canonical_name_and_price(
        self, db, catalog
    ):
        reply = await chatbot._handle_price_intent(
            db, CID, normalize_text("قیمت iphone 13")
        )
        assert "iPhone 13" in reply
        assert "35,000,000" in reply

    @pytest.mark.asyncio
    async def test_multiple_substring_matches_return_bulk_list(self, db, catalog):
        reply = await chatbot._handle_price_intent(
            db, CID, normalize_text("قیمت iphone")
        )
        assert "iPhone 13" in reply
        assert "iPhone 14" in reply
        assert "42,000,000" in reply

    @pytest.mark.asyncio
    async def test_unknown_product_returns_not_found(self, db, catalog):
        # "zzzzzzzzz" scores far below SUGGESTION_MIN_SCORE against the catalog,
        # so the substring, fuzzy and suggestion tiers all miss deterministically.
        reply = await chatbot._handle_price_intent(
            db, CID, normalize_text("قیمت zzzzzzzzz")
        )
        assert reply == settings.PRICE_NOT_FOUND_MESSAGE


# ---------------------------------------------------------------------------
# Background-task session lifetime (PHASE2 §2.5)
#
# handle_bot_reply runs as a FastAPI BackgroundTask, so the request's
# Depends(get_db) session may already be closed by the time it runs. It must
# therefore take no session parameter and open its own via AsyncSessionLocal.
# ---------------------------------------------------------------------------
class _TrackedSessionContext:
    """Delegates to a real session context manager, recording enter/exit.

    Lets the test assert `async with` was used (not a bare call or a manually
    managed session) while handle_bot_reply still gets a working session.
    """

    def __init__(self, factory):
        self._context = factory()
        self.aenter_calls = 0
        self.aexit_calls = 0

    async def __aenter__(self):
        self.aenter_calls += 1
        return await self._context.__aenter__()

    async def __aexit__(self, *exc_info):
        self.aexit_calls += 1
        return await self._context.__aexit__(*exc_info)


class _RollbackSpySessionContext:
    """Like _TrackedSessionContext, but counts rollback() on the yielded session.

    Needed because handle_post_bot_reply's failure branches must roll back the buyer
    message insert — an assertion on the absence of rows alone cannot distinguish a
    rollback from a session that simply was never committed.
    """

    def __init__(self, factory):
        self._context = factory()
        self.rollback_calls = 0

    async def __aenter__(self):
        session = await self._context.__aenter__()
        real_rollback = session.rollback

        async def counting_rollback():
            self.rollback_calls += 1
            return await real_rollback()

        session.rollback = counting_rollback
        return session

    async def __aexit__(self, *exc_info):
        return await self._context.__aexit__(*exc_info)


def test_handle_bot_reply_takes_no_session_parameter():
    """Guard: the Phase 1 signature must stay (conversation_id, user_text).

    Fails loudly if a request-scoped `db`/`session` param is ever added — that
    session is not guaranteed open when the background task runs.
    """
    parameters = list(inspect.signature(chatbot.handle_bot_reply).parameters)
    assert parameters == ["conversation_id", "user_text"]


@pytest.mark.asyncio
async def test_handle_bot_reply_opens_its_own_session(
    monkeypatch, session_factory, seeded_post, sqlite_upsert, catalog
):
    """handle_bot_reply must open its own session via `async with`.

    Driven through the real /start resolution path. `catalog` is required for
    its teardown: the seeded client is client_id 1 (== CID) in a fresh
    in-memory DB, and a pre-seeded cache entry both skips the lazy warm and
    guarantees the entry is popped afterwards.
    """
    client, post = seeded_post

    # handle_bot_reply's module does `from db.session import AsyncSessionLocal`,
    # so the name must be patched on that module, not on db.session.
    tracked_context = _TrackedSessionContext(session_factory)
    mock_session_local = MagicMock(return_value=tracked_context)
    _patch_session_local(monkeypatch, mock_session_local)

    send_message = AsyncMock(return_value=True)
    monkeypatch.setattr(chatbot.divar_service, "send_message", send_message)

    await chatbot.handle_bot_reply(
        "conversation-lifetime-test", f"/start MY_POST {post.post_token}"
    )

    # Opened its own session, with no arguments, exactly once...
    mock_session_local.assert_called_once_with()
    # ...and as an async context manager, so it is always closed.
    assert tracked_context.aenter_calls == 1
    assert tracked_context.aexit_calls == 1

    # The session was real and usable: resolution actually persisted a row.
    async with session_factory() as verify_session:
        conversation = (
            await verify_session.execute(
                select(Conversation).where(
                    Conversation.divar_conversation_id == "conversation-lifetime-test"
                )
            )
        ).scalar_one()
    assert conversation.client_id == client.id

    # No real HTTP call happened; the welcome reply went out on the new conversation.
    sent_texts = [call.args[1] for call in send_message.await_args_list]
    assert settings.WELCOME_MESSAGE in sent_texts


@pytest.mark.asyncio
async def test_handle_post_bot_reply_persists_buyer_and_bot_messages(
    monkeypatch, session_factory, seeded_post, sqlite_upsert
):
    client, post = seeded_post
    async with session_factory() as db:
        db.add(
            OAuthToken(
                client_id=client.id,
                divar_access_token="access-token",
                divar_refresh_token="refresh-token",
                token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        await db.commit()

    _patch_session_local(monkeypatch, lambda: session_factory())
    send = AsyncMock()
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", send)

    await chatbot.handle_post_bot_reply(
        "supplier-conversation", post.post_token, "hello", "divar-message-1"
    )

    send.assert_awaited_once_with(
        "supplier-conversation", settings.GREETING_REPLY_MESSAGE, "access-token"
    )
    async with session_factory() as db:
        conversation = (
            await db.execute(
                select(PostConversation).where(
                    PostConversation.divar_conversation_id == "supplier-conversation"
                )
            )
        ).scalar_one()
        messages = (
            await db.execute(
                select(PostMessage)
                .where(PostMessage.post_conversation_id == conversation.id)
                .order_by(PostMessage.id)
            )
        ).scalars().all()
    assert conversation.client_id == client.id
    assert conversation.current_state is PostConversationState.ACTIVE
    assert [(m.sender_type, m.text_content) for m in messages] == [
        (PostSenderType.BUYER, "hello"),
        (PostSenderType.BOT, settings.GREETING_REPLY_MESSAGE),
    ]


@pytest.mark.asyncio
async def test_handle_post_bot_reply_price_uses_generated_reply(
    monkeypatch, session_factory, seeded_post, sqlite_upsert, catalog
):
    client, post = seeded_post
    async with session_factory() as db:
        db.add(OAuthToken(
            client_id=client.id,
            divar_access_token="access-token",
            divar_refresh_token="refresh-token",
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await db.commit()
    _patch_session_local(monkeypatch, lambda: session_factory())
    send = AsyncMock()
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", send)

    await chatbot.handle_post_bot_reply(
        "price-conversation", post.post_token, "قیمت آیفون ۱۳", "price-message"
    )

    send.assert_awaited_once_with(
        "price-conversation", "قیمت iPhone 13: 35,000,000 تومان", "access-token"
    )


@pytest.mark.asyncio
async def test_handle_post_bot_reply_none_reply_persists_buyer_and_stays_new(
    monkeypatch, session_factory, seeded_post, sqlite_upsert
):
    _patch_session_local(monkeypatch, lambda: session_factory())
    monkeypatch.setattr(post_conversation, "generate_chatbot_reply", AsyncMock(return_value=None))
    send = AsyncMock()
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", send)

    await chatbot.handle_post_bot_reply(
        "none-conversation", seeded_post[1].post_token, "hello", "none-message"
    )

    send.assert_not_awaited()
    async with session_factory() as db:
        conversation = (
            await db.execute(
                select(PostConversation).where(
                    PostConversation.divar_conversation_id == "none-conversation"
                )
            )
        ).scalar_one()
        messages = (await db.execute(select(PostMessage))).scalars().all()
    assert conversation.current_state is PostConversationState.NEW
    assert len(messages) == 1
    assert messages[0].sender_type is PostSenderType.BUYER



@pytest.mark.asyncio
async def test_handle_post_bot_reply_deduplicates_redelivery(
    monkeypatch, session_factory, seeded_post, sqlite_upsert
):
    client, post = seeded_post
    async with session_factory() as db:
        db.add(OAuthToken(
            client_id=client.id,
            divar_access_token="access-token",
            divar_refresh_token="refresh-token",
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await db.commit()
    _patch_session_local(monkeypatch, lambda: session_factory())
    send = AsyncMock()
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", send)

    for _ in range(2):
        await chatbot.handle_post_bot_reply(
            "supplier-conversation", post.post_token, "hello", "same-message"
        )

    send.assert_awaited_once()
    async with session_factory() as db:
        assert len((await db.execute(select(PostMessage))).scalars().all()) == 2


@pytest.mark.asyncio
async def test_handle_post_bot_reply_loads_history_and_isolates_conversations(
    monkeypatch, session_factory, seeded_post, sqlite_upsert
):
    client, post = seeded_post
    async with session_factory() as db:
        db.add(OAuthToken(
            client_id=client.id,
            divar_access_token="access-token",
            divar_refresh_token="refresh-token",
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await db.commit()
    _patch_session_local(monkeypatch, lambda: session_factory())
    generate = AsyncMock(return_value="generated reply")
    monkeypatch.setattr(post_conversation, "generate_chatbot_reply", generate)
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", AsyncMock())

    await chatbot.handle_post_bot_reply("conversation-a", post.post_token, "first", "m1")
    await chatbot.handle_post_bot_reply("conversation-a", post.post_token, "second", "m2")

    assert generate.await_count == 2
    assert generate.await_args_list[0].kwargs["message_history"] == [("buyer", "first")]
    assert generate.await_args_list[1].kwargs["message_history"] == [
        ("buyer", "first"),
        ("bot", "generated reply"),
        ("buyer", "second"),
    ]


@pytest.mark.asyncio
async def test_handle_post_bot_reply_unknown_post_does_not_send(
    monkeypatch, session_factory, sqlite_upsert, caplog
):
    _patch_session_local(monkeypatch, lambda: session_factory())
    send = AsyncMock()
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", send)
    with caplog.at_level(logging.WARNING, logger="chatbot"):
        await chatbot.handle_post_bot_reply("unknown-conversation", "unknown-post", "hello", "m1")
    send.assert_not_awaited()
    assert any(record.message == "NEW_MESSAGE post_token did not resolve to a client" for record in caplog.records)


@pytest.mark.asyncio
async def test_handle_post_bot_reply_missing_oauth_token_does_not_send(
    monkeypatch, session_factory, seeded_post, sqlite_upsert
):
    _patch_session_local(monkeypatch, lambda: session_factory())
    send = AsyncMock()
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", send)
    await chatbot.handle_post_bot_reply(
        "supplier-conversation", seeded_post[1].post_token, "hello", "m1"
    )
    send.assert_not_awaited()
    async with session_factory() as db:
        assert not (await db.execute(select(PostMessage))).scalars().all()


@pytest.mark.asyncio
async def test_handle_post_bot_reply_refreshes_token_and_reregisters(
    monkeypatch, session_factory, seeded_post, sqlite_upsert
):
    client, post = seeded_post
    async with session_factory() as db:
        db.add(OAuthToken(
            client_id=client.id,
            divar_access_token="old-access",
            divar_refresh_token="old-refresh",
            token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ))
        await db.commit()
    _patch_session_local(monkeypatch, lambda: session_factory())
    refresh = AsyncMock(return_value=("new-access", "new-refresh", 37))
    register = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(chatbot.divar_service, "refresh_access_token", refresh)
    monkeypatch.setattr(chatbot.divar_service, "register_event_subscription", register)
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", send)

    await chatbot.handle_post_bot_reply("supplier-conversation", post.post_token, "hello", "m1")

    refresh.assert_awaited_once_with("old-access", "old-refresh")
    register.assert_awaited_once_with("new-access")
    send.assert_awaited_once_with("supplier-conversation", settings.GREETING_REPLY_MESSAGE, "new-access")


@pytest.mark.asyncio
async def test_handle_post_bot_reply_send_failure_does_not_persist_bot_message(
    monkeypatch, session_factory, seeded_post, sqlite_upsert
):
    client, post = seeded_post
    async with session_factory() as db:
        db.add(
            OAuthToken(
                client_id=client.id,
                divar_access_token="access-token",
                divar_refresh_token="refresh-token",
                token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        await db.commit()
    response = httpx.Response(502, request=httpx.Request("POST", "https://example.com"))
    error = httpx.HTTPStatusError("send failed", request=response.request, response=response)
    _patch_session_local(monkeypatch, lambda: session_factory())
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", AsyncMock(side_effect=error))

    await chatbot.handle_post_bot_reply("supplier-conversation", post.post_token, "hello", "m1")

    async with session_factory() as db:
        assert not (await db.execute(select(PostMessage))).scalars().all()


@pytest.mark.asyncio
async def test_handle_post_bot_reply_swallows_and_logs_transport_error(
    monkeypatch, session_factory, seeded_post, sqlite_upsert, caplog
):
    """A ConnectTimeout that survived all of send_supplier_message's retries must not
    escape into the BackgroundTask — it used to, because only HTTPStatusError was caught,
    and Starlette logged it as a bare "Exception in ASGI application".
    """
    client, post = seeded_post
    async with session_factory() as db:
        db.add(OAuthToken(
            client_id=client.id,
            divar_access_token="access-token",
            divar_refresh_token="refresh-token",
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await db.commit()
    tracked = _RollbackSpySessionContext(session_factory)
    _patch_session_local(monkeypatch, MagicMock(return_value=tracked))
    error = httpx.ConnectTimeout(
        "timed out", request=httpx.Request("POST", "https://example.com")
    )
    monkeypatch.setattr(
        chatbot.divar_service, "send_supplier_message", AsyncMock(side_effect=error)
    )

    with caplog.at_level(logging.ERROR, logger="chatbot"):
        # No pytest.raises: the point of the test is that nothing propagates.
        await chatbot.handle_post_bot_reply(
            "supplier-conversation", post.post_token, "hello", "m1"
        )

    record = next(
        record
        for record in caplog.records
        if record.message == "supplier message send failed"
    )
    assert record.status_code is None      # no response exists on a transport error
    # str() on both sides: whether logging_config.ContextFilter is installed (it
    # overwrites client_id from the contextvar, as a str) depends on whether another
    # test has called setup_logging, so the raw type here is not order-independent.
    assert str(record.client_id) == str(client.id)
    assert record.conversation_id == "supplier-conversation"
    assert "timed out" in record.error
    assert tracked.rollback_calls == 1
    async with session_factory() as db:
        assert not (await db.execute(select(PostMessage))).scalars().all()


@pytest.mark.asyncio
async def test_handle_post_bot_reply_logs_real_status_code_on_status_error(
    monkeypatch, session_factory, seeded_post, sqlite_upsert, caplog
):
    """Regression guard for the pre-existing branch: widening the except clause to
    httpx.HTTPError must not lose the real status code or the rollback.
    """
    client, post = seeded_post
    async with session_factory() as db:
        db.add(OAuthToken(
            client_id=client.id,
            divar_access_token="access-token",
            divar_refresh_token="refresh-token",
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await db.commit()
    tracked = _RollbackSpySessionContext(session_factory)
    _patch_session_local(monkeypatch, MagicMock(return_value=tracked))
    response = httpx.Response(502, request=httpx.Request("POST", "https://example.com"))
    error = httpx.HTTPStatusError(
        "send failed", request=response.request, response=response
    )
    monkeypatch.setattr(
        chatbot.divar_service, "send_supplier_message", AsyncMock(side_effect=error)
    )

    with caplog.at_level(logging.ERROR, logger="chatbot"):
        await chatbot.handle_post_bot_reply(
            "supplier-conversation", post.post_token, "hello", "m1"
        )

    record = next(
        record
        for record in caplog.records
        if record.message == "supplier message send failed"
    )
    assert record.status_code == 502
    assert str(record.client_id) == str(client.id)   # see note in the test above
    assert record.conversation_id == "supplier-conversation"
    assert tracked.rollback_calls == 1


@pytest.mark.asyncio
async def test_handle_post_bot_reply_refuses_cross_client_conversation(
    monkeypatch, session_factory, seeded_post, sqlite_upsert
):
    client, post = seeded_post
    other = Client(phone_number="09120000002")
    async with session_factory() as db:
        db.add(other)
        await db.flush()
        db.add(PostConversation(
            client_id=other.id,
            divar_conversation_id="shared-conversation",
            post_token=post.post_token,
        ))
        db.add(OAuthToken(
            client_id=client.id,
            divar_access_token="access-token",
            divar_refresh_token="refresh-token",
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await db.commit()
    _patch_session_local(monkeypatch, lambda: session_factory())
    send = AsyncMock()
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", send)

    await chatbot.handle_post_bot_reply("shared-conversation", post.post_token, "hello", "m1")

    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_post_bot_reply_sets_context_and_uses_own_session(
    monkeypatch, session_factory, seeded_post, sqlite_upsert
):
    client, post = seeded_post
    tracked = _TrackedSessionContext(session_factory)
    factory = MagicMock(return_value=tracked)
    _patch_session_local(monkeypatch, factory)
    monkeypatch.setattr(chatbot.divar_service, "send_supplier_message", AsyncMock())
    async with session_factory() as db:
        db.add(OAuthToken(
            client_id=client.id,
            divar_access_token="access-token",
            divar_refresh_token="refresh-token",
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await db.commit()

    await chatbot.handle_post_bot_reply("supplier-conversation", post.post_token, "hello", "m1")

    factory.assert_called_once_with()
    assert tracked.aenter_calls == 1
    assert tracked.aexit_calls == 1
    assert client_id_var.get() == str(client.id)
    assert conversation_id_var.get() == "supplier-conversation"



# ---------------------------------------------------------------------------
# State machine (2.6) — transition table, then the wiring in handle_bot_reply
# ---------------------------------------------------------------------------
class TestTransitionTable:
    """Pure unit tests — no DB, no session."""

    def test_auto_advance_edge_leaves_start(self):
        assert (
            transition(ConversationState.START, "menu") is ConversationState.MAIN_MENU
        )

    def test_price_enters_price_menu(self):
        assert (
            transition(ConversationState.MAIN_MENU, "price")
            is ConversationState.PRICE_MENU
        )

    def test_service_enters_service_menu(self):
        assert (
            transition(ConversationState.MAIN_MENU, "service")
            is ConversationState.SERVICE_MENU
        )

    def test_human_returns_to_main_menu_not_human_support(self):
        """No persistent human-support mode this phase."""
        assert (
            transition(ConversationState.MAIN_MENU, "human")
            is ConversationState.MAIN_MENU
        )

    @pytest.mark.parametrize(
        "state", [ConversationState.PRICE_MENU, ConversationState.SERVICE_MENU]
    )
    def test_menu_states_are_not_sticky(self, state):
        """Intents route out of a menu, rather than being swallowed."""
        assert transition(state, "menu") is ConversationState.MAIN_MENU
        assert transition(state, "human") is ConversationState.MAIN_MENU
        assert transition(state, "service") is ConversationState.SERVICE_MENU
        assert transition(state, "price") is ConversationState.PRICE_MENU

    def test_unknown_event_is_a_no_op(self):
        assert (
            transition(ConversationState.MAIN_MENU, "bogus")
            is ConversationState.MAIN_MENU
        )

    def test_every_intent_maps_to_a_defined_event(self):
        """INTENT_EVENTS and KEYWORD_MAP must not drift apart."""
        assert set(INTENT_EVENTS) == set(settings.KEYWORD_MAP.values())


@pytest_asyncio.fixture
async def bot(monkeypatch, session_factory):
    """Drive handle_bot_reply end-to-end and inspect what it persisted/sent.

    handle_bot_reply opens its own session, so this hands it a fresh one per
    call (the _TrackedSessionContext mock is single-entry and cannot serve a
    multi-message conversation).
    """
    _patch_session_local(monkeypatch, lambda: session_factory())
    send_message = AsyncMock(return_value=True)
    monkeypatch.setattr(chatbot.divar_service, "send_message", send_message)

    class Driver:
        sent = send_message

        async def say(self, text, conversation_id="conv-state"):
            await chatbot.handle_bot_reply(conversation_id, text)
            return [call.args[1] for call in send_message.await_args_list]

        async def state(self, conversation_id="conv-state"):
            async with session_factory() as verify:
                conv = (
                    await verify.execute(
                        select(Conversation).where(
                            Conversation.divar_conversation_id == conversation_id
                        )
                    )
                ).scalar_one()
            return ConversationState(conv.current_state)

    return Driver()


@pytest.mark.asyncio
async def test_first_contact_auto_advances_to_main_menu(
    bot, seeded_post, sqlite_upsert, catalog
):
    """START is not a resting state — first contact moves to MAIN_MENU."""
    _, post = seeded_post

    sent = await bot.say(f"/start MY_POST {post.post_token}")

    assert settings.WELCOME_MESSAGE in sent
    assert await bot.state() is ConversationState.MAIN_MENU


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["پشتیبانی", "اپراتور", "گارانتی"])
async def test_support_and_warranty_reply_with_phone_and_return_to_menu(
    bot, seeded_post, sqlite_upsert, catalog, text
):
    _, post = seeded_post
    await bot.say(f"/start MY_POST {post.post_token}")

    sent = await bot.say(text)

    assert settings.SUPPORT_PHONE_NUMBER in sent[-1]
    assert await bot.state() is ConversationState.MAIN_MENU


@pytest.mark.asyncio
async def test_price_keeps_its_reply_and_moves_to_price_menu(
    bot, seeded_post, sqlite_upsert, catalog
):
    """Price behavior is unchanged; only the state write is new."""
    _, post = seeded_post
    await bot.say(f"/start MY_POST {post.post_token}")

    sent = await bot.say("قیمت آیفون ۱۳")

    assert sent[-1] == "قیمت iPhone 13: 35,000,000 تومان"
    assert await bot.state() is ConversationState.PRICE_MENU


@pytest.mark.asyncio
async def test_service_then_menu_navigates_and_returns(
    bot, seeded_post, sqlite_upsert, catalog
):
    _, post = seeded_post
    await bot.say(f"/start MY_POST {post.post_token}")

    sent = await bot.say("خدمات")
    assert sent[-1] == settings.SERVICE_MENU_MESSAGE
    assert await bot.state() is ConversationState.SERVICE_MENU

    sent = await bot.say("منو")
    assert sent[-1] == settings.MENU_MESSAGE
    assert await bot.state() is ConversationState.MAIN_MENU


@pytest.mark.asyncio
async def test_unknown_text_leaves_state_unchanged(
    bot, seeded_post, sqlite_upsert, catalog
):
    _, post = seeded_post
    await bot.say(f"/start MY_POST {post.post_token}")
    await bot.say("خدمات")

    sent = await bot.say("یک چیز نامرتبط")

    assert sent[-1] == settings.FALLBACK_MESSAGE
    assert await bot.state() is ConversationState.SERVICE_MENU


# ---------------------------------------------------------------------------
# §2.2 conversation-resolution defects (fixed 2026-08-13)
#
# Both drive the race the entry-point lookup cannot see: `_lookup_conversation`
# is patched to None so the redelivered webhook reaches the upsert, exactly as it
# would if two deliveries were in flight before either committed.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_redelivered_start_does_not_rewelcome_or_reset_state(
    monkeypatch, bot, seeded_post, sqlite_upsert, catalog
):
    """A redelivered /start that loses the insert race must be a no-op.

    The conversation is moved off MAIN_MENU first, so a re-applied
    START → MAIN_MENU is observable rather than being masked by
    MAIN_MENU --menu--> MAIN_MENU landing on the same state.
    """
    _, post = seeded_post
    start = f"/start MY_POST {post.post_token}"

    await bot.say(start)
    await bot.say("خدمات")
    assert await bot.state() is ConversationState.SERVICE_MENU

    monkeypatch.setattr(chatbot_conversation, "_lookup_conversation", AsyncMock(return_value=None))
    sent = await bot.say(start)

    # `sent` is cumulative across the conversation: exactly one welcome, ever.
    assert sent.count(settings.WELCOME_MESSAGE) == 1
    assert await bot.state() is ConversationState.SERVICE_MENU


@pytest.mark.asyncio
async def test_cross_client_conversation_id_collision_fails_safe(
    monkeypatch, bot, seeded_post, sqlite_upsert, catalog, session_factory, caplog
):
    """A second client claiming a live divar_conversation_id must not 500.

    The composite ON CONFLICT target does not cover this — it is a different
    client_id — so migration 0004's global UNIQUE raises IntegrityError. That
    must be caught and routed to UNRESOLVED_CLIENT_MESSAGE, the same fail-safe
    path as an unknown post token, leaving the real owner's row untouched.
    """
    client_a, post_a = seeded_post
    async with session_factory() as setup:
        client_b = Client(phone_number="09120000002")
        setup.add(client_b)
        await setup.flush()
        setup.add(Post(post_token="OTHER_TOKEN", client_id=client_b.id))
        await setup.commit()
        client_b_id = client_b.id

    await bot.say(f"/start MY_POST {post_a.post_token}", conversation_id="conv-collide")

    monkeypatch.setattr(chatbot_conversation, "_lookup_conversation", AsyncMock(return_value=None))
    with caplog.at_level(logging.ERROR, logger="chatbot"):
        sent = await bot.say(
            "/start MY_POST OTHER_TOKEN", conversation_id="conv-collide"
        )

    assert sent[-1] == settings.UNRESOLVED_CLIENT_MESSAGE

    # Logged with both sides of the collision, so it is diagnosable in prod.
    collision = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(collision) == 1
    assert collision[0].owner_client_id == client_a.id
    assert collision[0].claiming_client_id == client_b_id
    assert collision[0].divar_conversation_id == "conv-collide"

    # Nothing persisted for B; A still owns the one row.
    async with session_factory() as verify:
        owners = (
            (
                await verify.execute(
                    select(Conversation.client_id).where(
                        Conversation.divar_conversation_id == "conv-collide"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert owners == [client_a.id]
