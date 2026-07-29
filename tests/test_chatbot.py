# Env vars for config.py are set by the root conftest.py before collection.
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from config import settings
from models.client import Client
from models.conversation import Conversation
from models.post import Post
from models.product import Product
import services.chatbot as chatbot
import services.price_lookup as pl
from services.price_lookup import normalize_text

# Test client_id used by the price-cache fixture (mirrors tests/test_price_lookup.py)
CID = 1


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
    tables = [
        Client.__table__,
        Post.__table__,
        Conversation.__table__,
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


@pytest.fixture
def sqlite_upsert(monkeypatch):
    monkeypatch.setattr(
        chatbot,
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
