from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base
from services.state_machine import ConversationState

if TYPE_CHECKING:
    from models.client import Client
    from models.message import Message


class Conversation(Base):
    __tablename__ = "conversations"

    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "divar_conversation_id",
            name="uq_conversations_client_divar",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        index=True,
    )
    divar_conversation_id: Mapped[str] = mapped_column(String(255))
    current_state: Mapped[str] = mapped_column(
    String(50),
    default=ConversationState.START.value,
    nullable=False,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
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
    client: Mapped[Client] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(back_populates="conversation")

