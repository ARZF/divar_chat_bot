"""Tests for services/divar_listings.py (Phase 3 steps 20-21).

Core rules under test:
* a seller's post tokens enter `posts` only after that seller completed
  Divar OAuth — OTP-only sellers (no oauth_tokens row) never get listings;
* presence semantics: present in the sync → present_on_divar True; absent →
  False, scoped strictly to the syncing client;
* `is_available` is the seller's own chatbot toggle (§3.8.4) — sync NEVER
  writes it, so a manual toggle survives every sync.
"""

from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.client import Client
from models.oauth_token import OAuthToken
from models.post import Post
import services.divar as divar_service
import services.divar_listings as divar_listings


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _user_posts_client(posts: list[dict]) -> AsyncMock:
    """A divar_service.client double whose single GET returns `posts`."""
    return AsyncMock(get=AsyncMock(return_value=_response({"posts": posts})))


POSTS_PAYLOAD = [
    {
        "token": "QVZ8LgaW",
        "title": "اجاره آپارتمان ۱۰۰ متری",
        "is_phone_hidden": True,
        "supplier_chat_assistant_enabled": True,
        "category": "apartment-rent",
    },
    {
        "token": "GZb9NfaX",
        "title": "خودرو مدل ۹۸",
        "is_phone_hidden": False,
        "supplier_chat_assistant_enabled": False,
        "category": "car",
    },
]


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [Client.__table__, Post.__table__, OAuthToken.__table__]
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


_phone_counter = count(1)


