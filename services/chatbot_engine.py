# chatbot_engine.py
"""Shared intent-matching and reply-generation engine.

Called by both orchestrators (``services/chatbot_conversation.py`` and
``services/post_conversation.py``). Must never import either of them — the
dependency runs one way only, mirroring the services → models discipline.
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from services.price_lookup import (
    get_all_matching_prices,
    get_price,
    find_top_matches,
    normalize_text,
)


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


async def generate_chatbot_reply(
    db: AsyncSession,
    client_id: int,
    user_text: str,
    *,
    message_history: list[tuple[str, str]] | None = None,
) -> str | None:
    """Generate a stateless chatbot reply for either conversation type.

    `message_history` is accepted as the forward-compatible seam for a future
    history-aware implementation. The current intent-matching logic is still
    purely text-driven and does not inspect it.
    """
    _ = message_history

    normalized_text = normalize_text(user_text)
    if not normalized_text:
        return settings.FALLBACK_MESSAGE

    intent = _match_intent(normalized_text)
    if intent == "PRICE":
        return await _handle_price_intent(db, client_id, normalized_text)
    if intent in ("WARRANTY", "SUPPORT"):
        base = (
            settings.WARRANTY_MESSAGE
            if intent == "WARRANTY"
            else settings.SUPPORT_MESSAGE
        )
        contact = settings.CONTACT_MESSAGE_TEMPLATE.format(
            phone=settings.SUPPORT_PHONE_NUMBER
        )
        return f"{base}\n{contact}"
    if intent == "MENU":
        return settings.MENU_MESSAGE
    if intent == "SERVICE":
        return settings.SERVICE_MENU_MESSAGE
    if _is_pure_greeting(normalized_text):
        return settings.GREETING_REPLY_MESSAGE
    return settings.FALLBACK_MESSAGE


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
