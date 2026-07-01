import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config import settings

logger = logging.getLogger("oauth")

router = APIRouter()

# Phase 1: single in-memory state for the one-time bootstrap flow.
# Phase 2 (section 2.3) will replace this with per-client state storage.
_pending_state: str | None = None


@router.get("/oauth/start")
async def oauth_start():
    """Generate a random state, store it in-memory, and return the authorization URL."""
    global _pending_state
    _pending_state = secrets.token_urlsafe(32)

    params = {
        "response_type": "code",
        "client_id": settings.DIVAR_APP_SLUG,
        "redirect_uri": settings.DIVAR_REDIRECT_URI,
        "scope": "offline_access",
        "state": _pending_state,
    }
    auth_url = f"https://oauth.divar.ir/oauth2/auth?{urlencode(params)}"
    logger.info("OAuth flow started — visit the authorization URL to proceed")
    return JSONResponse(content={"authorization_url": auth_url})


@router.get("/oauth/callback")
async def oauth_callback(request: Request):
    global _pending_state

    state = request.query_params.get("state")
    code = request.query_params.get("code")

    # 1.B2: Reject if state is missing
    if not state:
        logger.warning("OAuth callback rejected: missing state parameter")
        return JSONResponse(
            status_code=400, content={"detail": "Missing state parameter"}
        )

    # 1.B2: Validate state against the value generated at /oauth/start
    if _pending_state is None or state != _pending_state:
        logger.warning("OAuth callback rejected: state mismatch")
        return JSONResponse(
            status_code=400, content={"detail": "Invalid state parameter"}
        )

    # Clear state after successful validation (one-time use — prevents replay)
    _pending_state = None

    # If code is missing, the user denied permission
    if not code:
        logger.warning("OAuth callback: authorization code not provided")
        return JSONResponse(
            status_code=400, content={"detail": "Authorization code not provided"}
        )

    token_url = "https://oauth.divar.ir/oauth2/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.DIVAR_APP_SLUG,
        "client_secret": settings.DIVAR_CLIENT_SECRET,
        "redirect_uri": settings.DIVAR_REDIRECT_URI,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(token_url, data=payload)

    response_json = response.json()
    logger.info(
        "OAuth token exchange completed",
        extra={"status_code": response.status_code},
    )

    return JSONResponse(content=response_json)
