from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.conversation import Conversation
    from models.oauth_token import OAuthToken
    from models.post import Post
    from models.product import Product
    from models.refresh_token import RefreshToken


class Client(Base):
    __tablename__ = "clients"

    __table_args__ = (
        CheckConstraint(
            "phone_number IS NOT NULL OR divar_user_id IS NOT NULL",
            name="ck_clients_has_identifier",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_number: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True
    )
    divar_user_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    oauth_token: Mapped[OAuthToken | None] = relationship(
        back_populates="client", uselist=False
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="client"
    )
    posts: Mapped[list[Post]] = relationship(back_populates="client")
    products: Mapped[list[Product]] = relationship(back_populates="client")
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="client"
    )


