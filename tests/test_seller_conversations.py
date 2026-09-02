"""Seller post-conversation read-API tests (Phase 3 step 24, cleaned).

Step 24's seller-facing Conversations feature exposes ONLY the supplier-side
Divar conversation system (`post_conversations` / `post_messages`) — the
system the seller dashboard (step 25) reads. The Buyer↔Bot system
(`conversations` / `messages`) is intentionally NOT part of the seller API,
and its endpoints are asserted gone here.

Covers: JWT gates, two-tenant isolation, the non-leaking 404 (§3.14),
tenant-safe listing mapping (a conversation whose `post_token` is foreign or
missing must not leak another tenant's listing title), bounded pagination
with stable ordering, chronological message history, empty states, and the
security contract (no client_id / auth tokens / payload / internal ids).
"""

import json
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from config import settings
from db.session import get_db
from main import app
from models.client import Client
from models.enums import PostConversationState
from models.post import Post
from models.post_conversation import PostConversation
from models.post_message import PostMessage, PostSenderType

POST_TABLES = [
    Client.__table__,
    Post.__table__,
    PostConversation.__table__,
    PostMessage.__table__,
]


def make_access_token(client_id: int) -> str:
    payload = {
        "client_id": client_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def auth(client_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_access_token(client_id)}"}


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Client.metadata.create_all(c, tables=POST_TABLES))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def two_tenants(session_factory):
    """Seller A: 1 post + 4 post-conversations — one with stored messages,
    one with none, one whose `post_token` belongs to seller B (foreign), one
    whose `post_token` has no `posts` row at all (missing). Seller B: 1 post
    + 1 conversation — A must never see any of B's rows or B's listing
    title."""
    T = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    async with session_factory() as db:
        seller_a = Client(phone_number="09120000001")
        seller_b = Client(phone_number="09120000002")
        db.add_all([seller_a, seller_b])
        await db.flush()

        db.add_all([
            Post(
                post_token="A_LIVE",
                client_id=seller_a.id,
                title="اجاره آپارتمان ۱۰۰ متری",
                category="apartment-rent",
                present_on_divar=True,
                created_at=T,
            ),
            Post(
                post_token="B_ONLY",
                client_id=seller_b.id,
                title="فروش موبایل",
                present_on_divar=True,
                created_at=T,
            ),
        ])

        convs = [
            PostConversation(  # newest-updated listed last here — see order below
                client_id=seller_a.id,
                divar_conversation_id="a-post-1",
                post_token="A_LIVE",
                current_state=PostConversationState.NEW,
                created_at=T,
                updated_at=T + timedelta(hours=1),
            ),
            PostConversation(
                client_id=seller_a.id,
                divar_conversation_id="a-post-2",
                post_token="A_LIVE",
                current_state=PostConversationState.ACTIVE,
                created_at=T,
                updated_at=T + timedelta(hours=2),
            ),
            PostConversation(
                client_id=seller_a.id,
                divar_conversation_id="a-post-3",
                post_token="B_ONLY",  # foreign — not owned by A
                current_state=PostConversationState.NEW,
                created_at=T,
                updated_at=T + timedelta(hours=3),
            ),
            PostConversation(
                client_id=seller_a.id,
                divar_conversation_id="a-post-4",
                post_token="NOPE_GHOST",  # missing — no posts row
                current_state=PostConversationState.NEW,
                created_at=T,
                updated_at=T + timedelta(hours=4),
            ),
            PostConversation(
                client_id=seller_b.id,
                divar_conversation_id="b-post-1",
                post_token="B_ONLY",
                current_state=PostConversationState.NEW,
                created_at=T,
                updated_at=T,
            ),
        ]
        db.add_all(convs)
        await db.flush()

        db.add_all([
            PostMessage(
                post_conversation_id=convs[0].id,
                sender_type=PostSenderType.BUYER,
                text_content="سلام، موجود هست؟",
                created_at=T,
            ),
            PostMessage(
                post_conversation_id=convs[0].id,
                sender_type=PostSenderType.BOT,
                text_content="بله، موجود است.",
                created_at=T + timedelta(minutes=1),
            ),
            PostMessage(
                post_conversation_id=convs[4].id,
                sender_type=PostSenderType.BUYER,
                text_content="قیمتش چنده؟",
                created_at=T,
            ),
        ])
        await db.commit()
        return seller_a.id, seller_b.id


