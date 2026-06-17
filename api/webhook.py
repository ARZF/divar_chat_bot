import hmac
from fastapi import APIRouter, Header, BackgroundTasks
from fastapi.responses import JSONResponse
from schemas.webhook import WebhookSchema
from config import settings
from services.chatbot import handle_bot_reply

router = APIRouter()

@router.post("/api/v1/webhook/{client_id}")
async def webhook(
    client_id: str,
    payload: WebhookSchema,
    background_tasks: BackgroundTasks,
    authorization: str = Header(None),
):
    # 1. Security Gate
    if not authorization or not hmac.compare_digest(
        authorization, settings.DIVAR_IDENTIFICATION_KEY
    ):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    # 2. Event Filtering
    if payload.type != "NEW_CHATBOT_MESSAGE" or not payload.new_chatbot_message:
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # 3. Data Extraction
    conversation_id = payload.new_chatbot_message.conversation.id
    user_text = payload.new_chatbot_message.text

    # 4. Hand off to the Chatbot Service asynchronously
    background_tasks.add_task(handle_bot_reply, client_id, conversation_id, user_text)

    return JSONResponse(status_code=200, content={"status": "ok"})