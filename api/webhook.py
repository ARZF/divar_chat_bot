from fastapi import APIRouter,HTTPException
from services.divar import DivarService
from pydantic import BaseModel
from schemas.webhook import WebhookSchema


divar = DivarService()

router = APIRouter()


@router.post("/webhook")
async def webhook(payload: WebhookSchema):

    if payload.type != "NEW_CHATBOT_MESSAGE" or not payload.new_chatbot_message:
       return {"status": "ignored"}

    conversation_id = (
        payload
        .new_chatbot_message
        .conversation
        .id
    )
    divar.send_message(
        conversation_id,
        "سلام، پیام شما دریافت شد."
    )

    return {"status": "ok"}