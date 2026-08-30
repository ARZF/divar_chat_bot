"""Seller listing API tests (Phase 3 step 21).

Covers the three listing endpoints: the read-only list (never calls Divar),
the explicit sync trigger, and the availability PATCH (§3.8.4 — the seller's
own chatbot toggle, never touched by sync). JWT gates, two-tenant isolation,
the non-leaking 404 (§3.14), the OTP-only honest-empty-list rule, PATCH
purity, and the sync endpoint's tenant scoping and failure mapping.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt as pyjwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from config import settings
from db.session import get_db
from main import app
from models.client import Client
from models.oauth_token import OAuthToken
from models.post import Post
import services.divar as divar_service


def make_access_token(client_id: int) -> str:
    payload = {
        "client_id": client_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def auth(client_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_access_token(client_id)}"}


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _user_posts_http(posts: list[dict]) -> AsyncMock:
    """A divar_service.client double whose single GET returns `posts`."""
    return AsyncMock(get=AsyncMock(return_value=_response({"posts": posts})))


DIVAR_POST = {
    "token": "QVZ8LgaW",
    "title": "اجاره آپارتمان ۱۰۰ متری",
    "is_phone_hidden": True,
    "supplier_chat_assistant_enabled": True,
    "category": "apartment-rent",
}


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Client.metadata.create_all(
                c, tables=[Client.__table__, Post.__table__, OAuthToken.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def two_tenants(session_factory):
    """Seller A with an OAuth token and two listings (one still on Divar,
    one removed); seller B with one listing. OTP-only seller C has a client
    row but no oauth_tokens row — and therefore no listings (posts rows
    only enter through sync, which requires OAuth)."""
    async with session_factory() as db:
        seller_a = Client(phone_number="09120000001")
        seller_b = Client(phone_number="09120000002")
        otp_only = Client(phone_number="09120000003")
        db.add_all([seller_a, seller_b, otp_only])
        await db.flush()

        db.add(
            OAuthToken(
                client_id=seller_a.id,
                divar_access_token="access-a",
                divar_refresh_token="refresh-a",
                token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        db.add_all([
            Post(
                post_token="A_LIVE",
                client_id=seller_a.id,
                title="اجاره آپارتمان ۱۰۰ متری",
                category="apartment-rent",
                chat_enabled=True,
                is_phone_hidden=True,
                present_on_divar=True,
                last_synced_at=datetime(2026, 8, 30, 10, tzinfo=timezone.utc),
                # Deterministic list ordering: created_at DESC, post_token ASC.
                created_at=datetime(2026, 8, 30, 9, tzinfo=timezone.utc),
            ),
            Post(
                post_token="A_GONE",
                client_id=seller_a.id,
                title="removed listing",
                present_on_divar=False,
                last_synced_at=datetime(2026, 8, 28, 10, tzinfo=timezone.utc),
                created_at=datetime(2026, 8, 28, 9, tzinfo=timezone.utc),
            ),
            Post(
                post_token="B_ONLY",
                client_id=seller_b.id,
                present_on_divar=True,
                created_at=datetime(2026, 8, 29, 9, tzinfo=timezone.utc),
            ),
        ])
        await db.commit()
        return seller_a.id, seller_b.id, otp_only.id


@pytest.fixture
def client(session_factory):
    async def _override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------------------
# JWT gate
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/seller/listings"),
        ("POST", "/api/v1/seller/listings/sync"),
        ("PATCH", "/api/v1/seller/listings/some-token/availability"),
    ],
)
def test_endpoints_require_authorization_header(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/seller/listings"),
        ("POST", "/api/v1/seller/listings/sync"),
        ("PATCH", "/api/v1/seller/listings/some-token/availability"),
    ],
)
def test_endpoints_reject_invalid_token(client, method, path):
    response = client.request(
        method, path, json={}, headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------------------
# GET /api/v1/seller/listings — read-only, tenant-scoped
# --------------------------------------------------------------------------------------

def test_list_returns_own_rows_and_never_calls_divar(client, two_tenants, mocker):
    seller_a_id, _, _ = two_tenants
    http = _user_posts_http([])
    mocker.patch.object(divar_service, "client", new=http)

    response = client.get("/api/v1/seller/listings", headers=auth(seller_a_id))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "page", "page_size", "total", "page_count"}
    assert body["total"] == 2
    assert body["page"] == 1 and body["page_size"] == 20 and body["page_count"] == 1
    by_token = {item["post_token"]: item for item in body["items"]}
    # Full field contract; client_id never leaks; no unsupported fields.
    assert set(by_token["A_LIVE"]) == {
        "post_token",
        "title",
        "category",
        "chat_enabled",
        "is_phone_hidden",
        "is_available",
        "present_on_divar",
        "last_synced_at",
    }
    assert by_token["A_LIVE"]["present_on_divar"] is True
    assert by_token["A_LIVE"]["is_available"] is True
    assert by_token["A_GONE"]["present_on_divar"] is False
    # Read endpoint never spends a Divar API call (rate limits are per-app).
    assert http.get.await_count == 0


def test_list_is_scoped_to_the_jwt_client(client, two_tenants):
    seller_a_id, seller_b_id, _ = two_tenants

    body_a = client.get("/api/v1/seller/listings", headers=auth(seller_a_id)).json()
    body_b = client.get("/api/v1/seller/listings", headers=auth(seller_b_id)).json()

    assert [i["post_token"] for i in body_a["items"]] == ["A_LIVE", "A_GONE"]
    assert [i["post_token"] for i in body_b["items"]] == ["B_ONLY"]


def test_list_ignores_client_id_from_browser(client, two_tenants):
    seller_a_id, seller_b_id, _ = two_tenants

    response = client.get(
        "/api/v1/seller/listings",
        params={"client_id": str(seller_b_id)},
        headers=auth(seller_a_id),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_list_for_otp_only_seller_returns_honest_empty_list(client, two_tenants, mocker):
    """Never completed Divar OAuth: no synced listings, and no error —
    §3.8's 'must work without post_token/without sync' spirit."""
    _, _, otp_only_id = two_tenants
    http = _user_posts_http([])
    mocker.patch.object(divar_service, "client", new=http)

    response = client.get("/api/v1/seller/listings", headers=auth(otp_only_id))

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    assert http.get.await_count == 0


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}])
def test_list_rejects_out_of_bounds_pagination(client, two_tenants, params):
    seller_a_id, _, _ = two_tenants

    response = client.get(
        "/api/v1/seller/listings", params=params, headers=auth(seller_a_id)
    )
    assert response.status_code == 422