async def _add_client(db: AsyncSession, *, with_token: bool = True) -> Client:
    client = Client(phone_number=f"0912000{next(_phone_counter):05d}")
    db.add(client)
    await db.flush()
    if with_token:
        db.add(
            OAuthToken(
                client_id=client.id,
                divar_access_token="access-1",
                divar_refresh_token="refresh-1",
                token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
    await db.commit()
    return client


async def _get_post(db: AsyncSession, token: str) -> Post | None:
    return (
        await db.execute(select(Post).where(Post.post_token == token))
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_sync_skips_seller_without_oauth_token(db, mocker):
    """OTP-only seller: no OAuthToken row → sync is a no-op, no HTTP call."""
    client = await _add_client(db, with_token=False)
    http = _user_posts_client(POSTS_PAYLOAD)
    mocker.patch.object(divar_service, "client", new=http)

    result = await divar_listings.sync_listings(db, client.id)

    assert result is None
    assert http.get.await_count == 0
    assert (await db.execute(select(Post))).scalars().all() == []


@pytest.mark.asyncio
async def test_sync_inserts_new_posts_with_metadata_in_one_request(db, mocker):
    client = await _add_client(db)
    http = _user_posts_client(POSTS_PAYLOAD)
    mocker.patch.object(divar_service, "client", new=http)

    result = await divar_listings.sync_listings(db, client.id)

    assert result == {"registered": 2, "updated": 0, "marked_absent": 0}
    # One API request per sync — no per-post enrichment calls.
    assert http.get.await_count == 1
    call = http.get.await_args
    assert call.args[0] == divar_listings.USER_POSTS_URL
    assert call.kwargs["headers"]["Authorization"] == "Bearer access-1"

    post = await _get_post(db, "QVZ8LgaW")
    assert post.client_id == client.id
    assert post.title == "اجاره آپارتمان ۱۰۰ متری"
    assert post.category == "apartment-rent"
    assert post.is_phone_hidden is True
    assert post.chat_enabled is True
    assert post.present_on_divar is True
    assert post.is_available is True  # default — the seller's toggle, untouched
    assert post.last_synced_at is not None

    post2 = await _get_post(db, "GZb9NfaX")
    assert post2.chat_enabled is False
    assert post2.present_on_divar is True


@pytest.mark.asyncio
async def test_sync_updates_own_post_and_marks_missing_one_absent(db, mocker):
    client = await _add_client(db)
    db.add(
        Post(
            post_token="QVZ8LgaW",
            client_id=client.id,
            title="old title",
            present_on_divar=True,
            is_available=False,  # seller disabled the chatbot — sync must NOT flip it
        )
    )
    db.add(Post(post_token="GONE01", client_id=client.id, present_on_divar=True))
    await db.commit()
    mocker.patch.object(
        divar_service, "client", new=_user_posts_client([POSTS_PAYLOAD[0]])
    )

    result = await divar_listings.sync_listings(db, client.id)

    assert result == {"registered": 0, "updated": 1, "marked_absent": 1}

    present = await _get_post(db, "QVZ8LgaW")
    assert present.title == "اجاره آپارتمان ۱۰۰ متری"
    assert present.present_on_divar is True
    # The manual chatbot-off toggle survived the sync.
    assert present.is_available is False

    gone = await _get_post(db, "GONE01")
    assert gone.present_on_divar is False
    assert gone.is_available is True  # seller's toggle untouched by absence


@pytest.mark.asyncio
async def test_sync_never_touches_another_clients_posts(db, mocker):
    """Tenant scoping: absent posts of ANOTHER client stay available, and a
    token the other client owns is never stolen by this client's sync."""
    client = await _add_client(db)
    other = Client(phone_number="09120000002")
    db.add(other)
    await db.flush()
    # other's post: absent from this sync AND present under another client's
    # ownership — both protections tested at once is ambiguous, so split:
    db.add(Post(post_token="OTHER_GONE", client_id=other.id, present_on_divar=True))
    db.add(
        Post(
            post_token="QVZ8LgaW",
            client_id=other.id,
            title="other's title",
            present_on_divar=False,
            is_available=False,
        )
    )
    await db.commit()
    mocker.patch.object(
        divar_service, "client", new=_user_posts_client([POSTS_PAYLOAD[0]])
    )

    result = await divar_listings.sync_listings(db, client.id)

    # QVZ8LgaW exists (owned by `other`) → ON CONFLICT DO NOTHING, not stolen.
    assert result["registered"] == 0

    stolen = await _get_post(db, "QVZ8LgaW")
    assert stolen.client_id == other.id
    assert stolen.title == "other's title"
    assert stolen.present_on_divar is False  # untouched, not re-activated
    assert stolen.is_available is False  # untouched — and never sync's to write
    assert stolen.last_synced_at is None

    # OTHER_GONE is absent from the sync but belongs to `other` — untouched.
    untouched = await _get_post(db, "OTHER_GONE")
    assert untouched.client_id == other.id
    assert untouched.present_on_divar is True


@pytest.mark.asyncio
async def test_sync_empty_response_marks_all_own_posts_absent(db, mocker):
    """The seller genuinely has no listings on Divar → all their own posts
    are marked absent; another client's posts are untouched."""
    client = await _add_client(db)
    other = Client(phone_number="09120000002")
    db.add(other)
    await db.flush()
    db.add(Post(post_token="P1", client_id=client.id, present_on_divar=True))
    db.add(Post(post_token="P2", client_id=client.id, present_on_divar=True))
    db.add(Post(post_token="OTHER1", client_id=other.id, present_on_divar=True))
    await db.commit()
    mocker.patch.object(divar_service, "client", new=_user_posts_client([]))

    result = await divar_listings.sync_listings(db, client.id)

    assert result == {"registered": 0, "updated": 0, "marked_absent": 2}
    assert (await _get_post(db, "P1")).present_on_divar is False
    assert (await _get_post(db, "P2")).present_on_divar is False
    assert (await _get_post(db, "OTHER1")).present_on_divar is True


@pytest.mark.asyncio
async def test_sync_refreshes_expired_token_before_fetching(db, mocker):
    client = await _add_client(db)
    # Age the token so sync_listings must refresh before the GET.
    token = (
        await db.execute(select(OAuthToken).where(OAuthToken.client_id == client.id))
    ).scalar_one()
    token.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    refresh = mocker.patch.object(
        divar_listings,
        "_refresh_supplier_token",
        new=AsyncMock(return_value="access-2"),
    )
    http = _user_posts_client(POSTS_PAYLOAD)
    mocker.patch.object(divar_service, "client", new=http)

    result = await divar_listings.sync_listings(db, client.id)

    refresh.assert_awaited_once_with(client.id)
    assert result["registered"] == 2
    assert http.get.await_args.kwargs["headers"]["Authorization"] == "Bearer access-2"


@pytest.mark.asyncio
async def test_sync_returns_none_when_token_refresh_fails(db, mocker):
    client = await _add_client(db)
    token = (
        await db.execute(select(OAuthToken).where(OAuthToken.client_id == client.id))
    ).scalar_one()
    token.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    mocker.patch.object(
        divar_listings, "_refresh_supplier_token", new=AsyncMock(return_value=None)
    )
    http = _user_posts_client(POSTS_PAYLOAD)
    mocker.patch.object(divar_service, "client", new=http)

    assert await divar_listings.sync_listings(db, client.id) is None
    assert http.get.await_count == 0


@pytest.mark.asyncio
async def test_sync_aborts_without_writes_when_divar_fails(db, mocker):
    """A failed fetch must not look like 'the seller has no listings' —
    the HTTP error propagates before anything is written."""
    client = await _add_client(db)
    db.add(Post(post_token="P1", client_id=client.id, is_available=True))
    await db.commit()

    failing = MagicMock()
    failing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock()
    )
    mocker.patch.object(
        divar_service, "client", new=AsyncMock(get=AsyncMock(return_value=failing))
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar_listings.sync_listings(db, client.id)

    # Nothing was written: the post is still present and untouched.
    assert (await _get_post(db, "P1")).present_on_divar is True
    assert (await _get_post(db, "P1")).is_available is True


@pytest.mark.asyncio
async def test_get_user_posts_rejects_malformed_payload(mocker):
    """Defensive shape check: a non-list `posts` value raises instead of
    being treated as an empty listing set."""
    http = AsyncMock(
        get=AsyncMock(return_value=_response({"posts": "not-a-list"}))
    )
    mocker.patch.object(divar_service, "client", new=http)

    with pytest.raises(ValueError):
        await divar_listings.get_user_posts("access-1")
