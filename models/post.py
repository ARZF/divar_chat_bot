"""Posts table — post_token → client ownership for conversation resolution,
plus Divar-sourced listing metadata (title/category/chat flags/last_synced_at)
fetched by services/divar_listings.py (step 20).

The Divar-sourced columns are written ONLY by that sync service; is_available
remains the project's own chatbot-availability flag (§3.8.4) and is never
sourced from Divar.
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
    is_available: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # Divar-sourced listing metadata (step 20); all nullable because a post
    # can be registered before its first listing sync. Sources:
    # user-posts (title, category, is_phone_hidden) and finder/post
    # (chat_enabled) per docs/post/get_user_posts.md and docs/post/get_post.md.
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
