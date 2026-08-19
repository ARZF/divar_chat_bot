# chatbot_conversation.py
"""BOT-conversation (``NEW_CHATBOT_MESSAGE``) orchestration.

Split out of ``services/chatbot.py``. Depends on ``services/chatbot_engine.py``
for reply generation and must never import ``services/post_conversation.py``.
"""
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.session import AsyncSessionLocal
from logging_config import client_id_var, conversation_id_var
from models.conversation import Conversation
from models.post import Post
from services.chatbot_engine import (
    _is_pure_greeting,
    _match_intent,
    generate_chatbot_reply,
)
from services.price_lookup import normalize_text, refresh_lookup_cache
from services.state_machine import INTENT_EVENTS, ConversationState, transition
import services.divar as divar_service

logger = logging.getLogger("chatbot")

# ---------------------------------------------------------------------------
# /start message parser (implements 2.1 parse_start_message)
# ---------------------------------------------------------------------------
TOUCHPOINT_NAMES = frozenset(
    {"MY_POST", "MY_DIVAR", "DIVAR_PRO", "CHAT", "DEMAND_POST"}
)


def parse_start_message(text: str) -> Optional[Tuple[str, Optional[str]]]:
    """Parse a ``/start`` touchpoint message.

    Returns ``(touchpoint_name, token_or_none)`` if *text* matches
    ``/start <TOUCHPOINT> [<token>]``, else ``None``.
    Handles all five documented touchpoint names and does not assume a token
    is present (bare ``/start MY_DIVAR`` is valid).
    """
    if not text:
        return None

    text = text.strip()

    if not text.startswith("/start "):
        return None

    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        return None

    touchpoint = parts[1]
    if touchpoint not in TOUCHPOINT_NAMES:
        return None

    token = parts[2] if len(parts) > 2 else None
    return (touchpoint, token)


# ---------------------------------------------------------------------------
# Conversation resolution helpers
# ---------------------------------------------------------------------------
async def _lookup_conversation(
    db: AsyncSession, divar_conversation_id: str
) -> Optional[Conversation]:
    """Look up an existing resolved conversation by its Divar-assigned ID."""
    # No client_id filter is possible here — it is exactly what this lookup
    # resolves. scalar_one_or_none() is safe because migration 0004 makes
    # divar_conversation_id globally UNIQUE at the DB level; do not add a
    # defensive .first()/limit(1) fallback, it would only mask a broken schema.
    stmt = select(Conversation).where(
        Conversation.divar_conversation_id == divar_conversation_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _resolve_new_conversation(
    db: AsyncSession,
    divar_conversation_id: str,
    user_text: str,
) -> Optional[Tuple[Conversation, bool]]:
    """Attempt to resolve a conversation from a ``/start`` message.

    If the message carries a post_token (``MY_POST`` or ``DEMAND_POST``)
    and that token is registered in the ``posts`` table, the conversation
    row is created via an atomic upsert and ``(conversation, is_new)`` is
    returned. ``is_new`` reflects whether *this* call actually inserted the
    row, so a redelivered webhook that loses the race gets ``False`` and the
    caller skips the welcome message and the auto-advance (2.2).

    Does NOT commit — the caller owns the transaction so the row and any
    state transition land together (2.6).

    Returns ``None`` for unresolvable touchpoints, unknown post tokens, and
    for a second client claiming an already-owned ``divar_conversation_id``.
    All three fail safe the same way: nothing persisted, canned reply.
    """
    parsed = parse_start_message(user_text)

    if parsed is None:
        return None

    touchpoint, token = parsed

    if touchpoint not in ("MY_POST", "DEMAND_POST") or not token:
        return None

    # Look up post_token → client_id (WHERE scoped to post_token PK)
    stmt = select(Post.client_id).where(Post.post_token == token)
    result = await db.execute(stmt)
    resolved_client_id = result.scalar_one_or_none()

    if resolved_client_id is None:
        return None  # Post not registered by any seller

    # Atomic upsert: INSERT ... ON CONFLICT DO NOTHING.
    # The named composite constraint covers legitimate redelivery only — same
    # client, same conversation. A *different* client claiming this
    # divar_conversation_id conflicts against 0004's global UNIQUE instead,
    # which DO NOTHING does not swallow: it raises IntegrityError below.
    insert_stmt = (
        pg_insert(Conversation)
        .values(
            client_id=resolved_client_id,
            divar_conversation_id=divar_conversation_id,
            current_state=ConversationState.START.value,
        )
        .on_conflict_do_nothing(
            constraint="uq_conversations_client_divar"
        )
    )
    try:
        result = await db.execute(insert_stmt)
    except IntegrityError:
        # Should be unreachable: Divar assigns conversation IDs, so two clients
        # cannot legitimately be handed the same one. If it happens, our
        # global-uniqueness inference (see CHANGELOG 2026-08-13) was wrong.
        await db.rollback()
        # Deliberately not via _lookup_conversation: this diagnostic must stay
        # accurate regardless of what the caller's entry-point lookup returned.
        owner_client_id = (
            await db.execute(
                select(Conversation.client_id).where(
                    Conversation.divar_conversation_id == divar_conversation_id
                )
            )
        ).scalar_one_or_none()
        logger.error(
            "divar_conversation_id already owned by another client — "
            "refusing to attribute this conversation",
            extra={
                "divar_conversation_id": divar_conversation_id,
                "owner_client_id": owner_client_id,
                "claiming_client_id": resolved_client_id,
                "post_token": token,
            },
        )
        return None

    # rowcount == 1 → we created the row (new conversation)
    # rowcount == 0 → race: another delivery already created it
    is_new = result.rowcount == 1

    # A Core insert yields no ORM instance, and on the race path inserts nothing
    # at all — re-select to get the row either way. Scoped by the full composite
    # key: client_id is known by now, making this the one query in the flow where
    # 2.2's "WHERE client_id = :current_client_id" rule is enforceable in code
    # rather than merely relied on via the constraint.
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.client_id == resolved_client_id,
                Conversation.divar_conversation_id == divar_conversation_id,
            )
        )
    ).scalar_one()

    return conv, is_new


