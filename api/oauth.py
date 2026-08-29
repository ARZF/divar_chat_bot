import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import find_or_create_client, issue_session
from config import settings
from db.session import get_db
from models.oauth_token import OAuthToken
import services.divar as divar_service

logger = logging.getLogger("oauth")

router = APIRouter()

# Phase 1 bootstrap tool — one-time manual token retrieval for local dev/debugging only.
# Renamed to /oauth/dev/* to avoid colliding with Phase 2 section 2.3's per-seller
# "Sign in with Divar" login routes, which now own /oauth/start and /oauth/callback.
# This tool is retired once 2.8 (seller auth) + 2.3 (OAuth login) are live end-to-end —
# see PLAN.md changelog.
_pending_state: str | None = None

# Real seller-login handshakes. This is deliberately separate from the single-state
# Phase 1 dev bootstrap variable above so concurrent sellers do not overwrite each
# other's state. States are short-lived, process-local handshake artifacts.
LOGIN_STATE_TTL_SECONDS = 10 * 60
_login_states: dict[str, float] = {}


def _remove_expired_login_states(now: float | None = None) -> None:
    """Lazily remove seller-login states whose 10-minute TTL has elapsed."""
    current_time = time.time() if now is None else now
    expired_states = [
        state for state, expires_at in _login_states.items()
        if expires_at <= current_time
    ]
    for state in expired_states:
        _login_states.pop(state, None)


@router.get("/oauth/start")
async def oauth_start() -> RedirectResponse:
    """Start the real seller-facing "Sign in with Divar" flow."""
    now = time.time()
    _remove_expired_login_states(now)

    state = secrets.token_urlsafe(32)
    _login_states[state] = now + LOGIN_STATE_TTL_SECONDS

    params = {
        "response_type": "code",
        "client_id": settings.DIVAR_APP_SLUG,
        "redirect_uri": settings.DIVAR_REDIRECT_URI,
        "scope": (
            "USER_PHONE USER_ID offline_access "
            "CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND "
            "CHAT_SUPPLIER_ALL_CONVERSATIONS_READ USER_POSTS_GET"
        ),
        "state": state,
    }
    auth_url = f"https://oauth.divar.ir/oauth2/auth?{urlencode(params)}"
    return RedirectResponse(url=auth_url)


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Complete seller login, persist Divar tokens, and issue the app session."""
    state = request.query_params.get("state")
    code = request.query_params.get("code")

    if not state:
        logger.warning("Seller OAuth callback rejected: missing state parameter")
        return JSONResponse(
            status_code=400, content={"detail": "Missing state parameter"}
        )

    _remove_expired_login_states()
    if state not in _login_states:
        logger.warning("Seller OAuth callback rejected: invalid or expired state")
        return JSONResponse(
            status_code=400, content={"detail": "Invalid state parameter"}
        )

    # Consume immediately after validation: a callback state is one-time use even if
    # the user denied consent or a downstream Divar request later fails.
    _login_states.pop(state, None)

    if not code:
        logger.warning("Seller OAuth callback rejected: authorization code missing")
        return JSONResponse(
            status_code=400,
            content={"detail": "Authorization code not provided"},
        )

    token_url = "https://oauth.divar.ir/oauth2/token"
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.DIVAR_APP_SLUG,
        "client_secret": settings.DIVAR_CLIENT_SECRET,
        "redirect_uri": settings.DIVAR_REDIRECT_URI,
    }
    try:
        token_response = await divar_service.client.post(token_url, data=token_payload)
        token_response.raise_for_status()
        token_data = token_response.json()
        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_in = int(token_data["expires_in"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        logger.warning("Seller OAuth token exchange failed", exc_info=True)
        return JSONResponse(
            status_code=502,
            content={"detail": "Divar OAuth token exchange failed"},
        )

    user = await divar_service.get_user(access_token)
    if user is None or not user.get("phone_number"):
        logger.warning(
            "Seller OAuth login rejected: phone number unavailable after user lookup"
        )
        return JSONResponse(
            status_code=403,
            content={
                "error": "phone_required",
                "message": (
                    "دسترسی به شماره تلفن الزامی است. لطفاً مجدداً با تأیید دسترسی "
                    "شماره تلفن وارد شوید."
                ),
            },
        )

    client = await find_or_create_client(
        db,
        phone_number=user["phone_number"],
        divar_user_id=user.get("user_id"),
    )

    token_result = await db.execute(
        select(OAuthToken).where(OAuthToken.client_id == client.id)
    )
    oauth_token = token_result.scalar_one_or_none()
    token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    if oauth_token is None:
        oauth_token = OAuthToken(
            client_id=client.id,
            divar_access_token=access_token,
            divar_refresh_token=refresh_token,
            token_expires_at=token_expires_at,
        )
        db.add(oauth_token)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            oauth_token = (
                await db.execute(
                    select(OAuthToken).where(OAuthToken.client_id == client.id)
                )
            ).scalar_one()
            oauth_token.divar_access_token = access_token
            oauth_token.divar_refresh_token = refresh_token
            oauth_token.token_expires_at = token_expires_at
            await db.commit()
    else:
        oauth_token.divar_access_token = access_token
        oauth_token.divar_refresh_token = refresh_token
        oauth_token.token_expires_at = token_expires_at
        await db.commit()

    try:
        await divar_service.register_event_subscription(access_token)
    except httpx.HTTPError:
        # Without a successful registration, this seller's NEW_MESSAGE events will
        # not arrive until registration succeeds; there is no automatic retry yet.
        logger.warning(
            "Seller event subscription registration failed",
            extra={"client_id": client.id},
            exc_info=True,
        )

    # Hand off to the web destination without ever exposing a token in the URL:
    # issue_session sets the existing HTTP-only Secure refresh cookie directly on
    # the redirect response (FastAPI does not merge cookies from an injected
    # Response parameter when a Response object is returned), and the browser then
    # recovers the access token via the existing POST /auth/refresh flow.
    redirect = RedirectResponse(url="/dashboard")
    await issue_session(db, client, redirect)
    return redirect


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
        "scope": "USER_PHONE USER_ID offline_access",
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