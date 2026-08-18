from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.post_conversation import PostConversation


class PostSenderType(str, enum.Enum):
    BUYER = "buyer"
    BOT = "bot"


class PostMessage(Base):
    __tablename__ = "post_messages"

    __table_args__ = (
        UniqueConstraint(
            "divar_message_id",
            name="uq_post_messages_divar_message_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_conversation_id: Mapped[int] = mapped_column(
        ForeignKey("post_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    divar_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    sender_type: Mapped[PostSenderType] = mapped_column(
        Enum(
            PostSenderType,
            name="post_sender_type_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    post_conversation: Mapped[PostConversation] = relationship(
        back_populates="messages"
    )
