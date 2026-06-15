from datetime import datetime

from pydantic import BaseModel
from typing import Optional, Dict, Any
from enum import Enum


class ConversationSchema(BaseModel):
    id: str
    type: str
    post_token: Optional[str] = None

class EventType(str, Enum):
    NEW_CHATBOT_MESSAGE = "NEW_CHATBOT_MESSAGE"

class SenderSchema(BaseModel):
    side: Optional[str] = None
    type: str


class NewChatbotMessageSchema(BaseModel):
    id: str
    conversation: ConversationSchema
    sender: SenderSchema
    type: str
    sent_at: datetime
    text: Optional[str] = None


class WebhookSchema(BaseModel):
    type: EventType
    metadata: Optional[Dict[str, Any]] = None
    new_chatbot_message: Optional[NewChatbotMessageSchema] = None