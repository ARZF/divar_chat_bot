import hmac
from fastapi import APIRouter, Header, BackgroundTasks
from fastapi.responses import JSONResponse

from config import settings
from logging_config import conversation_id_var
from schemas.webhook import EventType, WebhookSchema
from services.chatbot import handle_bot_reply, handle_supplier_message
import logging

router = APIRouter()
logger = logging.getLogger("webhook")

@router.post("/api/v1/webhook")
async def webhook(
    payload: WebhookSchema,
    background_tasks: BackgroundTasks,
    authorization: str = Header(None),
):
    # 1. Security Gate
    if not authorization or not hmac.compare_digest(
        authorization, settings.DIVAR_IDENTIFICATION_KEY
    ):
        logger.warning("webhook auth failed")
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    # 2. Event Dispatch
    if payload.type == EventType.NEW_CHATBOT_MESSAGE:
        if not payload.new_chatbot_message:
            return JSONResponse(status_code=200, content={"status": "ignored"})

        # 3. Data Extraction
        conversation_id = payload.new_chatbot_message.conversation.id
        user_text = payload.new_chatbot_message.text
        conversation_id_var.set(conversation_id)

        if not user_text:
            logger.debug("message with no text content — ignoring")
            return JSONResponse(status_code=200, content={"status": "ignored"})

        logger.info("incoming message", extra={"text": user_text})
        
        # 4. Hand off to the Chatbot Service asynchronously
        background_tasks.add_task(handle_bot_reply, conversation_id, user_text)

        return JSONResponse(status_code=200, content={"status": "ok"})

    if payload.type == EventType.NEW_MESSAGE:
        message = payload.new_message
        if not message or message.sender.side != "BUYER":
            return JSONResponse(status_code=200, content={"status": "ignored"})

        conversation_id = message.conversation.id
        post_token = message.conversation.post_token
        conversation_id_var.set(conversation_id)
        background_tasks.add_task(
            handle_supplier_message,
            conversation_id,
            post_token,
            message.text,
        )
        return JSONResponse(status_code=200, content={"status": "ok"})

    return JSONResponse(status_code=200, content={"status": "ignored"})