def test_list_pagination_pages_and_metadata(client, two_tenants):
    seller_a_id, _, _ = two_tenants

    page1 = client.get(
        "/api/v1/seller/listings",
        params={"page": 1, "page_size": 1},
        headers=auth(seller_a_id),
    ).json()
    page2 = client.get(
        "/api/v1/seller/listings",
        params={"page": 2, "page_size": 1},
        headers=auth(seller_a_id),
    ).json()

    assert len(page1["items"]) == 1 and len(page2["items"]) == 1
    assert page1["total"] == 2 and page1["page_count"] == 2
    assert page1["items"][0]["post_token"] != page2["items"][0]["post_token"]


# --------------------------------------------------------------------------------------
# POST /api/v1/seller/listings/sync — explicit trigger, tenant-scoped
# --------------------------------------------------------------------------------------

def test_sync_registers_own_listings_from_divar(client, two_tenants, mocker):
    seller_a_id, seller_b_id, _ = two_tenants
    # A_LIVE matches the seeded row (→ updated); A_NEW is unseen (→
    # registered); A_GONE is absent from the response (→ marked_absent).
    http = _user_posts_http(
        [dict(DIVAR_POST, token="A_LIVE"), {"token": "A_NEW"}]
    )
    mocker.patch.object(divar_service, "client", new=http)

    response = client.post("/api/v1/seller/listings/sync", headers=auth(seller_a_id))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "registered": 1,  # A_NEW
        "updated": 1,  # A_LIVE metadata refreshed
        "marked_absent": 1,  # A_GONE no longer on Divar
    }
    assert http.get.await_count == 1

    # B's row is untouched by A's sync.
    body_b = client.get("/api/v1/seller/listings", headers=auth(seller_b_id)).json()
    assert [i["post_token"] for i in body_b["items"]] == ["B_ONLY"]
    assert body_b["items"][0]["present_on_divar"] is True


