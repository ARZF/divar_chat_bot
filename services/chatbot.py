# chatbot.py
from typing import Optional, Tuple
from config import settings
from services.price_lookup import get_price, normalize_text, find_top_matches, get_all_matching_prices
import services.divar as divar_service

# In-memory seen conversations (Phase 1 only)
seen_conversations: set[str] = set()

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
    clean_tokens = [tok for tok in tokens if tok not in ["قیمت", "price"] and tok not in settings.FILTERED_KEYWORDS]
    return " ".join(clean_tokens).strip()

async def handle_bot_reply(client_id: str, conversation_id: str, user_text: str) -> None:
    """
    Main orchestrator for processing user messages and sending the appropriate
    response back via Divar service.
    """
    is_new = conversation_id not in seen_conversations
    
    if is_new:
        seen_conversations.add(conversation_id)
        await divar_service.send_message(conversation_id, settings.WELCOME_MESSAGE)

    # Leverage the robust normalization pipeline
    normalized_text = normalize_text(user_text)
    intent = _match_intent(normalized_text)

    if intent == "PRICE":
        product_name = _extract_product_name(normalized_text)

        if not product_name:
            reply = settings.PRICE_PROMPT_MESSAGE
        else:
            # 1. Check substring matches FIRST
            matching_items = get_all_matching_prices(product_name)
            
            if len(matching_items) == 1:
                db_product_name, price = matching_items[0]
                reply = f"قیمت {db_product_name}: {price:,} تومان"
                
            elif len(matching_items) > 1:
                shown = matching_items[:settings.MAX_BULK_RESULTS]
                reply = "📋 لیست قیمت‌های یافت شده:\n\n"
                for name, price in shown:
                    reply += f"🔹 {name}: {price:,} تومان\n"
                    
                if len(matching_items) > settings.MAX_BULK_RESULTS:
                    remaining = len(matching_items) - settings.MAX_BULK_RESULTS
                    reply += f"\nو {remaining} مورد دیگر... لطفاً نام دقیق‌تر وارد کنید."
            else:
                # 2. Fall back to fuzzy matching
                result = get_price(product_name)
                if result is not None:
                    db_product_name, price = result
                    reply = f"قیمت {db_product_name}: {price:,} تومان"
                else:
                    # 3. Handle close fuzzy suggestions
                    candidates = [
                        name for name, score in find_top_matches(product_name, limit=2)
                        if score >= settings.SUGGESTION_MIN_SCORE
                    ]
                    if candidates:
                        canonical_candidates = []
                        for name in candidates:
                            resolved = get_price(name, threshold=0.0)
                            if resolved is not None:
                                canonical_candidates.append(resolved[0])
                                
                        if canonical_candidates:
                            options = " یا ".join(canonical_candidates)
                            reply = f"محصول مورد نظرتان را پیدا نکردم. منظورتان {options} بود؟"
                        else:
                            reply = settings.PRICE_NOT_FOUND_MESSAGE
                    else:
                        reply = settings.PRICE_NOT_FOUND_MESSAGE

    elif intent == "WARRANTY":
        reply = settings.WARRANTY_MESSAGE
    elif intent == "SUPPORT":
        reply = settings.SUPPORT_MESSAGE
    elif _is_pure_greeting(normalized_text):
        return
    else:
        reply = settings.FALLBACK_MESSAGE

    await divar_service.send_message(conversation_id, reply)