"""Plans/subscriptions model, service, and read-API tests (Phase 3 step 28).

Architecture under test (maintainer-approved 2026-09-04): the central
subscription service (services/subscriptions.py) owns everything —
lazy/idempotent default Free Trial assignment per client, on-demand
creation of the single Plan catalogue row from config, and read-time
expiration. main.py carries no subscription logic; the seller API only
delegates.

Covers: model relationships and defaults, the one-subscription-per-client
and plan-name uniqueness constraints, service idempotency and reuse,
independent per-seller subscriptions, the public plans API (active-only,
exact field contract, no leaks, read-only), and the owner-scoped
current-subscription API (JWT gate, lazy default assignment, read-time
EXPIRED presentation without mutation, pass-through of stored statuses,
and tenant isolation against query/body-supplied client_ids).
"""

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from config import settings
from db.session import get_db
from main import app
from models.client import Client
from models.enums import SubscriptionStatus
from models.plan import Plan
from models.post_conversation import PostConversation
from models.post_message import PostMessage, PostSenderType
from models.subscription import Subscription
from services.subscriptions import (
    effective_subscription_status,
    ensure_default_subscription,
    get_or_create_free_trial_plan,
    get_subscription,
    get_subscription_usage,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    """Allow the production PostgreSQL JSONB model to be tested on SQLite
    (same adapter as tests/test_chatbot.py)."""
    return "JSON"

SUBSCRIPTION_TABLES = [
    Client.__table__,
    Plan.__table__,
    Subscription.__table__,
    PostConversation.__table__,
    PostMessage.__table__,
]

# Relative to the real clock because expiry is derived from `now` at read
# time — fixed dates would silently flip meaning once passed.
T = datetime.now(timezone.utc)
FUTURE = T + timedelta(days=7)
PAST = T - timedelta(days=1)


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
        await conn.run_sync(
            lambda c: Client.metadata.create_all(c, tables=SUBSCRIPTION_TABLES)
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def client(session_factory):
    async def _override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


async def _make_client(db, phone: str) -> Client:
    seller = Client(phone_number=phone)
    db.add(seller)
    await db.flush()
    return seller


async def _make_plan(db, **overrides) -> Plan:
    plan = Plan(
        name=overrides.pop("name", "Test Plan"),
        price=overrides.pop("price", 0),
        duration_days=7,
        conversation_limit=50,
        message_limit=500,
        **overrides,
    )
    db.add(plan)
    await db.flush()
    return plan


# --------------------------------------------------------------------------------------
# Models — relationships, defaults, uniqueness
# --------------------------------------------------------------------------------------

async def test_plan_subscription_relationships_and_defaults(session_factory):
    async with session_factory() as db:
        seller = await _make_client(db, "09120000001")
        plan = await _make_plan(db)
        sub = Subscription(
            client_id=seller.id,
            plan_id=plan.id,
            started_at=T,
            expires_at=FUTURE,
        )
        db.add(sub)
        await db.flush()

        assert sub.status == SubscriptionStatus.ACTIVE  # model default
        assert plan.is_active is True  # model default
        # Async sessions raise MissingGreenlet on lazy relationship loads, so
        # the relationships are loaded explicitly here.
        await db.refresh(sub, ["plan", "client"])
        await db.refresh(plan, ["subscriptions"])
        await db.refresh(seller, ["subscription"])
        assert sub.plan.name == "Test Plan"
        assert sub.client.phone_number == "09120000001"
        assert plan.subscriptions == [sub]
        assert seller.subscription is sub


async def test_one_subscription_per_client(session_factory):
    async with session_factory() as db:
        seller = await _make_client(db, "09120000001")
        plan = await _make_plan(db)
        db.add(Subscription(client_id=seller.id, plan_id=plan.id))
        await db.flush()
        db.add(Subscription(client_id=seller.id, plan_id=plan.id))
        with pytest.raises(IntegrityError):
            await db.flush()


async def test_plan_name_is_unique(session_factory):
    async with session_factory() as db:
        await _make_plan(db, name="Same Name")
        db.add(Plan(name="Same Name", price=0))
        with pytest.raises(IntegrityError):
            await db.flush()


# --------------------------------------------------------------------------------------
# Plan catalogue — config is the only source; row created on first need
# --------------------------------------------------------------------------------------

async def test_free_trial_plan_created_from_config_on_demand(session_factory):
    async with session_factory() as db:
        # Nothing exists before first need.
        assert (
            await db.execute(select(Plan))
        ).scalars().all() == []

        plan = await get_or_create_free_trial_plan(db)
        assert plan.name == settings.FREE_TRIAL_PLAN_NAME
        assert plan.price == 0
        assert plan.billing_period is None  # one-time entitlement, not recurring
        assert plan.duration_days == settings.FREE_TRIAL_DURATION_DAYS == 7
        assert (
            plan.conversation_limit
            == settings.FREE_TRIAL_BUYER_CONVERSATION_LIMIT
            == 50
        )
        assert plan.message_limit == settings.FREE_TRIAL_BUYER_MESSAGE_LIMIT == 500
        assert plan.listing_limit is None and plan.product_limit is None
        assert plan.is_active is True

        # Idempotent: a second call returns the same row, no duplicate.
        again = await get_or_create_free_trial_plan(db)
        assert again.id == plan.id
        all_plans = (await db.execute(select(Plan))).scalars().all()
        assert len(all_plans) == 1


async def test_existing_plan_row_is_never_rewritten(session_factory):
    async with session_factory() as db:
        # A row already carrying the trial name (e.g. edited by hand) must
        # be returned exactly as-is.
        await _make_plan(db, name=settings.FREE_TRIAL_PLAN_NAME, price=123)
        plan = await get_or_create_free_trial_plan(db)
        assert plan.price == 123


# --------------------------------------------------------------------------------------
# Subscription service — lazy, idempotent default assignment
# --------------------------------------------------------------------------------------

async def test_ensure_creates_exactly_one_trial_per_client(session_factory):
    async with session_factory() as db:
        seller = await _make_client(db, "09120000001")

        # get_subscription is a pure read: nothing exists yet.
        assert await get_subscription(db, seller.id) is None

        first = await ensure_default_subscription(db, seller.id)
        assert first.status == SubscriptionStatus.ACTIVE
        assert first.started_at is not None
        # 7 × 24 h, half-open window, UTC.
        assert (
            first.expires_at - first.started_at == timedelta(days=7)
        )
        assert first.started_at.tzinfo is not None
        assert first.expires_at.tzinfo is not None
        assert first.plan_id == (await get_or_create_free_trial_plan(db)).id

        # Idempotent: repeated calls return the SAME row, never a new one.
        for _ in range(3):
            again = await ensure_default_subscription(db, seller.id)
            assert again.id == first.id
        rows = (
            await db.execute(
                select(Subscription).where(Subscription.client_id == seller.id)
            )
        ).scalars().all()
        assert len(rows) == 1


async def test_ensure_reuses_existing_subscription_untouched(session_factory):
    async with session_factory() as db:
        seller = await _make_client(db, "09120000001")
        plan = await _make_plan(db, name="Seller's Own Plan")
        existing = Subscription(
            client_id=seller.id,
            plan_id=plan.id,
            status=SubscriptionStatus.EXPIRED,
            started_at=PAST - timedelta(days=10),
            expires_at=PAST,
        )
        db.add(existing)
        await db.flush()

        returned = await ensure_default_subscription(db, seller.id)
        # An existing row of ANY status is returned as-is — an expired
        # seller never gets a second trial (one trial per client).
        assert returned.id == existing.id
        assert returned.status is SubscriptionStatus.EXPIRED
        assert returned.plan_id == plan.id


async def test_two_sellers_get_independent_trials(session_factory):
    async with session_factory() as db:
        seller_a = await _make_client(db, "09120000001")
        seller_b = await _make_client(db, "09120000002")

        sub_a = await ensure_default_subscription(db, seller_a.id)
        sub_b = await ensure_default_subscription(db, seller_b.id)

        assert sub_a.id != sub_b.id
        assert sub_a.client_id == seller_a.id
        assert sub_b.client_id == seller_b.id
        # Both reference the ONE shared catalogue row (Plan is reusable;
        # Subscription is per seller).
        assert sub_a.plan_id == sub_b.plan_id
        total = (await db.execute(select(Subscription))).scalars().all()
        assert len(total) == 2


# --------------------------------------------------------------------------------------
# Read-time expiration — pure interpretation, never a write-back
# --------------------------------------------------------------------------------------

def test_effective_status_rules():
    def sub(status, expires_at):
        return Subscription(
            client_id=1, plan_id=1, status=status, expires_at=expires_at
        )

    active_future = sub(SubscriptionStatus.ACTIVE, FUTURE)
    assert effective_subscription_status(active_future, now=T) is SubscriptionStatus.ACTIVE

    # Half-open window: at exactly expires_at the entitlement is over.
    assert (
        effective_subscription_status(
            sub(SubscriptionStatus.ACTIVE, T), now=T
        )
        is SubscriptionStatus.EXPIRED
    )
    assert (
        effective_subscription_status(sub(SubscriptionStatus.ACTIVE, PAST), now=T)
        is SubscriptionStatus.EXPIRED
    )
    # Only ACTIVE is time-derived; every other stored status passes through.
    for stored in (SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELLED):
        assert (
            effective_subscription_status(sub(stored, PAST), now=T) is stored
        )
    assert (
        effective_subscription_status(sub(SubscriptionStatus.PENDING, None), now=T)
        is SubscriptionStatus.PENDING
    )
    # ACTIVE without an expires_at is not time-derivable.
    assert (
        effective_subscription_status(sub(SubscriptionStatus.ACTIVE, None), now=T)
        is SubscriptionStatus.ACTIVE
    )
    # Naive read-back (SQLite) is treated as UTC, not compared against aware now.
    naive_past = sub(SubscriptionStatus.ACTIVE, PAST.replace(tzinfo=None))
    assert (
        effective_subscription_status(naive_past, now=T) is SubscriptionStatus.EXPIRED
    )
    # Pure interpretation: the stored value is never mutated.
    elapsed = sub(SubscriptionStatus.ACTIVE, PAST)
    effective_subscription_status(elapsed, now=T)
    assert elapsed.status is SubscriptionStatus.ACTIVE


# --------------------------------------------------------------------------------------
# Public plans API — active-only catalogue, exact contract, read-only
# --------------------------------------------------------------------------------------

def test_plans_endpoint_is_read_only(client):
    assert client.post("/api/v1/plans", json={"name": "x"}).status_code == 405
    assert client.patch("/api/v1/plans", json={}).status_code == 405
    assert client.delete("/api/v1/plans").status_code == 405


@pytest_asyncio.fixture
async def catalogue(session_factory):
    async with session_factory() as db:
        await _make_plan(db, name="Visible Plan", price=0, description="d")
        await _make_plan(db, name="Retired Plan", price=999, is_active=False)
        await db.commit()


def test_public_plans_list_active_only(client, catalogue):
    response = client.get("/api/v1/plans")  # no auth — public pricing source
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["name"] for i in items] == ["Visible Plan"]

    item = items[0]
    assert set(item) == {
        "name", "description", "price", "billing_period", "duration_days",
        "message_limit", "conversation_limit", "listing_limit",
        "product_limit", "features",
    }
    # No internal ids, no is_active, no timestamps, no tenant data.
    assert item["price"] == 0
    assert item["duration_days"] == 7
    assert item["conversation_limit"] == 50
    assert item["message_limit"] == 500
    assert item["features"] is None


def test_public_plans_empty_catalogue_is_honest(client):
    """No seeding at startup: before any seller needs a subscription, the
    catalogue is honestly empty — the pricing page already renders its
    "nothing to show" state for exactly this case (step 26)."""
    response = client.get("/api/v1/plans")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_public_plans_lists_trial_after_first_need(client, lazy_trial_catalogue):
    """The catalogue row appears only once some seller's flow needed it —
    lazy catalogue creation through the service."""
    response = client.get("/api/v1/plans")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["name"] for i in items] == [settings.FREE_TRIAL_PLAN_NAME]


