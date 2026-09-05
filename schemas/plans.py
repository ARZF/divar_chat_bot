"""Public plan and seller-subscription response schemas (§3.10, step 28).

The public plan item deliberately exposes no internal ids and no
`is_active` (the endpoint only ever lists active plans, so the flag would
be constant). `message_limit` is the buyer-generated-message limit — bot
replies and seller messages never count (step 26).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlanPublicItem(BaseModel):
    """One catalogue plan as the public pricing source may show it."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None
    price: int
    billing_period: str | None
    duration_days: int | None
    message_limit: int | None
    conversation_limit: int | None
    listing_limit: int | None
    product_limit: int | None
    features: list[str] | None


class PlansListResponse(BaseModel):
    """All currently active plans (inactive ones are never listed)."""

    items: list[PlanPublicItem]


class SubscriptionUsage(BaseModel):
    """Derived buyer usage over one subscription's entitlement window
    (step 27 contract, exposed read-only in step 29). Counts, not counters —
    `buyer_conversation_count` = window-scoped `post_conversations` rows,
    `buyer_message_count` = window-scoped committed `post_messages` rows
    with `sender_type = 'buyer'`. The window is the half-open UTC interval
    [period_start, period_end)."""

    period_start: datetime
    period_end: datetime
    buyer_conversation_count: int
    buyer_message_count: int


class SellerSubscriptionResponse(BaseModel):
    """The authenticated seller's current subscription (§3.10.5 display
    fields). `status` is the read-time *effective* status, so a stored-ACTIVE
    row whose entitlement window has elapsed is never presented as active.
    `usage` is the derived window-scoped count (step 29) — None only while
    the subscription has no entitlement window yet (PENDING)."""

    status: str
    started_at: datetime | None
    expires_at: datetime | None
    plan: PlanPublicItem
    usage: SubscriptionUsage | None
