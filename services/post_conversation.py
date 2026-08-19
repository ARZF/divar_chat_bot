# post_conversation.py
"""POST-conversation (``NEW_MESSAGE``) orchestration.

Split out of ``services/chatbot.py``. Depends on ``services/chatbot_engine.py``
for reply generation and must never import ``services/chatbot_conversation.py``.
"""
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import AsyncSessionLocal
from logging_config import client_id_var, conversation_id_var
from models.enums import PostConversationState
from models.oauth_token import OAuthToken
from models.post import Post
from models.post_conversation import PostConversation
from models.post_message import PostMessage, PostSenderType
from services.chatbot_engine import generate_chatbot_reply
from services.oauth_refresh import _refresh_supplier_token
import services.divar as divar_service

logger = logging.getLogger("chatbot")


# ---------------------------------------------------------------------------
# Post-conversation helpers
# ---------------------------------------------------------------------------
async def _resolve_post_conversation(
    db: AsyncSession,
    *,
    client_id: int,
    conversation_id: str,
    post_token: str,
) -> PostConversation | None:
    """Create or load an isolated post conversation, failing safe on ownership mismatch."""
    insert_stmt = (
        pg_insert(PostConversation)
        .values(
            client_id=client_id,
            divar_conversation_id=conversation_id,
            post_token=post_token,
            current_state=PostConversationState.NEW.value,
        )
        .on_conflict_do_nothing(
            constraint="uq_post_conversations_divar_conversation_id"
        )
    )

    try:
        result = await db.execute(insert_stmt)
    except IntegrityError:
        await db.rollback()
        owner_client_id = (
            await db.execute(
                select(PostConversation.client_id).where(
                    PostConversation.divar_conversation_id == conversation_id
                )
            )
        ).scalar_one_or_none()
        logger.error(
            "post conversation id already owned by another client — refusing to attribute this conversation",
            extra={
                "divar_conversation_id": conversation_id,
                "owner_client_id": owner_client_id,
                "claiming_client_id": client_id,
                "post_token": post_token,
            },
        )
        return None

    post_conversation = (
        await db.execute(
            select(PostConversation).where(
                PostConversation.divar_conversation_id == conversation_id
            )
        )
    ).scalar_one_or_none()
    if post_conversation is None:
        return None
    if post_conversation.client_id != client_id:
        logger.error(
            "post conversation id already owned by another client — refusing to attribute this conversation",
            extra={
                "divar_conversation_id": conversation_id,
                "owner_client_id": post_conversation.client_id,
                "claiming_client_id": client_id,
                "post_token": post_token,
                "inserted": result.rowcount == 1,
            },
        )
        await db.rollback()
        return None
    return post_conversation


async def _load_post_message_history(
    db: AsyncSession,
    post_conversation_id: int,
    *,
    limit: int = 10,
) -> list[tuple[str, str]]:
    """Return the recent post-conversation history, oldest first."""
    rows = (
        await db.execute(
            select(PostMessage.sender_type, PostMessage.text_content)
            .where(PostMessage.post_conversation_id == post_conversation_id)
            .order_by(PostMessage.created_at.desc(), PostMessage.id.desc())
            .limit(limit)
        )
    ).all()
    rows = list(reversed(rows))
    return [
        (sender_type.value, text_content or "")
        for sender_type, text_content in rows
    ]


# ---------------------------------------------------------------------------
# Main orchestrator — opens its own DB session (BackgroundTask-safe)
# ---------------------------------------------------------------------------
async def handle_post_bot_reply(
    conversation_id: str,
    post_token: str,
    user_text: str,
    divar_message_id: str,
) -> None:
    """Process a buyer message in a post conversation and send the bot reply."""
    client_id_var.set("-")
    conversation_id_var.set(conversation_id)
    logger.info(
        "post message received",
        extra={"conversation_id": conversation_id},
    )

    async with AsyncSessionLocal() as db:
        client_id = (
            await db.execute(
                select(Post.client_id).where(Post.post_token == post_token)
            )
        ).scalar_one_or_none()
        if client_id is None:
            logger.warning(
                "NEW_MESSAGE post_token did not resolve to a client",
                extra={
                    "post_token": post_token,
                    "conversation_id": conversation_id,
                },
            )
            return

        client_id_var.set(str(client_id))
        post_conversation = await _resolve_post_conversation(
            db,
            client_id=client_id,
            conversation_id=conversation_id,
            post_token=post_token,
        )
        if post_conversation is None:
            return

        buyer_insert = await db.execute(
            pg_insert(PostMessage)
            .values(
                post_conversation_id=post_conversation.id,
                divar_message_id=divar_message_id,
                sender_type=PostSenderType.BUYER.value,
                text_content=user_text,
            )
            .on_conflict_do_nothing(
                constraint="uq_post_messages_divar_message_id"
            )
        )
        if buyer_insert.rowcount != 1:
            await db.rollback()
            return

        history = await _load_post_message_history(db, post_conversation.id)
        reply = await generate_chatbot_reply(
            db,
            client_id,
            user_text,
            message_history=history,
        )
        if reply is None:
            await db.commit()
            return

        logger.info(
            "chatbot reply generated",
            extra={"conversation_id": conversation_id, "reply": reply},
        )

        oauth_token = (
            await db.execute(
                select(OAuthToken).where(OAuthToken.client_id == client_id)
            )
        ).scalar_one_or_none()
        if oauth_token is None:
            logger.warning(
                "supplier message skipped: OAuth token missing",
                extra={
                    "client_id": client_id,
                    "conversation_id": conversation_id,
                },
            )
            await db.rollback()
            return

        access_token = oauth_token.divar_access_token
        token_expires_at = oauth_token.token_expires_at
        if token_expires_at.tzinfo is None:
            token_expires_at = token_expires_at.replace(tzinfo=timezone.utc)
        if token_expires_at <= datetime.now(timezone.utc):
            access_token = await _refresh_supplier_token(client_id)
            if access_token is None:
                await db.rollback()
                return

        try:
            await divar_service.send_supplier_message(
                conversation_id, reply, access_token
            )
        except httpx.HTTPError as exc:
            # send_supplier_message re-raises the *original* exception after exhausting
            # retries, so this must cover both shapes it can surface: HTTPStatusError for
            # status failures, and the transport errors in divar.RETRYABLE_EXCEPTIONS
            # (ConnectTimeout/NetworkError/ReadTimeout/RemoteProtocolError) for network
            # exhaustion. httpx.HTTPError is the common base of both. Deliberately not
            # `except Exception` — a bug in generate_chatbot_reply above must still crash.
            status_code = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            logger.error(
                "supplier message send failed",
                extra={
                    "status_code": status_code,
                    "error": str(exc),
                    "client_id": client_id,
                    "conversation_id": conversation_id,
                },
            )
            await db.rollback()
            return

        db.add(
            PostMessage(
                post_conversation_id=post_conversation.id,
                sender_type=PostSenderType.BOT,
                text_content=reply,
            )
        )
        post_conversation.current_state = PostConversationState.ACTIVE
        await db.commit()

    logger.info(
        "post chatbot reply sent",
        extra={"conversation_id": conversation_id},
    )