@pytest.fixture
def client(session_factory):
    async def _override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


READ_ENDPOINTS = [
    ("GET", "/api/v1/seller/post-conversations"),
    ("GET", "/api/v1/seller/post-conversations/some-conv"),
    ("GET", "/api/v1/seller/post-conversations/some-conv/messages"),
]


# --------------------------------------------------------------------------------------
# JWT gate
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", READ_ENDPOINTS)
def test_endpoints_require_authorization_header(client, method, path):
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize("method,path", READ_ENDPOINTS)
def test_endpoints_reject_invalid_token(client, method, path):
    response = client.request(
        method, path, headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------------------
# List — tenant-scoped, tenant-safe listing mapping, bounded pagination
# --------------------------------------------------------------------------------------

def test_list_is_scoped_and_returns_listing_context(client, two_tenants):
    seller_a_id, _ = two_tenants
    body = client.get(
        "/api/v1/seller/post-conversations", headers=auth(seller_a_id)
    ).json()

    assert set(body) == {"items", "page", "page_size", "total", "page_count"}
    assert body["total"] == 4
    assert body["page"] == 1 and body["page_size"] == 20 and body["page_count"] == 1
    # updated_at DESC, id DESC — a-post-4 (T+4h) … a-post-1 (T+1h).
    assert [i["conversation_id"] for i in body["items"]] == [
        "a-post-4", "a-post-3", "a-post-2", "a-post-1",
    ]
    by_id = {i["conversation_id"]: i for i in body["items"]}
    # Full field contract; client_id never leaks; no unsupported fields.
    assert set(by_id["a-post-1"]) == {
        "conversation_id", "post_token", "listing_title", "current_state",
        "created_at", "updated_at", "last_message",
    }
    assert by_id["a-post-1"]["post_token"] == "A_LIVE"
    assert by_id["a-post-1"]["listing_title"] == "اجاره آپارتمان ۱۰۰ متری"
    assert by_id["a-post-1"]["current_state"] == "NEW"
    # Preview is the LATEST stored message only — bounded, never full history.
    lm = by_id["a-post-1"]["last_message"]
    assert set(lm) == {"sender_type", "text_content", "sent_at"}
    assert lm["sender_type"] == "bot"
    assert lm["text_content"] == "بله، موجود است."
    # Conversation without stored messages → honest null preview.
    assert by_id["a-post-2"]["last_message"] is None
    assert by_id["a-post-2"]["current_state"] == "ACTIVE"


def test_list_never_leaks_foreign_or_missing_listing_metadata(client, two_tenants):
    """A conversation whose post_token belongs to another tenant (a-post-3)
    or matches no posts row (a-post-4) gets listing_title=None — B's title
    never appears anywhere in A's list."""
    seller_a_id, _ = two_tenants
    body = client.get(
        "/api/v1/seller/post-conversations", headers=auth(seller_a_id)
    ).json()
    by_id = {i["conversation_id"]: i for i in body["items"]}

    assert by_id["a-post-3"]["post_token"] == "B_ONLY"
    assert by_id["a-post-3"]["listing_title"] is None  # foreign → no leak
    assert by_id["a-post-4"]["post_token"] == "NOPE_GHOST"
    assert by_id["a-post-4"]["listing_title"] is None  # missing → no fabrication

    dumped = json.dumps(body, ensure_ascii=False)
    assert "فروش موبایل" not in dumped  # B's title is absent from A's list


def test_list_is_scoped_to_the_jwt_client(client, two_tenants):
    seller_a_id, seller_b_id = two_tenants

    body_a = client.get(
        "/api/v1/seller/post-conversations", headers=auth(seller_a_id)
    ).json()
    body_b = client.get(
        "/api/v1/seller/post-conversations", headers=auth(seller_b_id)
    ).json()

    assert [i["conversation_id"] for i in body_a["items"]] == [
        "a-post-4", "a-post-3", "a-post-2", "a-post-1",
    ]
    assert body_b["total"] == 1
    assert body_b["items"][0]["conversation_id"] == "b-post-1"


def test_list_ignores_client_id_from_browser(client, two_tenants):
    seller_a_id, seller_b_id = two_tenants

    response = client.get(
        "/api/v1/seller/post-conversations",
        params={"client_id": str(seller_b_id)},
        headers=auth(seller_a_id),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 4


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}])
def test_list_rejects_out_of_bounds_pagination(client, two_tenants, params):
    seller_a_id, _ = two_tenants
    response = client.get(
        "/api/v1/seller/post-conversations",
        params=params,
        headers=auth(seller_a_id),
    )
    assert response.status_code == 422


