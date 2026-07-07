from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.conversation import Conversation


class SenderType(str, enum.Enum):
    USER = "user"
    BOT = "bot"
    HUMAN_AGENT = "human_agent"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    divar_message_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    sender_type: Mapped[SenderType] = mapped_column(
        Enum(SenderType, name="sender_type_enum")
    )
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    conversation: Mapped[Conversation] = relationship(
        back_populates="messages"
    )

