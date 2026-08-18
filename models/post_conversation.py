from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base
from models.enums import PostConversationState

if TYPE_CHECKING:
    from models.client import Client
    from models.post_message import PostMessage


class PostConversation(Base):
    __tablename__ = "post_conversations"

    __table_args__ = (
        UniqueConstraint(
            "divar_conversation_id",
            name="uq_post_conversations_divar_conversation_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        index=True,
    )
    divar_conversation_id: Mapped[str] = mapped_column(String(255))
    post_token: Mapped[str] = mapped_column(String(255))
    current_state: Mapped[PostConversationState] = mapped_column(
        Enum(
            PostConversationState,
            name="post_conversation_state_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=PostConversationState.NEW,
        nullable=False,
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

    client: Mapped[Client] = relationship(back_populates="post_conversations")
    messages: Mapped[list[PostMessage]] = relationship(
        back_populates="post_conversation"
    )
