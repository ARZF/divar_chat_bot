import hmac
from typing import Optional
from fastapi import APIRouter, Header, BackgroundTasks
from fastapi.responses import JSONResponse
from schemas.webhook import WebhookSchema
from config import settings
import services.divar as divar_service
from services.price_lookup import get_price

router = APIRouter()

# In-memory seen conversations (Phase 1 only — replaced by DB in Phase 2)
seen_conversations: set[str] = set()

# Reply constants — edit text here only, never inline
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

def match_keyword(text: str) -> Optional[str]:
    lowered = text.lower().strip()
    for keywords, intent in KEYWORD_MAP.items():
        if any(kw in lowered for kw in keywords):
            return intent
    return None

async def handle_bot_reply(client_id: str, conversation_id: str, user_text: str) -> None:
    is_new = conversation_id not in seen_conversations
    if is_new:
        seen_conversations.add(conversation_id)
        await divar_service.send_message(conversation_id, WELCOME_MESSAGE)
        return

    intent = match_keyword(user_text)

    if intent == "PRICE":
        price = get_price(user_text)
        reply = f"قیمت: {price} تومان" if price else PRICE_NOT_FOUND_MESSAGE
    elif intent == "WARRANTY":
        reply = WARRANTY_MESSAGE
    elif intent == "SUPPORT":
        reply = SUPPORT_MESSAGE
    else:
        reply = FALLBACK_MESSAGE

    await divar_service.send_message(conversation_id, reply)

@router.post("/api/v1/webhook/{client_id}")
async def webhook(
    client_id: str,
    payload: WebhookSchema,
    background_tasks: BackgroundTasks,
    authorization: str = Header(None),
):
    if not authorization or not hmac.compare_digest(
        authorization, settings.DIVAR_IDENTIFICATION_KEY
    ):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    if payload.type != "NEW_CHATBOT_MESSAGE" or not payload.new_chatbot_message:
        return JSONResponse(status_code=200, content={"status": "ignored"})

    conversation_id = payload.new_chatbot_message.conversation.id
    user_text = payload.new_chatbot_message.text

    background_tasks.add_task(handle_bot_reply, client_id, conversation_id, user_text)

    return JSONResponse(status_code=200, content={"status": "ok"})
