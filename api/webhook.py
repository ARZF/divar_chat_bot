from fastapi import APIRouter,HTTPException, Header
from services.divar import DivarService
from pydantic import BaseModel
from schemas.webhook import WebhookSchema
from config import settings

divar = DivarService()

router = APIRouter()


@router.post("/webhook")
async def webhook(payload: WebhookSchema,
                  authorization: str = Header(None)):
    
    if authorization != settings.DIVAR_IDENTIFICATION_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    if payload.type != "NEW_CHATBOT_MESSAGE" or not payload.new_chatbot_message:
       return {"status": "ignored"}

    conversation_id = (
        payload
        .new_chatbot_message
        .conversation
        .id
    )
    await divar.send_message(
        conversation_id,
        "سلام، پیام شما دریافت شد."
    )

    return {"status": "ok"}