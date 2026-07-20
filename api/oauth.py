import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config import settings
import services.divar as divar_service

logger = logging.getLogger("oauth")

router = APIRouter()

# Phase 1 bootstrap tool — one-time manual token retrieval for local dev/debugging only.
# Renamed to /oauth/dev/* to avoid colliding with Phase 2 section 2.3's per-seller
# "Sign in with Divar" login routes, which now own /oauth/start and /oauth/callback.
# This tool is retired once 2.8 (seller auth) + 2.3 (OAuth login) are live end-to-end —
# see PLAN.md changelog.
_pending_state: str | None = None


@router.get("/oauth/dev/start")
async def oauth_dev_start():
    """Generate a random state, store it in-memory, and return the authorization URL.

    One-time manual bootstrap tool — NOT the seller login flow (see section 2.3/2.8
    for that). Used only for local dev/debugging of OAuth-scoped endpoints.
    """
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
    logger.info("Dev OAuth bootstrap flow started — visit the authorization URL to proceed")
    return JSONResponse(content={"authorization_url": auth_url})


@router.get("/oauth/dev/callback")
async def oauth_dev_callback(request: Request):
    """One-time manual bootstrap callback — prints the raw token response for the
    developer to copy by hand. NOT the seller login flow (see section 2.3/2.8).
    """
    global _pending_state

    state = request.query_params.get("state")
    code = request.query_params.get("code")

    # 1.B2: Reject if state is missing
    if not state:
        logger.warning("Dev OAuth callback rejected: missing state parameter")
        return JSONResponse(
            status_code=400, content={"detail": "Missing state parameter"}
        )

    # 1.B2: Validate state against the value generated at /oauth/dev/start
    if _pending_state is None or state != _pending_state:
        logger.warning("Dev OAuth callback rejected: state mismatch")
        return JSONResponse(
            status_code=400, content={"detail": "Invalid state parameter"}
        )

    # Clear state after successful validation (one-time use — prevents replay)
    _pending_state = None

    # If code is missing, the user denied permission
    if not code:
        logger.warning("Dev OAuth callback: authorization code not provided")
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

    response = await divar_service.client.post(token_url, data=payload)

    response_json = response.json()
    logger.info(
        "Dev OAuth token exchange completed",
        extra={"status_code": response.status_code},
    )

    return JSONResponse(content=response_json)