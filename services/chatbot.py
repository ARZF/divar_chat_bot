from typing import Optional, Tuple
from services.price_lookup import get_price, normalize_text, find_top_matches
import services.divar as divar_service

# In-memory seen conversations (Phase 1 only)
seen_conversations: set[str] = set()

# Reply constants
WELCOME_MESSAGE = "سلام! به پشتیبانی خوش آمدید. برای قیمت بنویسید «قیمت»، برای گارانتی «گارانتی»، برای پشتیبانی «پشتیبانی»."
PRICE_NOT_FOUND_MESSAGE = "متأسفانه قیمت این محصول در سیستم ما یافت نشد."
PRICE_PROMPT_MESSAGE = "لطفاً نام محصول را وارد کنید. مثال: قیمت لپتاپ"
WARRANTY_MESSAGE = "محصولات ما دارای گارانتی ۱۲ ماهه هستند."
SUPPORT_MESSAGE = "تیم پشتیبانی ما در ساعات کاری ۹ تا ۱۸ پاسخگوی شما هستند."
FALLBACK_MESSAGE = "پیام شما دریافت شد. برای راهنمایی بیشتر با پشتیبانی تماس بگیرید."

# Below this score, a fuzzy candidate is too unreliable to even suggest as
# a "did you mean" option — it's effectively noise and would confuse the user.
SUGGESTION_MIN_SCORE = 45.0

# Pure greeting tokens — if a message contains ONLY these (after normalization),
# it's treated as a no-op: welcome was already sent for new conversations, and
# repeating a greeting back or sending the fallback message would feel like
# spam. Anything else unmatched still gets FALLBACK_MESSAGE so the user always
# knows their message was received, even if the bot didn't understand it.
GREETING_TOKENS = frozenset([
    "سلام", "درود", "سلامت", "هلو",
    "hi", "hello", "hey",
])

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

def _is_pure_greeting(normalized_text: str) -> bool:
    """True only if EVERY token in the message is a greeting word — so
    "سلام قیمت گوشی چنده" still falls through to intent matching as normal,
    while a lone "سلام" or "سلام خوبید؟"-without-other-content is treated
    as a no-op rather than triggering the fallback message."""
    tokens = normalized_text.split()
    if not tokens:
        return False
    return all(tok in GREETING_TOKENS for tok in tokens)

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
            reply = PRICE_PROMPT_MESSAGE
        else:
            result = get_price(product_name)
            if result is not None:
                db_product_name, price = result
                reply = f"قیمت {db_product_name}: {price:,} تومان"
            else:
                # No confident match. Before giving up, check whether there
                # are nearby candidates worth surfacing — e.g. user typed
                # "آيفون" (typo) and the catalog has "آیفون 13" — rather than
                # a flat "not found" that leaves the user with no next step.
                candidates = [
                    name for name, score in find_top_matches(product_name, limit=2)
                    if score >= SUGGESTION_MIN_SCORE
                ]
                if candidates:
                    # find_top_matches returns normalized keys; resolve each
                    # to its canonical (display-safe) name via get_price so
                    # we never show normalized/lowercased text to the user.
                    canonical_candidates = []
                    for name in candidates:
                        resolved = get_price(name, threshold=0.0)
                        if resolved is not None:
                            canonical_candidates.append(resolved[0])
                    if canonical_candidates:
                        options = " یا ".join(canonical_candidates)
                        reply = f"محصول مورد نظرتان را پیدا نکردم. منظورتان {options} بود؟"
                    else:
                        reply = PRICE_NOT_FOUND_MESSAGE
                else:
                    reply = PRICE_NOT_FOUND_MESSAGE
                
    elif intent == "WARRANTY":
        reply = WARRANTY_MESSAGE
    elif intent == "SUPPORT":
        reply = SUPPORT_MESSAGE
    elif _is_pure_greeting(normalized_text):
        # Welcome (if new) was already sent above; nothing more to say.
        return
    else:
        reply = FALLBACK_MESSAGE

    await divar_service.send_message(conversation_id, reply)