def test_sync_for_otp_only_seller_skips_without_http_call(client, two_tenants, mocker):
    _, _, otp_only_id = two_tenants
    http = _user_posts_http([DIVAR_POST])
    mocker.patch.object(divar_service, "client", new=http)

    response = client.post(
        "/api/v1/seller/listings/sync", headers=auth(otp_only_id)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert http.get.await_count == 0
    # Nothing was written.
    body = client.get("/api/v1/seller/listings", headers=auth(otp_only_id)).json()
    assert body["total"] == 0


def test_sync_maps_divar_failure_to_502_without_writes(client, two_tenants, mocker):
    seller_a_id, _, _ = two_tenants
    failing = MagicMock()
    failing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock()
    )
    mocker.patch.object(
        divar_service, "client", new=AsyncMock(get=AsyncMock(return_value=failing))
    )

    response = client.post("/api/v1/seller/listings/sync", headers=auth(seller_a_id))

    assert response.status_code == 502
    # A failed fetch must not tombstone the seller's existing listings.
    body = client.get("/api/v1/seller/listings", headers=auth(seller_a_id)).json()
    assert body["total"] == 2
    assert body["items"][0]["present_on_divar"] is True


# --------------------------------------------------------------------------------------
# PATCH /api/v1/seller/listings/{post_token}/availability — §3.8.4
# --------------------------------------------------------------------------------------

def test_patch_toggles_is_available_and_returns_full_item(client, two_tenants, mocker):
    seller_a_id, _, _ = two_tenants
    http = _user_posts_http([])
    mocker.patch.object(divar_service, "client", new=http)

    response = client.patch(
        "/api/v1/seller/listings/A_LIVE/availability",
        json={"is_available": False},
        headers=auth(seller_a_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["post_token"] == "A_LIVE"
    assert body["is_available"] is False
    assert body["present_on_divar"] is True  # untouched by the toggle
    # PATCH never calls Divar.
    assert http.get.await_count == 0

    # The toggle is visible through the list endpoint.
    listed = client.get("/api/v1/seller/listings", headers=auth(seller_a_id)).json()
    assert listed["items"][0]["is_available"] is False


@pytest.mark.asyncio
async def test_patch_changes_only_is_available(session_factory, two_tenants):
    """The toggle must not touch any Divar-sourced column or the presence
    flag — verified on the row itself, not just the response."""
    seller_a_id, _, _ = two_tenants
    async with session_factory() as db:
        row = (
            await db.execute(select(Post).where(Post.post_token == "A_LIVE"))
        ).scalar_one()
        before = {
            "title": row.title,
            "category": row.category,
            "chat_enabled": row.chat_enabled,
            "is_phone_hidden": row.is_phone_hidden,
            "present_on_divar": row.present_on_divar,
            "last_synced_at": row.last_synced_at,
        }

        # PATCH via the route function directly (single event loop).
        from api.seller import update_listing_availability
        from schemas.seller import ListingAvailabilityUpdateRequest

        await update_listing_availability(
            "A_LIVE",
            ListingAvailabilityUpdateRequest(is_available=False),
            client_id=seller_a_id,
            db=db,
        )

        fresh = (
            await db.execute(select(Post).where(Post.post_token == "A_LIVE"))
        ).scalar_one()
        assert fresh.is_available is False
        for field, value in before.items():
            assert getattr(fresh, field) == value


def test_patch_rejects_missing_or_non_boolean_body(client, two_tenants):
    seller_a_id, _, _ = two_tenants

    # Note: lax-mode-friendly values (1, "yes") are deliberately absent —
    # Pydantic v2 coerces them to True, so they are valid requests, not 422s.
    for payload in ({}, {"is_available": "maybe"}, {"is_available": [True]}):
        response = client.patch(
            "/api/v1/seller/listings/A_LIVE/availability",
            json=payload,
            headers=auth(seller_a_id),
        )
        assert response.status_code == 422, payload


def test_patch_cross_tenant_and_nonexistent_share_the_same_404(client, two_tenants):
    """B's listing toggled with A's token is the exact same 404 as a
    nonexistent token — never 403, never B's data (§3.14)."""
    seller_a_id, seller_b_id, _ = two_tenants

    cross_tenant = client.patch(
        "/api/v1/seller/listings/B_ONLY/availability",
        json={"is_available": False},
        headers=auth(seller_a_id),
    )
    nonexistent = client.patch(
        "/api/v1/seller/listings/NOPE1234/availability",
        json={"is_available": False},
        headers=auth(seller_a_id),
    )

    assert cross_tenant.status_code == 404
    assert nonexistent.status_code == 404
    assert cross_tenant.json() == nonexistent.json()

    # B's row is untouched.
    body_b = client.get("/api/v1/seller/listings", headers=auth(seller_b_id)).json()
    assert body_b["items"][0]["is_available"] is True
