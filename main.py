from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.webhook import router as webhook_router
from api.oauth import router as oauth_router
from api.admin import router as admin_router
from api.auth import router as auth_router
from api.seller import router as seller_router

from logging_config import setup_logging
import services.divar as divar_service
import httpx

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    divar_service.client = httpx.AsyncClient(timeout=60)
    yield
    await divar_service.client.aclose()

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.include_router(webhook_router)
app.include_router(oauth_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(seller_router)