def test_list_pagination_pages_and_metadata(client, two_tenants):
    seller_a_id, _ = two_tenants
    page1 = client.get(
        "/api/v1/seller/post-conversations",
        params={"page": 1, "page_size": 2},
        headers=auth(seller_a_id),
    ).json()
    page2 = client.get(
        "/api/v1/seller/post-conversations",
        params={"page": 2, "page_size": 2},
        headers=auth(seller_a_id),
    ).json()

    assert len(page1["items"]) == 2 and len(page2["items"]) == 2
    assert page1["total"] == 4 and page1["page_count"] == 2
    assert [i["conversation_id"] for i in page1["items"]] == ["a-post-4", "a-post-3"]
    assert [i["conversation_id"] for i in page2["items"]] == ["a-post-2", "a-post-1"]
    assert page1["page"] == 1 and page2["page"] == 2


def test_list_empty_page_is_honest(client, two_tenants):
    seller_a_id, _ = two_tenants
    body = client.get(
        "/api/v1/seller/post-conversations",
        params={"page": 99},
        headers=auth(seller_a_id),
    ).json()
    assert body["items"] == []
    assert body["total"] == 4
    assert body["page_count"] == 1


# --------------------------------------------------------------------------------------
# Detail — tenant-scoped, non-leaking 404, tenant-safe listing mapping
# --------------------------------------------------------------------------------------

def test_detail_returns_own_with_listing_context(client, two_tenants):
    seller_a_id, _ = two_tenants
    body = client.get(
        "/api/v1/seller/post-conversations/a-post-1", headers=auth(seller_a_id)
    ).json()

    assert body["conversation_id"] == "a-post-1"
    assert body["post_token"] == "A_LIVE"
    assert body["listing_title"] == "اجاره آپارتمان ۱۰۰ متری"
    assert body["current_state"] == "NEW"
    # Detail carries the conversation fields only (no preview / no internal id).
    assert set(body) == {
        "conversation_id", "post_token", "listing_title",
        "current_state", "created_at", "updated_at",
    }


def test_detail_never_leaks_foreign_or_missing_listing_metadata(client, two_tenants):
    seller_a_id, _ = two_tenants

    foreign = client.get(
        "/api/v1/seller/post-conversations/a-post-3", headers=auth(seller_a_id)
    ).json()
    assert foreign["post_token"] == "B_ONLY"
    assert foreign["listing_title"] is None

    missing = client.get(
        "/api/v1/seller/post-conversations/a-post-4", headers=auth(seller_a_id)
    ).json()
    assert missing["post_token"] == "NOPE_GHOST"
    assert missing["listing_title"] is None

    dumped = json.dumps([foreign, missing], ensure_ascii=False)
    assert "فروش موبایل" not in dumped  # B's title is never sourced


def test_cross_tenant_and_nonexistent_share_same_404(client, two_tenants):
    seller_a_id, _ = two_tenants

    cross_tenant = client.get(
        "/api/v1/seller/post-conversations/b-post-1", headers=auth(seller_a_id)
    )
    nonexistent = client.get(
        "/api/v1/seller/post-conversations/nope-123", headers=auth(seller_a_id)
    )
    cross_messages = client.get(
        "/api/v1/seller/post-conversations/b-post-1/messages", headers=auth(seller_a_id)
    )

    for response in (cross_tenant, cross_messages):
        assert response.status_code == 404
        assert response.json() == {"detail": "Conversation not found"}
    assert cross_tenant.json() == nonexistent.json()


# --------------------------------------------------------------------------------------
# Message history — chronological, stable, scoped, bounded
# --------------------------------------------------------------------------------------

