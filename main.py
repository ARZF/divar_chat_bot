import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from config import settings
from api.webhook import router as webhook_router
from api.oauth import router as oauth_router
from api.admin import router as admin_router
from api.auth import router as auth_router
from api.plans import router as plans_router
from api.seller import router as seller_router
from api.web import STATIC_DIR, router as web_router

from db.session import AsyncSessionLocal
from logging_config import setup_logging
from models.product import Product
import services.divar as divar_service
from services.price_lookup import refresh_lookup_cache
import httpx

logger = logging.getLogger("startup")


async def _warm_price_caches() -> None:
    """Warm the per-client price lookup caches on startup.

    Enumerates every client that has catalog data (``DISTINCT client_id`` from
    ``products``) and rebuilds its in-memory fuzzy index from the DB. A client
    with no products is intentionally skipped — there is nothing to warm.

    Failures here must NOT block app startup: the lazy-load fallback in
    ``services/chatbot.py`` populates any client that wasn't warmed (e.g. one
    that uploads a catalog after boot, or one missed due to a transient DB
    error here). On any exception we log and continue.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Product.client_id).distinct())
            client_ids = [row[0] for row in result.all()]
        for client_id in client_ids:
            async with AsyncSessionLocal() as db:
                await refresh_lookup_cache(db, client_id)
        logger.info(
            "price caches warmed at startup",
            extra={"client_count": len(client_ids)},
        )
    except Exception:
        logger.exception("failed to warm price caches at startup; "
                         "falling back to lazy load per client")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # One client shared by every function in services/divar.py. The connect timeout is
    # deliberately much tighter than the total: no Divar endpoint we call is expected to
    # have a slow TCP/TLS connect under normal operation, while a slow *response* is
    # plausible. Verified against send_message, get_conversation, get_user,
    # refresh_access_token and register_event_subscription — none override the timeout
    # per request, so all five inherit these values.
    divar_service.client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            settings.DIVAR_CLIENT_TOTAL_TIMEOUT_SECONDS,
            connect=settings.DIVAR_CLIENT_CONNECT_TIMEOUT_SECONDS,
        )
    )
    await _warm_price_caches()
    yield
    await divar_service.client.aclose()

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)
app.include_router(webhook_router)
app.include_router(oauth_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(plans_router)
app.include_router(seller_router)
app.include_router(web_router)

# Mounted under a dedicated prefix so it can never shadow an API route. The
# name="static" is what `url_for('static', path=...)` resolves in templates.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