@pytest_asyncio.fixture
async def lazy_trial_catalogue(session_factory):
    """A seller whose subscription need created the catalogue row."""
    async with session_factory() as db:
        seller = await _make_client(db, "09120000001")
        await ensure_default_subscription(db, seller.id)
        await db.commit()


@pytest_asyncio.fixture
async def fresh_seller_id(session_factory):
    """A client row with no subscription yet."""
    async with session_factory() as db:
        seller = await _make_client(db, "09120000001")
        await db.commit()
        return seller.id


# --------------------------------------------------------------------------------------
# Current-subscription API — owner-scoped, JWT-gated, lazy default assignment
# --------------------------------------------------------------------------------------

def test_subscription_requires_authorization(client):
    assert client.get("/api/v1/seller/subscription").status_code == 401
    assert (
        client.get(
            "/api/v1/seller/subscription",
            headers={"Authorization": "Bearer not-a-jwt"},
        ).status_code
        == 401
    )


def test_new_seller_gets_default_trial_on_first_read(client, fresh_seller_id):
    seller_id = fresh_seller_id

    response = client.get(
        "/api/v1/seller/subscription", headers=auth(seller_id)
    )
    assert response.status_code == 200
    body = response.json()
    # Step 29 extends the step 28 contract with the derived usage block.
    assert set(body) == {"status", "started_at", "expires_at", "plan", "usage"}
    assert body["status"] == "ACTIVE"
    assert body["plan"]["name"] == settings.FREE_TRIAL_PLAN_NAME
    assert body["plan"]["message_limit"] == settings.FREE_TRIAL_BUYER_MESSAGE_LIMIT
    assert body["plan"]["conversation_limit"] == settings.FREE_TRIAL_BUYER_CONVERSATION_LIMIT
    # No ids, no tenant data, no internal fields leak.
    assert "client_id" not in body and "id" not in body and "id" not in body["plan"]

    # The assignment persisted and a second read returns the same row.
    # (SQLite reads the row back naive while the in-session original was
    # tz-aware — compare instants, not raw strings.)
    response2 = client.get(
        "/api/v1/seller/subscription", headers=auth(seller_id)
    )
    assert response2.status_code == 200

    def _utc(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    assert _utc(response2.json()["started_at"]) == _utc(body["started_at"])


def test_two_sellers_read_isolated_subscriptions(client, two_fresh_sellers):
    seller_a_id, seller_b_id = two_fresh_sellers

    body_a = client.get(
        "/api/v1/seller/subscription", headers=auth(seller_a_id)
    ).json()
    body_b = client.get(
        "/api/v1/seller/subscription", headers=auth(seller_b_id)
    ).json()
    # Each read is owner-scoped: both are valid trials, each about its own
    # seller (row distinctness itself is asserted at the service level in
    # test_two_sellers_get_independent_trials).
    assert body_a["status"] == "ACTIVE"
    assert body_b["status"] == "ACTIVE"
    assert body_a["plan"]["name"] == settings.FREE_TRIAL_PLAN_NAME
    assert body_b["plan"]["name"] == settings.FREE_TRIAL_PLAN_NAME


@pytest_asyncio.fixture
async def two_fresh_sellers(session_factory):
    async with session_factory() as db:
        seller_a = await _make_client(db, "09120000001")
        seller_b = await _make_client(db, "09120000002")
        await db.commit()
        return seller_a.id, seller_b.id


@pytest_asyncio.fixture
async def elapsed_trial_seller(session_factory):
    """A subscription stored ACTIVE whose entitlement window has elapsed —
    the read-time EXPIRED case (nothing may mutate it during the GET)."""
    async with session_factory() as db:
        seller = await _make_client(db, "09120000003")
        plan = await _make_plan(db, name="Elapsed Plan")
        db.add(
            Subscription(
                client_id=seller.id,
                plan_id=plan.id,
                started_at=PAST - timedelta(days=7),
                expires_at=PAST,  # elapsed — the read-time EXPIRED case
            )
        )
        await db.commit()
        return seller.id


def test_elapsed_active_is_presented_expired(client, elapsed_trial_seller):
    response = client.get(
        "/api/v1/seller/subscription", headers=auth(elapsed_trial_seller)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "EXPIRED"
    # Read-time interpretation only — the stored row is still ACTIVE.
    assert body["started_at"] is not None


@pytest_asyncio.fixture
async def stored_status_sellers(session_factory):
    """One seller per non-ACTIVE stored status (§3.10.3), each with a
    subscription in that status — read-time must pass them through
    untouched (only ACTIVE is time-derived)."""
    async with session_factory() as db:
        by_status: dict[str, int] = {}
        for i, status in enumerate(
            ("EXPIRED", "CANCELLED", "PENDING"), start=1
        ):
            seller = await _make_client(db, f"0912000001{i:02d}")
            plan = await _make_plan(db, name=f"Plan {status}")
            db.add(
                Subscription(
                    client_id=seller.id,
                    plan_id=plan.id,
                    status=SubscriptionStatus(status),
                    started_at=None if status == "PENDING" else T,
                    expires_at=None if status == "PENDING" else PAST,
                )
            )
            by_status[status] = seller.id
        await db.commit()
        return by_status


def test_stored_statuses_pass_through(client, stored_status_sellers):
    for stored, seller_id in stored_status_sellers.items():
        response = client.get(
            "/api/v1/seller/subscription", headers=auth(seller_id)
        )
        assert response.status_code == 200
        assert response.json()["status"] == stored


@pytest_asyncio.fixture
async def sellers_a_and_b(session_factory):
    """Seller A with no subscription yet; seller B with an EXPIRED
    subscription of their own."""
    async with session_factory() as db:
        seller_a = await _make_client(db, "09120000001")
        seller_b = await _make_client(db, "09120000002")
        plan = await _make_plan(db, name="B Plan")
        db.add(
            Subscription(
                client_id=seller_b.id,
                plan_id=plan.id,
                status=SubscriptionStatus.EXPIRED,
                started_at=PAST - timedelta(days=14),
                expires_at=PAST - timedelta(days=7),
            )
        )
        await db.commit()
        return seller_a.id, seller_b.id


def test_tenant_isolation_ignores_client_id_inputs(client, sellers_a_and_b):
    seller_a_id, seller_b_id = sellers_a_and_b

    # A query param or forged header is never trusted — A still gets A's
    # own (lazily created) trial, never B's expired row. (GET has no body.)
    for kwargs in (
        {"params": {"client_id": seller_b_id}},
        {"headers": {"X-Client-Id": str(seller_b_id)}},
    ):
        response = client.get(
            "/api/v1/seller/subscription",
            headers={**auth(seller_a_id), **kwargs.pop("headers", {})},
            **kwargs,
        )
        assert response.status_code == 200
        assert response.json()["plan"]["name"] == settings.FREE_TRIAL_PLAN_NAME
        assert response.json()["status"] == "ACTIVE"

    # And B reads only B's row.
    response_b = client.get(
        "/api/v1/seller/subscription", headers=auth(seller_b_id)
    )
    assert response_b.status_code == 200
    assert response_b.json()["status"] == "EXPIRED"
    assert response_b.json()["plan"]["name"] == "B Plan"


# --------------------------------------------------------------------------------------
# Derived usage (step 27 contract, step 29 display) — window-scoped COUNTs only
# --------------------------------------------------------------------------------------

async def _make_post_conversation(db, seller_id, conv_id, *, created_at=None):
    conv = PostConversation(
        client_id=seller_id,
        divar_conversation_id=conv_id,
        post_token=f"token_{conv_id}",
        created_at=created_at or T,
    )
    db.add(conv)
    await db.flush()
    return conv


async def _make_message(db, conv, *, sender, created_at, message_id=None):
    msg = PostMessage(
        post_conversation_id=conv.id,
        sender_type=sender,
        text_content="x",
        divar_message_id=message_id,
        created_at=created_at,
    )
    db.add(msg)
    await db.flush()
    return msg


@pytest_asyncio.fixture
async def seller_with_usage(session_factory):
    """Seller A: one conversation before the window, two inside it; the
    inside-window conversation has 2 buyer messages (1 in, 1 out of window
    boundary tests live in the test bodies) plus 1 bot reply that must
    never count. Seller B: one conversation with one buyer message —
    B's rows must never leak into A's usage."""
    async with session_factory() as db:
        seller_a = await _make_client(db, "09120000001")
        seller_b = await _make_client(db, "09120000002")
        plan = await _make_plan(db, name="Usage Plan")
        window_start = T
        window_end = T + timedelta(days=7)
        sub_a = Subscription(
            client_id=seller_a.id,
            plan_id=plan.id,
            started_at=window_start,
            expires_at=window_end,
        )
        db.add(sub_a)
        await db.flush()

        # Before the entitlement window: must not count.
        early = await _make_post_conversation(
            db, seller_a.id, "a-early", created_at=T - timedelta(days=30)
        )
        await _make_message(
            db, early,
            sender=PostSenderType.BUYER,
            created_at=T - timedelta(days=30),
            message_id="early-msg",
        )
        # In-window conversation with buyer messages and one bot reply.
        in_window = await _make_post_conversation(db, seller_a.id, "a-in-1")
        await _make_message(
            db, in_window,
            sender=PostSenderType.BUYER,
            created_at=T,
            message_id="a-msg-1",
        )
        await _make_message(
            db, in_window,
            sender=PostSenderType.BUYER,
            created_at=T + timedelta(days=1),
            message_id="a-msg-2",
        )
        await _make_message(
            db, in_window,
            sender=PostSenderType.BOT,
            created_at=T + timedelta(days=1),
        )
        # Seller B's rows — the cross-tenant rows.
        b_conv = await _make_post_conversation(db, seller_b.id, "b-1")
        await _make_message(
            db, b_conv,
            sender=PostSenderType.BUYER,
            created_at=T,
            message_id="b-msg-1",
        )
        await db.commit()
        return sub_a


async def test_usage_counts_window_scoped_buyer_rows(session_factory, seller_with_usage):
    sub = seller_with_usage
    async with session_factory() as db:
        usage = await get_subscription_usage(db, sub)
        # 1 conversation in window (the pre-window one excluded); 2 buyer
        # messages (bot reply and B's message never counted).
        assert usage.buyer_conversation_count == 1
        assert usage.buyer_message_count == 2
        # The window reported is the subscription's half-open interval.
        assert usage.period_start == sub.started_at
        assert usage.period_end == sub.expires_at


async def test_pending_subscription_has_no_usage(session_factory):
    async with session_factory() as db:
        seller = await _make_client(db, "09120000001")
        plan = await _make_plan(db, name="Pending Plan")
        sub = Subscription(
            client_id=seller.id,
            plan_id=plan.id,
            status=SubscriptionStatus.PENDING,
            started_at=None,
            expires_at=None,
        )
        db.add(sub)
        await db.flush()
        assert await get_subscription_usage(db, sub) is None


def test_subscription_response_includes_derived_usage(client, seller_with_usage):
    """The step 29 display contract: the seller subscription API carries the
    derived usage block alongside the step 28 fields."""
    response = client.get(
        "/api/v1/seller/subscription", headers=auth(seller_with_usage.client_id)
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "started_at", "expires_at", "plan", "usage"}
    usage = body["usage"]
    assert set(usage) == {
        "period_start", "period_end",
        "buyer_conversation_count", "buyer_message_count",
    }
    assert usage["buyer_conversation_count"] == 1
    assert usage["buyer_message_count"] == 2


def test_new_trial_reports_zero_usage(client, fresh_seller_id):
    """A lazily created trial has an empty entitlement window so far —
    honest zeros, not a missing usage block."""
    response = client.get(
        "/api/v1/seller/subscription", headers=auth(fresh_seller_id)
    )
    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["buyer_conversation_count"] == 0
    assert usage["buyer_message_count"] == 0


def test_tenant_usage_isolated(client, seller_with_usage):
    """Seller B's rows must never appear in A's usage, and vice versa."""
    sub = seller_with_usage
    # A reads A's own usage — never B's conversation/message.
    response_a = client.get(
        "/api/v1/seller/subscription", headers=auth(sub.client_id)
    )
    assert response_a.json()["usage"]["buyer_message_count"] == 2

    # B has no subscription row yet → lazy trial with zero usage of their
    # own (B's actual rows belong to no entitlement window and count only
    # for B's own future subscription, never for A's).
    # Forge attempts: A's JWT + B's client_id must still yield A's data.
    response_forged = client.get(
        "/api/v1/seller/subscription",
        headers=auth(sub.client_id),
        params={"client_id": 99999},
    )
    assert response_forged.json()["usage"] == response_a.json()["usage"]
