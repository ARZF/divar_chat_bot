"""Posts table — post_token → client ownership for conversation resolution,
plus Divar-sourced listing metadata (title/category/chat flags/last_synced_at)
fetched by services/divar_listings.py (steps 20-21).

Two single-owner flags, deliberately separate (a seller's manual chatbot
toggle must survive syncs, and sync's presence verdict must survive manual
toggles):

* `present_on_divar` — written ONLY by the listing sync: True while the
  latest user-posts response still contains the post, False once it is gone.
* `is_available` — written ONLY by the seller's availability PATCH (§3.8.4):
  whether the chatbot should handle this listing at all.

Conversation resolution (chatbot_conversation / post_conversation) requires
both: the chatbot answers only for a listing that still exists on Divar and
whose seller has not disabled it. Whether the *item* is still for sale is
not a posts field — it lives in the seller's products catalog, which the
chatbot's answers already derive from.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.client import Client


class Post(Base):
    __tablename__ = "posts"

    post_token: Mapped[str] = mapped_column(String(20), primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        index=True,
    )
    # Chatbot availability toggle (§3.8.4) — written ONLY by the seller's
    # PATCH .../availability endpoint, never by sync.
    is_available: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # Listing existence on Divar — written ONLY by services/divar_listings.py.
    present_on_divar: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # Divar-sourced listing metadata (step 20); all nullable because rows are
    # only written by services/divar_listings.py, and the source (user-posts)
    # may omit any field. Per docs/post/get_user_posts.md: title, category,
    # is_phone_hidden, and supplier_chat_assistant_enabled → chat_enabled.
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chat_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_phone_hidden: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    client: Mapped[Client] = relationship(back_populates="posts")
