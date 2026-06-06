from pydantic import BaseModel
from typing import Optional, Dict, Any


class ConversationSchema(BaseModel):
    id: str
    type: str
    post_token: Optional[str] = None


class SenderSchema(BaseModel):
    side: str
    type: str


class NewChatbotMessageSchema(BaseModel):
    id: str
    conversation: ConversationSchema
    sender: SenderSchema
    type: str
    sent_at: int
    text: str


class WebhookSchema(BaseModel):
    type: str
    metadata: Optional[Dict[str, Any]] = None
    new_chatbot_message: Optional[NewChatbotMessageSchema] = None