def test_message_history_chronological_and_scoped(client, two_tenants):
    seller_a_id, _ = two_tenants
    body = client.get(
        "/api/v1/seller/post-conversations/a-post-1/messages",
        headers=auth(seller_a_id),
    ).json()

    assert body["total"] == 2
    items = body["items"]
    assert set(items[0]) == {"sender_type", "text_content", "sent_at"}
    assert [i["sender_type"] for i in items] == ["buyer", "bot"]
    assert [i["text_content"] for i in items] == ["سلام، موجود هست؟", "بله، موجود است."]
    sent = [i["sent_at"] for i in items]
    assert sent == sorted(sent)  # created_at ASC, stable


def test_history_empty_for_conversation_without_messages(client, two_tenants):
    seller_a_id, _ = two_tenants
    body = client.get(
        "/api/v1/seller/post-conversations/a-post-2/messages",
        headers=auth(seller_a_id),
    ).json()
    assert body["items"] == []
    assert body["total"] == 0 and body["page_count"] == 0


@pytest.mark.parametrize(
    "params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}]
)
def test_history_rejects_out_of_bounds_pagination(client, two_tenants, params):
    seller_a_id, _ = two_tenants
    response = client.get(
        "/api/v1/seller/post-conversations/a-post-1/messages",
        params=params,
        headers=auth(seller_a_id),
    )
    assert response.status_code == 422


def test_history_pagination_pages(client, two_tenants):
    seller_a_id, _ = two_tenants
    page1 = client.get(
        "/api/v1/seller/post-conversations/a-post-1/messages",
        params={"page": 1, "page_size": 1},
        headers=auth(seller_a_id),
    ).json()
    page2 = client.get(
        "/api/v1/seller/post-conversations/a-post-1/messages",
        params={"page": 2, "page_size": 1},
        headers=auth(seller_a_id),
    ).json()

    assert [i["text_content"] for i in page1["items"]] == ["سلام، موجود هست؟"]
    assert [i["text_content"] for i in page2["items"]] == ["بله، موجود است."]
    assert page1["total"] == 2 and page1["page_count"] == 2


# --------------------------------------------------------------------------------------
# Security contract — no client_id, auth tokens, payload, or internal ids
# --------------------------------------------------------------------------------------

FORBIDDEN_KEYS = {
    "client_id",
    "id",
    "divar_message_id",
    "payload",
    "metadata",
    "divar_access_token",
    "divar_refresh_token",
    "token_hash",
    "code_hash",
    "otp_code",
    "access_token",
    "refresh_token",
}


def _assert_no_forbidden_keys(obj, forbidden, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key not in forbidden, (path, key)
            _assert_no_forbidden_keys(value, forbidden, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _assert_no_forbidden_keys(value, forbidden, f"{path}[{i}]")


def test_responses_never_leak_internal_or_sensitive_fields(client, two_tenants):
    seller_a_id, _ = two_tenants
    responses = [
        client.get("/api/v1/seller/post-conversations", headers=auth(seller_a_id)).json(),
        client.get(
            "/api/v1/seller/post-conversations/a-post-1", headers=auth(seller_a_id)
        ).json(),
        client.get(
            "/api/v1/seller/post-conversations/a-post-1/messages",
            headers=auth(seller_a_id),
        ).json(),
    ]
    for body in responses:
        _assert_no_forbidden_keys(body, FORBIDDEN_KEYS)
        dumped = json.dumps(body, ensure_ascii=False)
        # Content markers for credential material must not appear at all.
        for marker in ("divar_access_token", "refresh_token", "code_hash", "JWT"):
            assert marker not in dumped, (marker, dumped)


# --------------------------------------------------------------------------------------
# The Buyer↔Bot seller API does not exist
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/seller/conversations",
        "/api/v1/seller/conversations/a-bot-1",
        "/api/v1/seller/conversations/a-bot-1/messages",
    ],
)
def test_bot_conversation_endpoints_are_removed(client, two_tenants, path):
    """The Buyer↔Bot system is not part of the seller conversation API — no
    route exists (404 even with a valid JWT)."""
    seller_a_id, _ = two_tenants
    assert client.get(path, headers=auth(seller_a_id)).status_code == 404
