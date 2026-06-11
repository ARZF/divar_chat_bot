from contextlib import asynccontextmanager
from fastapi import FastAPI
from api.webhook import router as webhook_router
from api.oauth import router as oauth_router
import services.divar as divar_service
import httpx

@asynccontextmanager
async def lifespan(app: FastAPI):
    divar_service.client = httpx.AsyncClient(timeout=10)
    yield
    await divar_service.client.aclose()

app = FastAPI(lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(oauth_router)
