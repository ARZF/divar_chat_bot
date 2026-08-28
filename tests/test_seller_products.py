"""Tenant-scoped product read API tests (Phase 3 step 15).

Covers the JWT gate (401 paths), two-tenant isolation on both list and detail,
normalized search semantics, pagination bounds/ordering, and the non-leaking
404 rule (cross-tenant is indistinguishable from nonexistent, §3.14).
"""

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
from models.product import Product


def make_access_token(client_id: int) -> str:
    payload = {
        "client_id": client_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def auth(client_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_access_token(client_id)}"}


def ts(day: int, hour: int = 0) -> datetime:
    """Deterministic tz-aware updated_at seeds so ordering is exact."""
    return datetime(2026, 8, day, hour, tzinfo=timezone.utc)


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
                c, tables=[Client.__table__, Product.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def two_tenants(session_factory):
    """Seller A with 5 products; seller B with 1 product that shares a
    normalized_name with one of A's (UNIQUE is per-tenant). A's responses must
    never contain or count B's row.

    A's products by expected list order (updated_at DESC, id DESC):
      1. کیف گوشی            (08-25 09:00, highest id — tie-break over لپ تاپ ایسوس)
      2. لپ تاپ ایسوس        (08-25 09:00)
      3. گوشی سامسونگ گلکسی  (08-20 10:00)
      4. گوشی آیفون ۱۲       (08-10 12:00)
      5. old_model           (08-01 08:00)
    """
    async with session_factory() as db:
        seller_a = Client(phone_number="09120000001")
        seller_b = Client(phone_number="09120000002")
        db.add_all([seller_a, seller_b])
        await db.flush()

        db.add_all([
            Product(
                client_id=seller_a.id,
                item_name="گوشی سامسونگ گلکسی",
                normalized_name="samsung galaxy گوشی",
                price=25_000_000,
                updated_at=ts(20, 10),
            ),
            Product(
                client_id=seller_a.id,
                item_name="لپ تاپ ایسوس",
                normalized_name="لپتاپ asus",
                price=32_000_000,
                updated_at=ts(25, 9),
            ),
            Product(
                client_id=seller_a.id,
                item_name="کیف گوشی",
                normalized_name="کیف گوشی",
                price=150_000,
                updated_at=ts(25, 9),
            ),
            Product(
                client_id=seller_a.id,
                item_name="گوشی آیفون ۱۲",
                normalized_name="گوشی iphone 12",
                price=41_000_000,
                updated_at=ts(10, 12),
            ),
            Product(
                client_id=seller_a.id,
                item_name="old_model",
                normalized_name="old_model",
                price=1_000,
                updated_at=ts(1, 8),
            ),
            # B's row: same normalized_name as A's "samsung galaxy گوشی".
            Product(
                client_id=seller_b.id,
                item_name="گوشی سامسونگ گلکسی",
                normalized_name="samsung galaxy گوشی",
                price=99_999_999,
                updated_at=ts(26, 6),
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


def product_ids(body: dict) -> list[int]:
    return [item["id"] for item in body["items"]]


# --------------------------------------------------------------------------------------
# JWT gate
# --------------------------------------------------------------------------------------

def test_list_requires_authorization_header(client):
    assert client.get("/api/v1/seller/products").status_code == 401


def test_list_rejects_invalid_token(client):
    response = client.get(
        "/api/v1/seller/products",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


def test_detail_requires_authorization_header(client):
    assert client.get("/api/v1/seller/products/1").status_code == 401


def test_detail_rejects_invalid_token(client):
    response = client.get(
        "/api/v1/seller/products/1",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------------------
# List: defaults, ordering, response shape
# --------------------------------------------------------------------------------------

def test_list_defaults_ordering_and_metadata(client, two_tenants):
    seller_a_id, _ = two_tenants

    response = client.get("/api/v1/seller/products", headers=auth(seller_a_id))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "page", "page_size", "total", "page_count"}
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 5
    assert body["page_count"] == 1
    # updated_at DESC with id DESC tie-break: the two 08-25 rows come first,
    # higher id (کیف گوشی, inserted after لپ تاپ ایسوس) before lower.
    names = [item["item_name"] for item in body["items"]]
    assert names == [
        "کیف گوشی",
        "لپ تاپ ایسوس",
        "گوشی سامسونگ گلکسی",
        "گوشی آیفون ۱۲",
        "old_model",
    ]


def test_list_item_shape_exposes_no_internal_fields(client, two_tenants):
    seller_a_id, _ = two_tenants

    body = client.get("/api/v1/seller/products", headers=auth(seller_a_id)).json()

    assert len(body["items"]) == 5
    for item in body["items"]:
        assert set(item) == {"id", "item_name", "price", "updated_at"}
    by_name = {item["item_name"]: item for item in body["items"]}
    assert by_name["گوشی سامسونگ گلکسی"]["price"] == 25_000_000


# --------------------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------------------

def test_list_pagination_pages_and_metadata(client, two_tenants):
    seller_a_id, _ = two_tenants

    page1 = client.get(
        "/api/v1/seller/products",
        params={"page": 1, "page_size": 2},
        headers=auth(seller_a_id),
    )
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert body1["total"] == 5
    assert body1["page_count"] == 3

    page2 = client.get(
        "/api/v1/seller/products",
        params={"page": 2, "page_size": 2},
        headers=auth(seller_a_id),
    ).json()
    assert len(page2["items"]) == 2
    assert page2["page"] == 2

    # Pages do not overlap and ordering continues across the boundary:
    # page 1 is the two 08-25 rows, page 2 opens with the 08-20 row.
    assert set(product_ids(body1)).isdisjoint(product_ids(page2))
    assert page2["items"][0]["item_name"] == "گوشی سامسونگ گلکسی"

    page3 = client.get(
        "/api/v1/seller/products",
        params={"page": 3, "page_size": 2},
        headers=auth(seller_a_id),
    ).json()
    assert len(page3["items"]) == 1

    page4 = client.get(
        "/api/v1/seller/products",
        params={"page": 4, "page_size": 2},
        headers=auth(seller_a_id),
    ).json()
    assert page4["items"] == []
    assert page4["total"] == 5


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": -1},
        {"page_size": 0},
        {"page_size": 101},
        {"page_size": -5},
    ],
)
def test_list_rejects_out_of_bounds_pagination(client, two_tenants, params):
    """Over-max page_size is rejected with 422, never silently clamped."""
    seller_a_id, _ = two_tenants

    response = client.get(
        "/api/v1/seller/products",
        params=params,
        headers=auth(seller_a_id),
    )
    assert response.status_code == 422


def test_list_page_size_cap_allows_max_of_100(client, two_tenants):
    seller_a_id, _ = two_tenants

    response = client.get(
        "/api/v1/seller/products",
        params={"page_size": 100},
        headers=auth(seller_a_id),
    )
    assert response.status_code == 200
    assert response.json()["page_size"] == 100


# --------------------------------------------------------------------------------------
# Normalized search
# --------------------------------------------------------------------------------------

def test_list_search_normalizes_brand_and_matches_normalized_name(client, two_tenants):
    seller_a_id, _ = two_tenants

    # Persian brand word -> "samsung" via the shared synonym map.
    for q in ("سامسونگ", "SAMSUNG", "  سامسونگ  "):
        body = client.get(
            "/api/v1/seller/products", params={"q": q}, headers=auth(seller_a_id)
        ).json()
        assert [i["item_name"] for i in body["items"]] == ["گوشی سامسونگ گلکسی"]
        assert body["total"] == 1
        assert body["page_count"] == 1


def test_list_search_applies_word_synonyms(client, two_tenants):
    seller_a_id, _ = two_tenants

    # "موبایل" normalizes to "گوشی" — substring-matches every normalized_name
    # containing "گوشی" (کیف گوشی, samsung galaxy گوشی, گوشی iphone 12).
    body = client.get(
        "/api/v1/seller/products", params={"q": "موبایل"}, headers=auth(seller_a_id)
    ).json()
    assert sorted(i["item_name"] for i in body["items"]) == [
        "کیف گوشی",
        "گوشی آیفون ۱۲",
        "گوشی سامسونگ گلکسی",
    ]
    assert body["total"] == 3


def test_list_search_normalizes_phrase_synonyms(client, two_tenants):
    seller_a_id, _ = two_tenants

    # "نوتبوک" normalizes to "لپتاپ" — substring-matches "لپتاپ asus".
    body = client.get(
        "/api/v1/seller/products", params={"q": "نوتبوک"}, headers=auth(seller_a_id)
    ).json()
    assert [i["item_name"] for i in body["items"]] == ["لپ تاپ ایسوس"]


def test_list_search_with_no_match_returns_empty_page_metadata(client, two_tenants):
    seller_a_id, _ = two_tenants

    body = client.get(
        "/api/v1/seller/products", params={"q": "پرینتر"}, headers=auth(seller_a_id)
    ).json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page_count"] == 0


def test_list_search_escapes_like_wildcards(client, two_tenants):
    """A `%` or `_` in q must be matched literally, not as a SQL wildcard."""
    seller_a_id, _ = two_tenants

    for q in ("%", "old_model", "%_"):
        body = client.get(
            "/api/v1/seller/products", params={"q": q}, headers=auth(seller_a_id)
        ).json()
        # "%" matches nothing (no product contains a literal %); "old_model"
        # matches only itself, not e.g. "oldXmodel" via the _ wildcard.
        expected = 0 if q != "old_model" else 1
        assert body["total"] == expected, q


def test_list_search_is_tenant_scoped(client, two_tenants):
    """B's row shares a normalized_name with A's, but A's search only sees A's."""
    seller_a_id, seller_b_id = two_tenants

    body_a = client.get(
        "/api/v1/seller/products", params={"q": "سامسونگ"}, headers=auth(seller_a_id)
    ).json()
    assert body_a["total"] == 1
    assert body_a["items"][0]["price"] == 25_000_000

    body_b = client.get(
        "/api/v1/seller/products", params={"q": "سامسونگ"}, headers=auth(seller_b_id)
    ).json()
    assert body_b["total"] == 1
    assert body_b["items"][0]["price"] == 99_999_999


def test_list_whitespace_only_q_returns_all(client, two_tenants):
    seller_a_id, _ = two_tenants

    body = client.get(
        "/api/v1/seller/products", params={"q": "   "}, headers=auth(seller_a_id)
    ).json()
    assert body["total"] == 5


# --------------------------------------------------------------------------------------
# Tenant isolation
# --------------------------------------------------------------------------------------

def test_list_is_scoped_to_the_jwt_client(client, two_tenants):
    seller_a_id, seller_b_id = two_tenants

    body_a = client.get("/api/v1/seller/products", headers=auth(seller_a_id)).json()
    assert body_a["total"] == 5

    body_b = client.get("/api/v1/seller/products", headers=auth(seller_b_id)).json()
    assert body_b["total"] == 1
    assert body_b["items"][0]["item_name"] == "گوشی سامسونگ گلکسی"


def test_list_ignores_client_id_from_browser(client, two_tenants):
    """A `client_id` query param cannot steer the listing to another tenant."""
    seller_a_id, seller_b_id = two_tenants

    response = client.get(
        "/api/v1/seller/products",
        params={"client_id": str(seller_b_id)},
        headers=auth(seller_a_id),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 5


# --------------------------------------------------------------------------------------
# Detail
# --------------------------------------------------------------------------------------

def test_detail_returns_own_product(client, two_tenants):
    seller_a_id, _ = two_tenants
    listing = client.get("/api/v1/seller/products", headers=auth(seller_a_id)).json()
    target = next(i for i in listing["items"] if i["item_name"] == "گوشی آیفون ۱۲")

    response = client.get(
        f"/api/v1/seller/products/{target['id']}", headers=auth(seller_a_id)
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": target["id"],
        "item_name": "گوشی آیفون ۱۲",
        "price": 41_000_000,
        "updated_at": target["updated_at"],
    }
    # No internal fields leak.
    assert set(response.json()) == {"id", "item_name", "price", "updated_at"}


def test_detail_cross_tenant_404_is_indistinguishable_from_nonexistent(client, two_tenants):
    """B's product fetched with A's token returns the exact same 404 as a
    nonexistent id — never 403, never B's data (§3.14 non-leaking rule)."""
    seller_a_id, seller_b_id = two_tenants
    listing_b = client.get("/api/v1/seller/products", headers=auth(seller_b_id)).json()
    foreign_id = listing_b["items"][0]["id"]

    cross_tenant = client.get(
        f"/api/v1/seller/products/{foreign_id}", headers=auth(seller_a_id)
    )
    nonexistent = client.get(
        "/api/v1/seller/products/999999", headers=auth(seller_a_id)
    )

    assert cross_tenant.status_code == 404
    assert nonexistent.status_code == 404
    assert cross_tenant.json() == nonexistent.json()
    assert "normalized_name" not in cross_tenant.json()


def test_list_for_unknown_client_returns_honest_empty_list(client):
    """A syntactically valid JWT for an unknown client (e.g. deleted seller)
    lists zero products — no rows exist for that tenant, nothing fabricated."""
    body = client.get("/api/v1/seller/products", headers=auth(99999)).json()
    assert body == {
        "items": [],
        "page": 1,
        "page_size": 20,
        "total": 0,
        "page_count": 0,
    }
