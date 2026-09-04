"""Subscriptions table — a client's entitlement to a plan (§3.10.2, step 28).

One row per client (uq_subscriptions_client_id): the seller's *current*
subscription — what `GET /api/v1/seller/subscription` reads and what makes
"one trial per client" (step 26) hold at the row level. Granting/upgrading
is activation logic (a later step), not this read model.

Expiration is dual: the persisted `status` is the lifecycle record, but a
row stored ACTIVE whose `expires_at` has passed is presented as EXPIRED at
read time (services/subscriptions.py::effective_subscription_status) —
read-time interpretation, never a hidden GET-time mutation. Timestamps are
UTC and the entitlement window is the half-open [started_at, expires_at)
interval (step 27). `started_at`/`expires_at` are nullable because a PENDING
subscription has not started — no sentinel dates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base
from models.enums import SubscriptionStatus

if TYPE_CHECKING:
    from models.client import Client
    from models.plan import Plan


class Subscription(Base):
    __tablename__ = "subscriptions"

    __table_args__ = (
        # One subscription record per client — the "current subscription"
        # is a single row; the unique constraint is its index.
        UniqueConstraint("client_id", name="uq_subscriptions_client_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id"),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(
            SubscriptionStatus,
            name="subscription_status_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=SubscriptionStatus.ACTIVE,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    client: Mapped[Client] = relationship(back_populates="subscription")
    plan: Mapped[Plan] = relationship(back_populates="subscriptions")
