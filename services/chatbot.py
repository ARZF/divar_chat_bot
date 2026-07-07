# chatbot.py
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.session import AsyncSessionLocal
from logging_config import client_id_var, conversation_id_var
from models.conversation import Conversation
from models.post import Post
from services.price_lookup import (
    get_price,
    normalize_text,
    find_top_matches,
    get_all_matching_prices,
    refresh_lookup_cache,
)
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
    if not text or not text.startswith("/start "):
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
    stmt = select(Conversation).where(
        Conversation.divar_conversation_id == divar_conversation_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _resolve_new_conversation(
    db: AsyncSession,
    divar_conversation_id: str,
    user_text: str,
) -> Optional[int]:
    """Attempt to resolve ``client_id`` from a ``/start`` message.

    If the message carries a post_token (``MY_POST`` or ``DEMAND_POST``)
    and that token is registered in the ``posts`` table, the conversation
    row is created via an atomic upsert and the resolved ``client_id`` is
    returned.

    Returns ``None`` for unresolvable touchpoints or unknown post tokens.
    """
    parsed = parse_start_message(user_text)
    if parsed is None:
        # Not a /start message — treat as unresolved
        return None

    touchpoint, token = parsed

    if touchpoint in ("MY_POST", "DEMAND_POST") and token:
        # Look up post_token → client_id (WHERE scoped to post_token PK)
        stmt = select(Post.client_id).where(Post.post_token == token)
        result = await db.execute(stmt)
        resolved_client_id = result.scalar_one_or_none()

        if resolved_client_id is None:
            return None  # Post not registered by any seller

        # Atomic upsert: INSERT ... ON CONFLICT DO NOTHING
        # rowcount == 1 → we created the row (new conversation)
        # rowcount == 0 → race: another request already created it
        insert_stmt = (
            pg_insert(Conversation)
            .values(
                client_id=resolved_client_id,
                divar_conversation_id=divar_conversation_id,
                current_state="START",
            )
            .on_conflict_do_nothing(
                constraint="uq_conversations_client_divar"
            )
        )
        await db.execute(insert_stmt)
        await db.commit()
        return resolved_client_id

    # ------------------------------------------------------------------
    # Experimental fallback for chatbot testing.
    #
    # In production, MY_DIVAR / DIVAR_PRO / CHAT conversations cannot be
    # resolved because they carry no post_token.
    #
    # During development we allow routing unresolved conversations to a
    # fixed test client configured in settings.
    #
    # IMPORTANT:
    # We also persist the conversation here so subsequent messages in the
    # same Divar conversation_id can resolve directly from the database,
    # matching the production flow.
    # ------------------------------------------------------------------
    if settings.EXPERIMENTAL_CLIENT_ID is not None:
        client_id = settings.EXPERIMENTAL_CLIENT_ID

        insert_stmt = (
            pg_insert(Conversation)
            .values(
                client_id=client_id,
                divar_conversation_id=divar_conversation_id,
                current_state="START",
            )
            .on_conflict_do_nothing(
                constraint="uq_conversations_client_divar"
            )
        )

        await db.execute(insert_stmt)
        await db.commit()

        logger.warning(
            "Using experimental client fallback",
            extra={
                "conversation_id": divar_conversation_id,
                "client_id": client_id,
                "touchpoint": touchpoint,
            },
        )

        return client_id

    return None


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
            client_id = conv.client_id
            is_new = False
        else:
            # First time seeing this conversation — try to resolve via /start
            client_id_or_none = await _resolve_new_conversation(
                db, conversation_id, user_text
            )
            if client_id_or_none is None:
                # Unresolved — send canned message, persist nothing (2.1 design)
                logger.info(
                    "unresolved conversation",
                    extra={"text": user_text},
                )
                await divar_service.send_message(
                    conversation_id, settings.UNRESOLVED_CLIENT_MESSAGE
                )
                return
            client_id = client_id_or_none
            is_new = True

        # ---- 2. Set logging context ----
        client_id_var.set(str(client_id))

        # ---- 3. Ensure price cache is loaded for this client ----
        from services.price_lookup import _prices

        if client_id not in _prices:
            await refresh_lookup_cache(db, client_id)

        # ---- 4. Welcome message on first-in-conversation ----
        if is_new:
            await divar_service.send_message(
                conversation_id, settings.WELCOME_MESSAGE
            )

        # ---- 5. Intent matching & response ----
        normalized_text = normalize_text(user_text)
        intent = _match_intent(normalized_text)
        logger.info("intent matched", extra={"intent": intent, "text": user_text})

        if intent == "PRICE":
            reply = _handle_price_intent(client_id, normalized_text)
        elif intent == "WARRANTY":
            reply = settings.WARRANTY_MESSAGE
        elif intent == "SUPPORT":
            reply = settings.SUPPORT_MESSAGE
        elif _is_pure_greeting(normalized_text):
            if is_new:
                logger.debug("greeting suppressed — welcome already sent")
                return
            reply = settings.GREETING_REPLY_MESSAGE
            await divar_service.send_message(conversation_id, reply)
            logger.info("reply sent", extra={"text": reply})
            return
        else:
            reply = settings.FALLBACK_MESSAGE

        await divar_service.send_message(conversation_id, reply)
        logger.info("reply sent", extra={"text": reply})


# ---------------------------------------------------------------------------
# Price-intent handler (extracted for readability)
# ---------------------------------------------------------------------------
def _handle_price_intent(client_id: int, normalized_text: str) -> str:
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
    result = get_price(client_id, product_name)
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
            resolved = get_price(client_id, name, threshold=0.0)
            if resolved is not None:
                canonical_candidates.append(resolved[0])

        if canonical_candidates:
            options = " یا ".join(canonical_candidates)
            return f"محصول مورد نظرتان را پیدا نکردم. منظورتان {options} بود؟"

    return settings.PRICE_NOT_FOUND_MESSAGE
