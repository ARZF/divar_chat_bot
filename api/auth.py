"""Seller authentication (section 2.8): OTP-to-phone login, session issuance, and the
shared auth dependency used by seller-facing endpoints.

Two login paths converge here: OTP-to-phone (implemented in this module) and
"Sign in with Divar" (OAuth — section 2.3, not implemented here). Both resolve a
`clients` row by phone number (`find_or_create_client`) and issue the same JWT +
refresh-token session (`issue_session`).

Security (PLAN.md 2.8):
- OTP codes are HMAC-SHA256 hashed at rest with `OTP_HMAC_KEY`; never logged/returned.
- App refresh tokens are SHA-256 hashed at rest; never logged; cookie-only, never in a body.
- JWT secret / OTP HMAC key live in `.env` only, never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.session import get_db
from models.client import Client
from models.otp_code import OTPCode
from models.refresh_token import RefreshToken
from schemas.auth import (
    MeResponse,
    MessageResponse,
    OTPRequestBody,
    OTPVerifyBody,
    TokenResponse,
)
from services.sms import SMSService, get_sms_service

logger = logging.getLogger("auth")

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_otp(code: str) -> str:
    """HMAC-SHA256 hex digest of an OTP code, keyed with OTP_HMAC_KEY."""
    return hmac.new(
        settings.OTP_HMAC_KEY.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest of an app refresh token (stored at rest, never plaintext)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _access_token_expires_in() -> int:
    """Access-token lifetime in seconds, derived from settings (never hardcoded)."""
    return settings.ACCESS_TOKEN_LIFETIME_MINUTES * 60


def _generate_otp_code() -> str:
    """Generate a random numeric OTP of length OTP_LENGTH (zero-padded)."""
    upper = 10 ** settings.OTP_LENGTH
    return str(secrets.randbelow(upper)).zfill(settings.OTP_LENGTH)


async def find_or_create_client(
    db: AsyncSession,
    phone_number: str,
    divar_user_id: str | None = None,
) -> Client:
    """Merge-by-phone. `phone_number` is the sole merge key.

    1. SELECT clients WHERE phone_number = :phone_number
    2. If found: backfill divar_user_id if it was null and we now have one. Return row.
    3. If not found: INSERT. On UNIQUE(phone_number) violation from a concurrent insert,
       roll back and re-SELECT the winning row.
    """
    result = await db.execute(
        select(Client).where(Client.phone_number == phone_number)
    )
    client = result.scalar_one_or_none()

    if client is not None:
        if divar_user_id and client.divar_user_id is None:
            client.divar_user_id = divar_user_id
        await db.commit()
        await db.refresh(client)
        return client

    client = Client(phone_number=phone_number, divar_user_id=divar_user_id)
    db.add(client)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent insert won the UNIQUE(phone_number) race — retry as a SELECT.
        await db.rollback()
        result = await db.execute(
            select(Client).where(Client.phone_number == phone_number)
        )
        client = result.scalar_one()
        if divar_user_id and client.divar_user_id is None:
            client.divar_user_id = divar_user_id
            await db.commit()
            await db.refresh(client)
        return client

    await db.refresh(client)
    return client


async def issue_session(
    db: AsyncSession, client: Client, response: Response
) -> dict:
    """Issue a JWT access token + a DB-stored refresh token (cookie).

    - JWT payload {"client_id", "exp"}, signed HS256 with JWT_SECRET_KEY.
    - Random 64-byte refresh token; SHA-256 hash stored in refresh_tokens.
    - Refresh token set as HTTP-only Secure cookie (SameSite=Lax, path=/auth).
    - Returns {"access_token", "expires_in"}.
    """
    expires_in = _access_token_expires_in()
    payload = {
        "client_id": client.id,
        "exp": _now() + timedelta(minutes=settings.ACCESS_TOKEN_LIFETIME_MINUTES),
    }
    access_token = jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )

    refresh_token = secrets.token_urlsafe(64)
    db.add(
        RefreshToken(
            client_id=client.id,
            token_hash=_hash_refresh_token(refresh_token),
            expires_at=_now() + timedelta(days=settings.REFRESH_TOKEN_LIFETIME_DAYS),
        )
    )
    await db.commit()

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.REFRESH_TOKEN_LIFETIME_DAYS * 24 * 60 * 60,
    )

    return {"access_token": access_token, "expires_in": expires_in}


async def get_current_client_id(
    authorization: str | None = Header(default=None),
) -> int:
    """Extract and validate the Bearer JWT; return the client_id claim.

    Raises HTTPException(401) if the token is missing, malformed, expired, or invalid.
    JWT-only — does not check that the client still exists in the DB (see Future
    Improvements: deleted-client edge case).
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    client_id = payload.get("client_id")
    if client_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return int(client_id)