def _state_of(conv: Conversation) -> ConversationState:
    """Parse the persisted state, falling back to START if it is unrecognized.

    Runs inside a BackgroundTask where the webhook already returned 200, so a
    raised ValueError would just mean the user silently never gets a reply.
    """
    try:
        return ConversationState(conv.current_state)
    except ValueError:
        logger.warning(
            "unrecognized conversation state — falling back to START",
            extra={"state": conv.current_state},
        )
        return ConversationState.START


async def _safe_send(conversation_id: str, text: str) -> bool:
    """Send a message, logging and swallowing send failures.

    handle_bot_reply runs in a FastAPI BackgroundTask after the webhook already
    returned 200, so a raised send error would only surface as an unhandled
    background-task exception. We log it and return False instead, so one failed
    send (e.g. the welcome) never aborts a later, more important send (the reply)
    or the state commit that precedes it.
    """
    try:
        await divar_service.send_message(conversation_id, text)
        return True
    except Exception:
        logger.exception(
            "send_message failed in background task",
            extra={"conversation_id": conversation_id},
        )
        return False


# ---------------------------------------------------------------------------
# Main orchestrator — opens its own DB session (BackgroundTask-safe)
# ---------------------------------------------------------------------------
async def handle_bot_reply(conversation_id: str, user_text: str) -> None:
    """Process a user message and send the appropriate response.

    Opens its own ``AsyncSession`` (do NOT inject the request's session —
    FastAPI closes it before background tasks run).
    Resolves ``client_id`` from the conversations/posts tables (2.1).
    """
    conversation_id_var.set(conversation_id)
    logger.debug("processing message", extra={"text": user_text})

    async with AsyncSessionLocal() as db:
        # ---- 1. Resolve conversation → client_id ----
        conv = await _lookup_conversation(db, conversation_id)

        if conv is not None:
            # Existing resolved conversation
            is_new = False
        else:
            # First time seeing this conversation — try to resolve via /start
            resolved = await _resolve_new_conversation(db, conversation_id, user_text)
            if resolved is None:
                # Unresolved — send canned message, persist nothing. No commit:
                # an unresolved conversation never gets a row (CHANGELOG 2026-07-20).
                # A cross-client divar_conversation_id collision lands here too,
                # already logged and rolled back (CHANGELOG 2026-08-13).
                logger.info(
                    "unresolved conversation",
                    extra={"text": user_text},
                )
                await _safe_send(conversation_id, settings.UNRESOLVED_CLIENT_MESSAGE)
                return
            # is_new comes from whether the upsert actually inserted — NOT from
            # "the lookup above found nothing". Two redelivered webhooks can both
            # pass that lookup before either commits; only one inserts.
            conv, is_new = resolved

        client_id = conv.client_id

        # ---- 2. Set logging context ----
        client_id_var.set(str(client_id))

        # ---- 3. Ensure price cache is loaded for this client ----
        from services.price_lookup import _cache

        if client_id not in _cache:
            await refresh_lookup_cache(db, client_id)

        # ---- 4. Auto-advance on first-in-conversation ----
        # In-memory only; the welcome send is deferred until after the commit
        # (see step 6) so a failed send cannot abort the state transition or
        # the substantive reply.
        if is_new:
            # Fires unconditionally on first contact — no keyword needed.
            conv.current_state = transition(_state_of(conv), "menu").value

        # ---- 5. Intent matching & response ----
        normalized_text = normalize_text(user_text)
        intent = _match_intent(normalized_text)
        logger.info("intent matched", extra={"intent": intent, "text": user_text})

        # Unmatched text yields no event, and therefore no transition.
        event = INTENT_EVENTS.get(intent)
        if event is not None:
            conv.current_state = transition(_state_of(conv), event).value

        reply = await generate_chatbot_reply(db, client_id, user_text)
        if is_new and _is_pure_greeting(normalized_text):
            # Welcome already covers it — but the state change still needs saving.
            logger.debug("greeting suppressed — welcome already sent")
            reply = None

        # ---- 6. Persist state, then send ----
        # One transaction for the whole webhook (2.6). Committed BEFORE the sends
        # because send_message re-raises on non-2xx: a transient Divar failure
        # should cost the outbound message, never the state. Both sends go
        # through _safe_send, so a failed welcome cannot suppress the reply.
        await db.commit()

        if is_new:
            await _safe_send(conversation_id, settings.WELCOME_MESSAGE)

        if reply is None:
            return

        await _safe_send(conversation_id, reply)
        logger.info("reply sent", extra={"text": reply})
