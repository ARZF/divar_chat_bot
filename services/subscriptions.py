# subscriptions.py
"""Central subscription service (§3.10, step 28) — the single owner of
"does this seller have a subscription, and what is it?".

Architecture (maintainer-approved 2026-09-04):

    Plan (catalogue, config-defined)
      ↓
    Subscription (one row per client)
      ↓
    Usage derived later from post_conversations / post_messages (step 27)

Nothing here enforces quotas, processes payment, or counts usage — this is
the read/ownership layer that later steps call, so the "is this seller
entitled?" logic exists exactly once.

Assignment is LAZY and IDEMPOTENT: no startup seeding (main.py carries no
subscription logic), no eager creation at client signup — the first caller
that genuinely needs a seller's subscription invokes
`ensure_default_subscription`, which returns the existing row or creates
exactly one default Free Trial subscription. One trial per client is
guaranteed by `uq_subscriptions_client_id` (a lost insert race is re-read,
never duplicated). Existing clients are never backfilled in bulk; they get
their trial the same lazy way, on first need.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.enums import SubscriptionStatus
from models.plan import Plan
from models.subscription import Subscription

logger = logging.getLogger("subscriptions")


# ---------------------------------------------------------------------------
# Plan catalogue — the Free Trial definition (config is the only source)
# ---------------------------------------------------------------------------
async def get_or_create_free_trial_plan(db: AsyncSession) -> Plan:
    """Idempotently return the Free Trial Plan catalogue row, creating it
    from the central config on first need.

    Catalogue seeding, not subscription assignment: this row is the
    reusable definition every seller's trial Subscription references. The
    numbers come only from config (steps 26–27); the paid catalogue is
    deferred (step 26 payment boundary) — nothing else is ever created.
    A concurrent create losing the uq_plans_name race is fine — the row
    exists either way.
    """
    plan = (
        await db.execute(
            select(Plan).where(Plan.name == settings.FREE_TRIAL_PLAN_NAME)
        )
    ).scalar_one_or_none()
    if plan is not None:
        return plan
    try:
        plan = Plan(
            name=settings.FREE_TRIAL_PLAN_NAME,
            price=0,
            # One-time 7-day entitlement, not a recurring billing period.
            billing_period=None,
            duration_days=settings.FREE_TRIAL_DURATION_DAYS,
            conversation_limit=settings.FREE_TRIAL_BUYER_CONVERSATION_LIMIT,
            message_limit=settings.FREE_TRIAL_BUYER_MESSAGE_LIMIT,
            # No listing/product limits in the trial (step 26) — those
            # counts are reportable metrics only (step 27).
            listing_limit=None,
            product_limit=None,
            is_active=True,
        )
        db.add(plan)
        await db.flush()
        return plan
    except IntegrityError:
        # Lost the unique-name race; the winner's row is the catalogue row.
        await db.rollback()
        return (
            await db.execute(
                select(Plan).where(Plan.name == settings.FREE_TRIAL_PLAN_NAME)
            )
        ).scalar_one()


# ---------------------------------------------------------------------------
# Seller subscription — lookup, lazy default assignment, expiry
# ---------------------------------------------------------------------------
async def get_subscription(
    db: AsyncSession, client_id: int
) -> Subscription | None:
    """The seller's current subscription row, or None if they have never
    been assigned one. Pure read — no default assignment."""
    return (
        await db.execute(
            select(Subscription).where(Subscription.client_id == client_id)
        )
    ).scalar_one_or_none()


async def ensure_default_subscription(
    db: AsyncSession, client_id: int
) -> Subscription:
    """Return the seller's subscription, creating the default Free Trial
    exactly once when they have none.

    Idempotent: an existing row of ANY status is returned untouched — a
    seller whose trial already expired never gets a second one (step 26:
    one trial per client), and existing state is never silently changed.
    Concurrent first-calls are serialized by uq_subscriptions_client_id:
    the loser's insert raises IntegrityError and re-reads the winner's row.
    The entitlement window is the step 27 half-open interval
    [started_at, started_at + 7 × 24 h), UTC.
    """
    existing = await get_subscription(db, client_id)
    if existing is not None:
        return existing

    plan = await get_or_create_free_trial_plan(db)
    now = datetime.now(timezone.utc)
    try:
        subscription = Subscription(
            client_id=client_id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            started_at=now,
            expires_at=now + timedelta(days=settings.FREE_TRIAL_DURATION_DAYS),
        )
        db.add(subscription)
        await db.flush()
        return subscription
    except IntegrityError:
        # Lost the one-row-per-client race; the winner's row is authoritative.
        await db.rollback()
        return await get_subscription_or_fail(db, client_id)


async def get_subscription_or_fail(
    db: AsyncSession, client_id: int
) -> Subscription:
    """Re-read after a lost insert race — the row must exist by then."""
    subscription = await get_subscription(db, client_id)
    assert subscription is not None, (
        "subscription row vanished after IntegrityError re-read"
    )
    return subscription


def effective_subscription_status(
    subscription: Subscription, *, now: datetime | None = None
) -> SubscriptionStatus:
    """Read-time status: a row stored ACTIVE whose `expires_at` has passed
    is EXPIRED (step 27's half-open window — expired at now >= expires_at).

    Pure interpretation: the stored `status` stays the lifecycle record and
    is never written back during a read. The tzinfo guard mirrors the
    OAuth-token handling in services/post_conversation.py — SQLite reads
    datetimes back naive; Postgres (timezone=True) reads them back aware.
    """
    expires_at = subscription.expires_at
    if (
        subscription.status == SubscriptionStatus.ACTIVE
        and expires_at is not None
    ):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if (now or datetime.now(timezone.utc)) >= expires_at:
            return SubscriptionStatus.EXPIRED
    return subscription.status
