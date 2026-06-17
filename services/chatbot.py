from typing import Optional, Tuple
from services.price_lookup import get_price, normalize_text
import services.divar as divar_service

# In-memory seen conversations (Phase 1 only)
seen_conversations: set[str] = set()

# Reply constants
WELCOME_MESSAGE = "سلام! به پشتیبانی خوش آمدید. برای قیمت بنویسید «قیمت»، برای گارانتی «گارانتی»، برای پشتیبانی «پشتیبانی»."
PRICE_NOT_FOUND_MESSAGE = "متأسفانه قیمت این محصول در سیستم ما یافت نشد."
WARRANTY_MESSAGE = "محصولات ما دارای گارانتی ۱۲ ماهه هستند."
SUPPORT_MESSAGE = "تیم پشتیبانی ما در ساعات کاری ۹ تا ۱۸ پاسخگوی شما هستند."
FALLBACK_MESSAGE = "پیام شما دریافت شد. برای راهنمایی بیشتر با پشتیبانی تماس بگیرید."

KEYWORD_MAP = {
    frozenset(["price", "قیمت"]): "PRICE",
    frozenset(["warranty", "گارانتی"]): "WARRANTY",
    frozenset(["support", "پشتیبانی"]): "SUPPORT",
}

def _match_intent(normalized_text: str) -> Optional[str]:
    """Internal helper to match intent against pre-normalized text tokens."""
    tokens = normalized_text.split()
    for keywords, intent in KEYWORD_MAP.items():
        if any(kw in tokens for kw in keywords):
            return intent
    return None

def _extract_product_name(normalized_text: str) -> str:
    """Internal helper to clean intent keywords and isolate the product query."""
    tokens = normalized_text.split()
    clean_tokens = [tok for tok in tokens if tok not in ["قیمت", "price"]]
    return " ".join(clean_tokens).strip()

async def handle_bot_reply(client_id: str, conversation_id: str, user_text: str) -> None:
    """
    Main orchestrator for processing user messages and sending the appropriate
    response back via Divar service.
    """
    is_new = conversation_id not in seen_conversations
    
    if is_new:
        seen_conversations.add(conversation_id)
        await divar_service.send_message(conversation_id, WELCOME_MESSAGE)

    # Leverage the robust normalization pipeline
    normalized_text = normalize_text(user_text)
    intent = _match_intent(normalized_text)

    if intent == "PRICE":
        product_name = _extract_product_name(normalized_text)

        if not product_name:
            reply = "لطفاً نام محصول را وارد کنید. مثال: قیمت لپتاپ"
        else:
            result = get_price(product_name)
            if result is not None:
                db_product_name, price = result
                reply = f"قیمت {db_product_name}: {price:,} تومان"
            else:
                reply = PRICE_NOT_FOUND_MESSAGE
                
    elif intent == "WARRANTY":
        reply = WARRANTY_MESSAGE
    elif intent == "SUPPORT":
        reply = SUPPORT_MESSAGE
    else:
        if is_new:
            return  # Avoid double-replying if it's just a greeting
        reply = FALLBACK_MESSAGE

    await divar_service.send_message(conversation_id, reply)