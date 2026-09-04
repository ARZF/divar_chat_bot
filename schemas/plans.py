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


class SellerSubscriptionResponse(BaseModel):
    """The authenticated seller's current subscription (§3.10.5 display
    fields minus usage — derived usage lands in step 29). `status` is the
    read-time *effective* status, so a stored-ACTIVE row whose entitlement
    window has elapsed is never presented as active."""

    status: str
    started_at: datetime | None
    expires_at: datetime | None
    plan: PlanPublicItem
