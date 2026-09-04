"""Plans table — the seller package catalogue (§3.10.1, step 28).

Read/configuration data only: nothing here activates a plan, charges
anything, or enforces limits. The single catalogue row is the step 26–27
approved Free Trial (created idempotently on first need by
services/subscriptions.py::get_or_create_free_trial_plan); the paid
catalogue is deliberately deferred until the maintainer defines it.

Field notes:
* `message_limit` is the buyer-generated-message limit — bot replies and
  seller messages never count (step 26).
* `conversation_limit` and `duration_days` are not in §3.10.1's *suggested*
  list, but are required to carry the approved trial semantics (50 buyer
  conversations, 7 × 24 h entitlement) in the same row instead of splitting
  the trial's numbers between the catalogue and config.
* `billing_period` is the future paid-plan period label ("monthly", …);
  NULL for the one-time trial. No currency field exists — the paid
  catalogue (and its currencies) is deferred per step 26.
* NULL limit = no limit of that kind (the trial sets only the conversation
  and message limits; listing/product counts are reportable metrics, not
  trial quotas — step 27).
* The per-conversation 50 inbound-BUYER-message rule is deliberately NOT a
  plan field: it is abuse protection, not a package quota (step 26).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.subscription import Subscription


class Plan(Base):
    __tablename__ = "plans"

    __table_args__ = (
        UniqueConstraint("name", name="uq_plans_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Price in Rials as a plain Integer, same convention as products.price;
    # 0 for the Free Trial.
    price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    billing_period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Entitlement length in days; the trial's 7 becomes the half-open
    # [started_at, started_at + 7 × 24 h) window (step 27).
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listing_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Only active plans may be represented as available (§3.10.1, step 28
    # acceptance); the public plans API filters on this.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
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
    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="plan"
    )
