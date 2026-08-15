# chatbot.py
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.session import AsyncSessionLocal
from logging_config import client_id_var, conversation_id_var
from models.conversation import Conversation
from models.oauth_token import OAuthToken
from models.post import Post
from services.price_lookup import (
    get_price,
    normalize_text,
    find_top_matches,
    get_all_matching_prices,
    refresh_lookup_cache,
)
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


# ---------------------------------------------------------------------------
# Intent helpers (unchanged from Phase 1)
# ---------------------------------------------------------------------------
def _match_intent(normalized_text: str) -> Optional[str]:
    """Internal helper to match intent against pre-normalized text tokens."""
    tokens = normalized_text.split()
    for keywords, intent in settings.KEYWORD_MAP.items():
        if any(kw in tokens for kw in keywords):
            return intent
    return None


def _is_pure_greeting(normalized_text: str) -> bool:
    """True only if EVERY token in the message is a greeting word."""
    tokens = normalized_text.split()
    if not tokens:
        return False
    return all(tok in settings.GREETING_TOKENS for tok in tokens)


def _extract_product_name(normalized_text: str) -> str:
    """Internal helper to clean intent keywords and isolate the product query."""
    tokens = normalized_text.split()
    clean_tokens = [
        tok
        for tok in tokens
        if tok not in ["قیمت", "price"] and tok not in settings.FILTERED_KEYWORDS
    ]
    return " ".join(clean_tokens).strip()


# ---------------------------------------------------------------------------
# Main orchestrator — opens its own DB session (BackgroundTask-safe)
# ---------------------------------------------------------------------------
async def handle_supplier_message(
    conversation_id: str, post_token: str, text: str
) -> None:
    """Resolve a supplier post chat and send the seller-authorized reply."""
    client_id_var.set("-")
    conversation_id_var.set(conversation_id)

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
            return
        access_token = oauth_token.divar_access_token
        refresh_token = oauth_token.divar_refresh_token
        token_expires_at = oauth_token.token_expires_at

    client_id_var.set(str(client_id))

    if token_expires_at.tzinfo is None:
        token_expires_at = token_expires_at.replace(tzinfo=timezone.utc)
    if token_expires_at <= datetime.now(timezone.utc):
        try:
            access_token, refresh_token = await divar_service.refresh_access_token(
                access_token
            )
        except httpx.HTTPError:
            logger.error(
                "supplier message skipped: OAuth token refresh failed",
                extra={"client_id": client_id},
                exc_info=True,
            )
            return

        async with AsyncSessionLocal() as db:
            oauth_token = (
                await db.execute(
                    select(OAuthToken).where(OAuthToken.client_id == client_id)
                )
            ).scalar_one()
            oauth_token.divar_access_token = access_token
            oauth_token.divar_refresh_token = refresh_token
            oauth_token.token_expires_at = datetime.now(timezone.utc) + timedelta(
                days=7
            )
            await db.commit()
        # TODO: Re-register the event subscription after refresh per PHASE2.md §2.9's
        # "Mandatory, recurring" note; refresh scheduling infrastructure is not built.

    try:
        await divar_service.send_supplier_message(
            conversation_id, text, access_token
        )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "supplier message send failed",
            extra={
                "status_code": exc.response.status_code,
                "client_id": client_id,
                "conversation_id": conversation_id,
            },
        )
        return

    logger.info(
        "supplier reply sent",
        extra={
            "client_id": client_id,
            "conversation_id": conversation_id,
            "send_method": "send_supplier_message",
        },
    )


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
                await divar_service.send_message(
                    conversation_id, settings.UNRESOLVED_CLIENT_MESSAGE
                )
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

        # ---- 4. Welcome message + auto-advance on first-in-conversation ----
        if is_new:
            await divar_service.send_message(
                conversation_id, settings.WELCOME_MESSAGE
            )
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

        if intent == "PRICE":
            reply = await _handle_price_intent(db, client_id, normalized_text)
        elif intent in ("WARRANTY", "SUPPORT"):
            base = (
                settings.WARRANTY_MESSAGE
                if intent == "WARRANTY"
                else settings.SUPPORT_MESSAGE
            )
            contact = settings.CONTACT_MESSAGE_TEMPLATE.format(
                phone=settings.SUPPORT_PHONE_NUMBER
            )
            reply = f"{base}\n{contact}"
        elif intent == "MENU":
            reply = settings.MENU_MESSAGE
        elif intent == "SERVICE":
            reply = settings.SERVICE_MENU_MESSAGE
        elif _is_pure_greeting(normalized_text):
            if is_new:
                # Welcome already covers it — but the state change still needs saving.
                logger.debug("greeting suppressed — welcome already sent")
                reply = None
            else:
                reply = settings.GREETING_REPLY_MESSAGE
        else:
            reply = settings.FALLBACK_MESSAGE

        # ---- 6. Persist state, then send ----
        # One transaction for the whole webhook (2.6). Committed BEFORE the send
        # because send_message re-raises on non-2xx: a transient Divar failure
        # should cost the outbound message, never the state.
        await db.commit()

        if reply is None:
            return

        await divar_service.send_message(conversation_id, reply)
        logger.info("reply sent", extra={"text": reply})


# ---------------------------------------------------------------------------
# Price-intent handler (extracted for readability)
# ---------------------------------------------------------------------------
async def _handle_price_intent(
    db: AsyncSession, client_id: int, normalized_text: str
) -> str:
    """Build the reply for a PRICE intent, scoped to *client_id*."""
    product_name = _extract_product_name(normalized_text)

    if not product_name:
        return settings.PRICE_PROMPT_MESSAGE

    # 1. Substring matches FIRST
    matching_items = get_all_matching_prices(client_id, product_name)

    if len(matching_items) == 1:
        db_product_name, price = matching_items[0]
        return f"قیمت {db_product_name}: {price:,} تومان"

    if len(matching_items) > 1:
        shown = matching_items[: settings.MAX_BULK_RESULTS]
        reply = "📋 لیست قیمت‌های یافت شده:\n\n"
        for name, price in shown:
            reply += f"🔹 {name}: {price:,} تومان\n"
        if len(matching_items) > settings.MAX_BULK_RESULTS:
            remaining = len(matching_items) - settings.MAX_BULK_RESULTS
            reply += f"\nو {remaining} مورد دیگر... لطفاً نام دقیق‌تر وارد کنید."
        return reply

    # 2. Fuzzy matching
    result = await get_price(db, client_id, product_name)
    if result is not None:
        db_product_name, price = result
        return f"قیمت {db_product_name}: {price:,} تومان"

    # 3. Suggestions
    candidates = [
        name
        for name, score in find_top_matches(client_id, product_name, limit=2)
        if score >= settings.SUGGESTION_MIN_SCORE
    ]
    if candidates:
        canonical_candidates = []
        for name in candidates:
            resolved = await get_price(db, client_id, name, threshold=0.0)
            if resolved is not None:
                canonical_candidates.append(resolved[0])

        if canonical_candidates:
            options = " یا ".join(canonical_candidates)
            return f"محصول مورد نظرتان را پیدا نکردم. منظورتان {options} بود؟"

    return settings.PRICE_NOT_FOUND_MESSAGE
