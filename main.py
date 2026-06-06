from fastapi import FastAPI
from api.webhook import router as webhook_router
from bot import get_reply
from services.divar import send_message

app = FastAPI()

app.include_router(webhook_router)