# --------------------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------------------

@router.post("/otp/request", response_model=MessageResponse)
async def request_otp(
    body: OTPRequestBody,
    db: AsyncSession = Depends(get_db),
    sms: SMSService = Depends(get_sms_service),
) -> MessageResponse:
    """Generate, store (hashed), and send an OTP for the given phone number."""
    phone = body.phone_number
    now = _now()

    # Rate limit: reject if the most recent OTP for this phone is within the cooldown.
    latest = await db.execute(
        select(OTPCode)
        .where(OTPCode.phone_number == phone)
        .order_by(OTPCode.created_at.desc())
        .limit(1)
    )
    latest_otp = latest.scalar_one_or_none()
    if latest_otp is not None:
        created_at = latest_otp.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        elapsed = (now - created_at).total_seconds()
        if elapsed < settings.OTP_REQUEST_COOLDOWN_SECONDS:
            raise HTTPException(
                status_code=429,
                detail="Too many OTP requests. Please wait before requesting again.",
            )

    # Only one active OTP per phone — remove any previous rows for this phone.
    existing = await db.execute(
        select(OTPCode).where(OTPCode.phone_number == phone)
    )
    for row in existing.scalars().all():
        await db.delete(row)

    code = _generate_otp_code()
    otp = OTPCode(
        phone_number=phone,
        code_hash=_hash_otp(code),
        expires_at=now + timedelta(minutes=settings.OTP_LIFETIME_MINUTES),
        attempts=0,
    )
    db.add(otp)
    await db.commit()

    # Send via the abstract SMS service. On failure the OTP must not remain active.
    try:
        await sms.send_otp(phone, code)
    except Exception:
        logger.warning("OTP SMS delivery failed; invalidating OTP", extra={})
        await db.delete(otp)
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "error": "sms_unavailable",
                "message": "Unable to send OTP. Please try again later.",
            },
        )

    # Do not disclose whether the phone number is registered (prevents enumeration).
    return MessageResponse(message="OTP sent")


@router.post("/otp/verify", response_model=TokenResponse)
async def verify_otp(
    body: OTPVerifyBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Verify an OTP, merge-by-phone, and issue a session."""
    phone = body.phone_number
    now = _now()

    result = await db.execute(
        select(OTPCode)
        .where(OTPCode.phone_number == phone, OTPCode.expires_at > now)
        .order_by(OTPCode.created_at.desc())
        .limit(1)
    )
    otp = result.scalar_one_or_none()

    if otp is None or otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    otp.attempts += 1
    await db.commit()

    expected_hash = otp.code_hash
    provided_hash = _hash_otp(body.code)
    if not hmac.compare_digest(expected_hash, provided_hash):
        # Do not distinguish "wrong code" from "expired".
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    # Success — consume the OTP, merge the client, issue the session.
    await db.delete(otp)
    await db.commit()

    client = await find_or_create_client(db, phone_number=phone)
    session = await issue_session(db, client, response)
    return TokenResponse(**session)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_session(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> TokenResponse:
    """Rotate the refresh token (read from the HTTP-only cookie) and issue a new JWT."""
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    now = _now()
    token_hash = _hash_refresh_token(refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.expires_at > now,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Rotate: delete the old row, then issue a fresh session (new token + cookie + JWT).
    client_id = row.client_id
    await db.delete(row)
    await db.commit()

    client_result = await db.execute(select(Client).where(Client.id == client_id))
    client = client_result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=401, detail="Client not found")

    session = await issue_session(db, client, response)
    return TokenResponse(**session)


@router.post("/logout")
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> Response:
    """Delete the session's refresh token (if any) and clear the cookie."""
    if refresh_token:
        token_hash = _hash_refresh_token(refresh_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await db.delete(row)
            await db.commit()

    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    response.status_code = 200
    return response



@router.get("/me", response_model=MeResponse)
async def me(
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=401, detail="Client not found")
    return MeResponse(
        id=client.id,
        phone_number=client.phone_number,
        divar_user_id=client.divar_user_id,
        created_at=client.created_at,
    )
