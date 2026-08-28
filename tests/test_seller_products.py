"""Tenant-scoped product API tests (Phase 3 steps 15-17).

Covers the JWT gate (401 paths), two-tenant isolation on list/detail/mutations,
normalized search semantics, pagination bounds/ordering, the non-leaking
404 rule (cross-tenant is indistinguishable from nonexistent, §3.14), the
tenant-scoped 409 on duplicate normalized names, the lookup-cache
refresh after every successful mutation, and the tenant-scoped spreadsheet
import (§3.7.6) wrapping load_prices_to_db unchanged.
"""

from datetime import datetime, timedelta, timezone
from io import BytesIO

import jwt as pyjwt
import pandas as pd
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import services.price_lookup as price_lookup
from api.seller import update_product
from config import settings
from db.session import get_db
from main import app
from models.client import Client
from models.product import Product
from schemas.seller import ProductUpdateRequest


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

    normalized_name values are exactly normalize_text(item_name) so duplicate
    and conflict tests collide the way production rows would.
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
                normalized_name="گوشی samsung galaxy",
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
            # B's row: same normalized_name as A's "گوشی samsung galaxy".
            Product(
                client_id=seller_b.id,
                item_name="گوشی سامسونگ گلکسی",
                normalized_name="گوشی samsung galaxy",
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


@pytest.fixture(autouse=True)
def clear_lookup_cache():
    """The lookup cache is module-level state shared with the chatbot; keep
    tests independent of each other's mutations."""
    price_lookup._cache.clear()
    yield
    price_lookup._cache.clear()


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


# --------------------------------------------------------------------------------------
# Mutations (Phase 3 step 16)
# --------------------------------------------------------------------------------------

def own_product_id(client, client_id: int, item_name: str) -> int:
    listing = client.get("/api/v1/seller/products", headers=auth(client_id)).json()
    return next(i["id"] for i in listing["items"] if i["item_name"] == item_name)


def foreign_product_id(client, client_id: int) -> int:
    listing = client.get("/api/v1/seller/products", headers=auth(client_id)).json()
    return listing["items"][0]["id"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/seller/products"),
        ("PATCH", "/api/v1/seller/products/1"),
        ("DELETE", "/api/v1/seller/products/1"),
    ],
)
def test_mutations_require_authorization_header(client, method, path):
    response = client.request(method, path, json={})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/seller/products"),
        ("PATCH", "/api/v1/seller/products/1"),
        ("DELETE", "/api/v1/seller/products/1"),
    ],
)
def test_mutations_reject_invalid_token(client, method, path):
    response = client.request(
        method, path, json={}, headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


# ---- create ---------------------------------------------------------------------------

def test_create_returns_201_with_detail_shape_and_normalizes_name(client, two_tenants):
    seller_a_id, _ = two_tenants

    response = client.post(
        "/api/v1/seller/products",
        json={"item_name": "گوشی شیائومی ردمی", "price": 18_500_000},
        headers=auth(seller_a_id),
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "item_name", "price", "updated_at"}
    assert body["item_name"] == "گوشی شیائومی ردمی"
    assert body["price"] == 18_500_000
    # Server-derived normalized_name is searchable ("شیائومی" -> "xiaomi").
    search = client.get(
        "/api/v1/seller/products", params={"q": "شیائومی"}, headers=auth(seller_a_id)
    ).json()
    assert search["total"] == 1
    assert search["items"][0]["id"] == body["id"]
    assert "normalized_name" not in body


def test_create_rejects_invalid_bodies(client, two_tenants):
    seller_a_id, _ = two_tenants

    for payload in (
        {},
        {"item_name": ""},
        {"item_name": "x" * 501},
        {"price": 100},
        {"item_name": "گوشی", "price": -1},
        {"item_name": "گوشی"},
    ):
        response = client.post(
            "/api/v1/seller/products", json=payload, headers=auth(seller_a_id)
        )
        assert response.status_code == 422, payload


def test_create_ignores_client_id_and_normalized_name_in_body(client, two_tenants):
    """Extra body fields cannot steer tenant or the derived normalization."""
    seller_a_id, seller_b_id = two_tenants

    response = client.post(
        "/api/v1/seller/products",
        json={
            "item_name": "تبلت لنوو",
            "price": 9_000_000,
            "client_id": seller_b_id,
            "normalized_name": "fabricated",
        },
        headers=auth(seller_a_id),
    )

    assert response.status_code == 201
    # Belongs to A (visible in A's list), never to B.
    listing_a = client.get("/api/v1/seller/products", headers=auth(seller_a_id)).json()
    assert any(i["item_name"] == "تبلت لنوو" for i in listing_a["items"])
    listing_b = client.get("/api/v1/seller/products", headers=auth(seller_b_id)).json()
    assert not any(i["item_name"] == "تبلت لنوو" for i in listing_b["items"])
    # The fabricated normalized_name was ignored: search by the real
    # normalization ("لنوو" -> "lenovo") finds it, "fabricated" does not.
    assert client.get(
        "/api/v1/seller/products", params={"q": "لنوو"}, headers=auth(seller_a_id)
    ).json()["total"] == 1
    assert client.get(
        "/api/v1/seller/products", params={"q": "fabricated"}, headers=auth(seller_a_id)
    ).json()["total"] == 0


def test_create_duplicate_normalized_name_in_same_tenant_returns_409(client, two_tenants):
    seller_a_id, _ = two_tenants
    existing_id = own_product_id(client, seller_a_id, "گوشی سامسونگ گلکسی")

    # Different display name, same normalization: "موبایل" is a word synonym
    # of "گوشی", so this normalizes to the stored "گوشی samsung galaxy".
    response = client.post(
        "/api/v1/seller/products",
        json={"item_name": "موبایل سامسونگ گلکسی", "price": 1},
        headers=auth(seller_a_id),
    )

    assert response.status_code == 409
    # The conflicting product's id must not leak.
    assert str(existing_id) not in response.text
    assert response.json() == {"detail": "A product with this name already exists in your catalog"}


def test_create_same_normalized_name_in_other_tenant_succeeds(client, two_tenants):
    """UNIQUE(client_id, normalized_name) is per-tenant: B may create a name
    A already owns."""
    seller_a_id, seller_b_id = two_tenants

    response = client.post(
        "/api/v1/seller/products",
        json={"item_name": "گوشی آیفون ۱۲", "price": 45_000_000},
        headers=auth(seller_b_id),
    )

    assert response.status_code == 201
    listing_b = client.get("/api/v1/seller/products", headers=auth(seller_b_id)).json()
    assert listing_b["total"] == 2


# ---- update ---------------------------------------------------------------------------

def test_patch_updates_price_and_renames_with_renormalization(client, two_tenants):
    seller_a_id, _ = two_tenants

    rename = client.patch(
        f"/api/v1/seller/products/{own_product_id(client, seller_a_id, 'کیف گوشی')}",
        json={"item_name": "کاور گوشی"},
        headers=auth(seller_a_id),
    )
    assert rename.status_code == 200
    assert rename.json()["item_name"] == "کاور گوشی"

    # Old normalized name no longer matches; the new one does.
    assert client.get(
        "/api/v1/seller/products", params={"q": "کیف"}, headers=auth(seller_a_id)
    ).json()["total"] == 0
    assert client.get(
        "/api/v1/seller/products", params={"q": "کاور"}, headers=auth(seller_a_id)
    ).json()["total"] == 1

    reprice = client.patch(
        f"/api/v1/seller/products/{rename.json()['id']}",
        json={"price": 250_000},
        headers=auth(seller_a_id),
    )
    assert reprice.status_code == 200
    assert reprice.json()["price"] == 250_000
    assert reprice.json()["item_name"] == "کاور گوشی"


@pytest.mark.asyncio
async def test_patch_updates_updated_at_but_not_created_at(session_factory, two_tenants):
    """Direct endpoint call (single event loop, shared StaticPool connection):
    a real change must touch updated_at via the model's onupdate and leave
    created_at alone."""
    seller_a_id, _ = two_tenants

    def as_utc(dt: datetime) -> datetime:
        # SQLite returns naive datetimes while the model's onupdate produces
        # tz-aware ones — normalize before comparing.
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    async with session_factory() as db:
        row = (
            await db.execute(
                select(Product).where(
                    Product.client_id == seller_a_id,
                    Product.normalized_name == "کیف گوشی",
                )
            )
        ).scalar_one()
        original_created_at, original_updated_at = row.created_at, row.updated_at

        result = await update_product(
            row.id,
            ProductUpdateRequest(price=999_999),
            client_id=seller_a_id,
            db=db,
        )

        assert result.price == 999_999

        fresh = (
            await db.execute(select(Product).where(Product.id == row.id))
        ).scalar_one()
        assert as_utc(fresh.created_at) == as_utc(original_created_at)
        assert as_utc(fresh.updated_at) > as_utc(original_updated_at)


def test_patch_rename_to_own_current_name_does_not_409(client, two_tenants):
    seller_a_id, _ = two_tenants
    product_id = own_product_id(client, seller_a_id, "کیف گوشی")

    # Identical item_name, and a synonym that normalizes to the same key.
    for new_name in ("کیف گوشی", "کیف موبایل"):
        response = client.patch(
            f"/api/v1/seller/products/{product_id}",
            json={"item_name": new_name},
            headers=auth(seller_a_id),
        )
        assert response.status_code == 200, new_name


def test_patch_rename_conflict_returns_409_without_conflicting_id(client, two_tenants):
    seller_a_id, _ = two_tenants
    product_id = own_product_id(client, seller_a_id, "کیف گوشی")
    conflicting_id = own_product_id(client, seller_a_id, "گوشی سامسونگ گلکسی")

    response = client.patch(
        f"/api/v1/seller/products/{product_id}",
        json={"item_name": "گوشی سامسونگ گلکسی"},
        headers=auth(seller_a_id),
    )

    assert response.status_code == 409
    assert str(conflicting_id) not in response.text
    assert str(product_id) not in response.text


def test_patch_requires_at_least_one_field(client, two_tenants):
    seller_a_id, _ = two_tenants

    response = client.patch(
        f"/api/v1/seller/products/{own_product_id(client, seller_a_id, 'کیف گوشی')}",
        json={},
        headers=auth(seller_a_id),
    )
    assert response.status_code == 422


def test_patch_rejects_invalid_values(client, two_tenants):
    seller_a_id, _ = two_tenants
    product_id = own_product_id(client, seller_a_id, "کیف گوشی")

    for payload in ({"item_name": ""}, {"item_name": "x" * 501}, {"price": -1}):
        response = client.patch(
            f"/api/v1/seller/products/{product_id}",
            json=payload,
            headers=auth(seller_a_id),
        )
        assert response.status_code == 422, payload


def test_patch_cross_tenant_and_nonexistent_share_the_same_404(client, two_tenants):
    seller_a_id, seller_b_id = two_tenants
    foreign_id = foreign_product_id(client, seller_b_id)

    cross_tenant = client.patch(
        f"/api/v1/seller/products/{foreign_id}",
        json={"price": 1},
        headers=auth(seller_a_id),
    )
    nonexistent = client.patch(
        "/api/v1/seller/products/999999",
        json={"price": 1},
        headers=auth(seller_a_id),
    )

    assert cross_tenant.status_code == 404
    assert nonexistent.status_code == 404
    assert cross_tenant.json() == nonexistent.json()
    # B's row is untouched.
    listing_b = client.get("/api/v1/seller/products", headers=auth(seller_b_id)).json()
    assert listing_b["items"][0]["price"] == 99_999_999


# ---- delete ---------------------------------------------------------------------------

def test_delete_removes_product_and_returns_204_with_no_body(client, two_tenants):
    seller_a_id, _ = two_tenants
    product_id = own_product_id(client, seller_a_id, "old_model")

    response = client.delete(
        f"/api/v1/seller/products/{product_id}", headers=auth(seller_a_id)
    )

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(
        f"/api/v1/seller/products/{product_id}", headers=auth(seller_a_id)
    ).status_code == 404
    # The other rows survive.
    assert client.get(
        "/api/v1/seller/products", headers=auth(seller_a_id)
    ).json()["total"] == 4
    # Deleting again is the same non-leaking 404.
    assert client.delete(
        f"/api/v1/seller/products/{product_id}", headers=auth(seller_a_id)
    ).status_code == 404


def test_delete_cross_tenant_and_nonexistent_share_the_same_404(client, two_tenants):
    seller_a_id, seller_b_id = two_tenants
    foreign_id = foreign_product_id(client, seller_b_id)

    cross_tenant = client.delete(
        f"/api/v1/seller/products/{foreign_id}", headers=auth(seller_a_id)
    )
    nonexistent = client.delete(
        "/api/v1/seller/products/999999", headers=auth(seller_a_id)
    )

    assert cross_tenant.status_code == 404
    assert nonexistent.status_code == 404
    assert cross_tenant.json() == nonexistent.json()
    # B's row still exists.
    assert client.get(
        "/api/v1/seller/products", headers=auth(seller_b_id)
    ).json()["total"] == 1


# ---- lookup-cache refresh after every successful mutation -----------------------------

def test_create_refreshes_lookup_cache_for_own_tenant_only(client, two_tenants):
    seller_a_id, seller_b_id = two_tenants

    client.post(
        "/api/v1/seller/products",
        json={"item_name": "گوشی شیائومی ردمی", "price": 18_500_000},
        headers=auth(seller_a_id),
    )

    # Chatbot-style lookup sees the new row immediately, without a restart.
    assert price_lookup.get_all_matching_prices(seller_a_id, "شیائومی") == [
        ("گوشی شیائومی ردمی", 18_500_000)
    ]
    # The cache entry is per-tenant: B's lookup does not see A's new product.
    assert price_lookup.get_all_matching_prices(seller_b_id, "شیائومی") == []


def test_update_refreshes_lookup_cache(client, two_tenants):
    seller_a_id, _ = two_tenants

    client.patch(
        f"/api/v1/seller/products/{own_product_id(client, seller_a_id, 'کیف گوشی')}",
        json={"item_name": "کاور گوشی", "price": 250_000},
        headers=auth(seller_a_id),
    )

    assert price_lookup.get_all_matching_prices(seller_a_id, "کاور گوشی") == [
        ("کاور گوشی", 250_000)
    ]
    assert price_lookup.get_all_matching_prices(seller_a_id, "کیف گوشی") == []


def test_delete_refreshes_lookup_cache(client, two_tenants):
    seller_a_id, _ = two_tenants

    client.delete(
        f"/api/v1/seller/products/{own_product_id(client, seller_a_id, 'old_model')}",
        headers=auth(seller_a_id),
    )

    assert price_lookup.get_all_matching_prices(seller_a_id, "old_model") == []


def test_failed_mutation_leaves_cache_and_db_unchanged(client, two_tenants):
    """A 409 create must not leave a half-written row or a stale cache entry:
    first warm the cache with a successful create, then attempt the duplicate."""
    seller_a_id, _ = two_tenants

    created = client.post(
        "/api/v1/seller/products",
        json={"item_name": "تبلت لنوو", "price": 9_000_000},
        headers=auth(seller_a_id),
    )
    assert created.status_code == 201

    duplicate = client.post(
        "/api/v1/seller/products",
        json={"item_name": "تبلت لنوو", "price": 1},
        headers=auth(seller_a_id),
    )
    assert duplicate.status_code == 409

    listing = client.get(
        "/api/v1/seller/products", headers=auth(seller_a_id)
    ).json()
    assert listing["total"] == 6
    # The cache still holds exactly one entry for that name — the original
    # price, not the duplicate's.
    assert price_lookup.get_all_matching_prices(seller_a_id, "تبلت لنوو") == [
        ("تبلت لنوو", 9_000_000)
    ]


# --------------------------------------------------------------------------------------
# Spreadsheet import (Phase 3 step 17) — thin wrapper over load_prices_to_db
# --------------------------------------------------------------------------------------

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx_bytes(columns: dict[str, list]) -> bytes:
    """Build a real .xlsx file with the given columns, e.g.
    {"product": ["گوشی"], "price": [100]}. Values may include None (NaN price)."""
    df = pd.DataFrame(columns)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    return buffer.getvalue()


def upload(client, token: int, filename: str, content: bytes):
    return client.post(
        "/api/v1/seller/products/import",
        files={"file": (filename, content, XLSX_MIME)},
        headers=auth(token),
    )


def test_import_requires_authorization_header(client):
    response = client.post(
        "/api/v1/seller/products/import",
        files={"file": ("prices.xlsx", b"ignored", XLSX_MIME)},
    )
    assert response.status_code == 401


def test_import_rejects_invalid_token(client):
    response = client.post(
        "/api/v1/seller/products/import",
        files={"file": ("prices.xlsx", b"ignored", XLSX_MIME)},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


def test_import_rejects_non_xlsx_filename(client, two_tenants):
    seller_a_id, _ = two_tenants

    for filename in ("prices.csv", "prices.xls", "prices", "prices.XLSX.bak"):
        response = upload(client, seller_a_id, filename, b"whatever")
        assert response.status_code == 400, filename


def test_import_rejects_oversized_file_with_413(client, two_tenants):
    """One byte over the 5 MiB cap → 413, checked before any parsing."""
    seller_a_id, _ = two_tenants

    response = upload(
        client,
        seller_a_id,
        "prices.xlsx",
        b"x" * (5 * 1024 * 1024 + 1),
    )
    assert response.status_code == 413

    # At exactly the cap the size check passes (parsing then fails on the
    # garbage bytes with 400, not 413/500 — proving the boundary).
    boundary = upload(client, seller_a_id, "prices.xlsx", b"x" * (5 * 1024 * 1024))
    assert boundary.status_code == 400


def test_import_rejects_corrupt_xlsx_bytes_with_400_not_500(client, two_tenants):
    seller_a_id, _ = two_tenants

    response = upload(client, seller_a_id, "prices.xlsx", b"not a zip file at all")
    assert response.status_code == 400
    assert "readable" in response.json()["detail"]


def test_import_rejects_missing_or_misnamed_columns_with_400(client, two_tenants):
    """_parse_df's AttributeError path (surfacing as ValueError from
    load_prices_to_db) must be a 400, never a 500."""
    seller_a_id, _ = two_tenants

    response = upload(
        client,
        seller_a_id,
        "prices.xlsx",
        xlsx_bytes({"name": ["گوشی"], "cost": [100]}),
    )
    assert response.status_code == 400
    assert "Invalid file format" in response.json()["detail"]

    # Seller's existing catalog is untouched by the failed import.
    listing = client.get("/api/v1/seller/products", headers=auth(seller_a_id)).json()
    assert listing["total"] == 5


def test_import_replaces_catalog_and_returns_rows_loaded(client, two_tenants):
    """The accepted replace-all semantics: A's 5 seeded rows are gone, exactly
    the file's 2 rows remain — verified through the step-15 list endpoint."""
    seller_a_id, _ = two_tenants

    response = upload(
        client,
        seller_a_id,
        "prices.xlsx",
        xlsx_bytes(
            {
                "product": ["تبلت لنوو", "هدفون سونی"],
                "price": [9_000_000, 2_500_000],
            }
        ),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "rows_loaded": 2}

    listing = client.get("/api/v1/seller/products", headers=auth(seller_a_id)).json()
    assert listing["total"] == 2
    by_name = {i["item_name"]: i["price"] for i in listing["items"]}
    assert by_name == {"تبلت لنوو": 9_000_000, "هدفون سونی": 2_500_000}
    # Old rows really are gone (404 on a previously-owned id, search empty).
    assert client.get(
        "/api/v1/seller/products", params={"q": "old_model"}, headers=auth(seller_a_id)
    ).json()["total"] == 0


def test_import_is_tenant_scoped_and_refreshes_only_own_cache(client, two_tenants):
    seller_a_id, seller_b_id = two_tenants

    # A imports a new catalog; B imports its own.
    response_a = upload(
        client,
        seller_a_id,
        "prices.xlsx",
        xlsx_bytes({"product": ["تبلت لنوو"], "price": [9_000_000]}),
    )
    response_b = upload(
        client,
        seller_b_id,
        "prices.xlsx",
        xlsx_bytes({"product": ["ساعت هوشمند"], "price": [4_000_000]}),
    )
    assert response_a.json()["rows_loaded"] == 1
    assert response_b.json()["rows_loaded"] == 1

    # B's DB rows were replaced by B's OWN import, never touched by A's.
    listing_b = client.get("/api/v1/seller/products", headers=auth(seller_b_id)).json()
    assert listing_b["total"] == 1
    assert listing_b["items"][0]["item_name"] == "ساعت هوشمند"
    # A's catalog contains only A's import.
    listing_a = client.get("/api/v1/seller/products", headers=auth(seller_a_id)).json()
    assert [i["item_name"] for i in listing_a["items"]] == ["تبلت لنوو"]

    # load_prices_to_db's internal refresh_lookup_cache holds per tenant:
    # each chatbot lookup sees exactly its own catalog.
    assert price_lookup.get_all_matching_prices(seller_a_id, "لنوو") == [
        ("تبلت لنوو", 9_000_000)
    ]
    assert price_lookup.get_all_matching_prices(seller_a_id, "ساعت") == []
    assert price_lookup.get_all_matching_prices(seller_b_id, "ساعت") == [
        ("ساعت هوشمند", 4_000_000)
    ]
    assert price_lookup.get_all_matching_prices(seller_b_id, "لنوو") == []


def test_import_skips_invalid_price_rows_like_admin_upload(client, two_tenants):
    """NaN and non-numeric prices are skipped by _parse_df (existing admin
    behavior); only the valid rows load."""
    seller_a_id, _ = two_tenants

    response = upload(
        client,
        seller_a_id,
        "prices.xlsx",
        xlsx_bytes(
            {
                "product": ["گوشی نوکیا", "تبلت لنوو", "هدفون سونی"],
                "price": [3_000_000, None, "cheap"],
            }
        ),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "rows_loaded": 1}
    listing = client.get("/api/v1/seller/products", headers=auth(seller_a_id)).json()
    assert [i["item_name"] for i in listing["items"]] == ["گوشی نوکیا"]


def test_import_of_empty_sheet_clears_catalog_with_zero_rows(client, two_tenants):
    """Replace-all edge: a sheet with only headers is a valid import that
    loads 0 rows and leaves the catalog empty (maintainer-approved semantics)."""
    seller_a_id, _ = two_tenants

    response = upload(
        client,
        seller_a_id,
        "prices.xlsx",
        xlsx_bytes({"product": [], "price": []}),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "rows_loaded": 0}
    assert client.get(
        "/api/v1/seller/products", headers=auth(seller_a_id)
    ).json()["total"] == 0
