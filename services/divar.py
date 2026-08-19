import asyncio
import logging
import random
import httpx
from config import settings

logger = logging.getLogger("divar")

client: httpx.AsyncClient = None  # Set at startup via lifespan in main.py

BASE_URL = "https://open-api.divar.ir"
USER_URL = f"{BASE_URL}/v1/open-platform/users"

# --- Retry policy — send_supplier_message only ---
# Divar's API/CDN intermittently returns 502 for this endpoint. Only gateway-level
# statuses are retried: 500 means the upstream handled the request and failed, and
# 4xx (including 401/403/429) can never be fixed by repeating the same request.
# The v2 send-message endpoint (docs/chat/users_conversations.md) documents no
# idempotency key, so 504 is retried under an explicit duplicate-delivery risk —
# see _log_supplier_retry.
RETRYABLE_STATUS_CODES = {502, 503, 504}
# Transport errors where a usable response was never received. httpx.NetworkError
# is the parent of ConnectError/ReadError/WriteError/CloseError, so those subclasses
# are not repeated here. Timeouts are a separate hierarchy: ConnectTimeout and
# ReadTimeout are safe to retry, but PoolTimeout/WriteTimeout are not listed.
RETRYABLE_EXCEPTIONS = (
    httpx.NetworkError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)
MAX_RETRIES = 3
MAX_ATTEMPTS = MAX_RETRIES + 1
RETRY_BACKOFF_BASE = 1.0
RETRY_JITTER_MAX = 0.25
# Worst-case wall-clock budget for one send_supplier_message call, with the shared
# client's DIVAR_CLIENT_CONNECT_TIMEOUT_SECONDS=5 / DIVAR_CLIENT_TOTAL_TIMEOUT_SECONDS=15
# defaults (main.py builds the httpx.Timeout; httpx applies it per phase, not as a total):
#   backoff  = delay(0) + delay(1) + delay(2) = (1 + 2 + 4) + 3 × jitter ≤ 7.75s
#   attempts = 4 × 15s if every attempt hangs waiting to read a response  = 60s
#   → ≤ ~68s worst case; ≤ ~28s for the connect-timeout case (4 × 5s + backoff).
# Before the 2026-08-19 fix the client used a flat 60s for all four phases, so a
# connect-timeout cycle cost 4 × 60s + backoff ≈ 4 minutes — the observed incident.
# Raising MAX_RETRIES or either timeout multiplies this; keep it well under whatever
# window the caller (a BackgroundTask) is expected to finish in.


def _api_key_headers() -> dict:
    """For endpoints that authenticate via X-Api-Key only (send_message, get_conversation)."""
    return {
        "X-API-Key": settings.DIVAR_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def _oauth_headers(access_token: str) -> dict:
    """For endpoints that need both X-Api-Key and OAuth Bearer token (e.g. get_user)."""
    return {
        "X-API-Key": settings.DIVAR_API_KEY,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def get_user(access_token: str) -> dict | None:
    """Return the OAuth user's phone number and per-app Divar user ID.

    The two fields are independently conditional on the scopes granted by the user.
    Phone parsing follows the live API shape while remaining compatible with the older
    documented ``phone_numbers`` array. Lookup failures are intentionally converted to
    ``None`` so the login callback can decide how authentication should fail.
    """
    try:
        response = await client.get(USER_URL, headers=_oauth_headers(access_token))
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("Divar OAuth user lookup failed", exc_info=True)
        return None

    if not isinstance(payload, dict):
        logger.warning("Divar OAuth user lookup returned an invalid response shape")
        return None

    phone_number = payload.get("phone_number")
    if not isinstance(phone_number, str) or not phone_number.strip():
        phone_number = None
        phone_numbers = payload.get("phone_numbers")
        if isinstance(phone_numbers, list):
            phone_number = next(
                (
                    candidate.strip()
                    for candidate in phone_numbers
                    if isinstance(candidate, str) and candidate.strip()
                ),
                None,
            )
    else:
        phone_number = phone_number.strip()

    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        user_id = None
    else:
        user_id = user_id.strip()

    return {"phone_number": phone_number, "user_id": user_id}


async def get_user_phone_number(access_token: str) -> str | None:
    """Return only the OAuth user's phone number, preserving section 2.3's API."""
    user = await get_user(access_token)
    return user["phone_number"] if user is not None else None


async def refresh_access_token(
    current_access_token: str,
    refresh_token: str,
) -> tuple[str, str, int]:
    """Exchange a seller's refresh token for a fresh access/refresh token pair.

    Both tokens must belong to the same seller: Divar rotates the refresh token on
    every call, so passing a refresh token that does not match the caller's stored
    credentials would overwrite that seller's row with another identity's tokens.
    ``code`` carries the current access token per ``docs/oauth/ReadMe.md`` step 5.
    """
    response = await client.post(
        "https://oauth.divar.ir/oauth2/token",
        data={
            "code": current_access_token,
            "client_id": settings.DIVAR_APP_SLUG,
            "client_secret": settings.DIVAR_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "redirect_uri": settings.DIVAR_REDIRECT_URI,
            "refresh_token": refresh_token,
        }
    )
    response.raise_for_status()
    token_data = response.json()
    return (
        token_data["access_token"],
        token_data["refresh_token"],
        int(token_data["expires_in"]),
    )


async def send_message(conversation_id: str, text: str) -> bool:
    url = f"{BASE_URL}/v1/open-platform/chat/bot/conversations/{conversation_id}/messages"
    payload = {"type": "TEXT", "text_message": text}

    response = await client.post(url, headers=_api_key_headers(), json=payload)

    # NOTE: This endpoint authenticates via X-Api-Key, not OAuth.
    # A 401/403 here means the API key is invalid — refreshing an OAuth
    # token cannot fix it. Do not auto-refresh; let the error propagate.

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        if response.status_code in (401, 403):
            logger.error(
                "send_message auth failed — DIVAR_API_KEY is invalid or missing required scope. "
                "Check DIVAR_API_KEY in .env",
                extra={"status_code": response.status_code, "response_body": response.text}
            )
        else:
            logger.error("send_message failed", extra={
                "status_code": response.status_code,
                "response_body": response.text
            })
        raise

    logger.debug("send_message succeeded", extra={"status_code": response.status_code})
    return True


def _supplier_retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter, so concurrent senders do not retry in lockstep."""
    return RETRY_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, RETRY_JITTER_MAX)


async def send_supplier_message(
    conversation_id: str, text: str, access_token: str
) -> bool:
    """Send a seller-authorized message, retrying only transient gateway failures.

    Token refresh stays in ``chatbot.handle_post_bot_reply`` — a 401 here is never
    retried or refreshed. Bounded at ``MAX_ATTEMPTS`` because this endpoint has a real
    send side effect and Divar documents no idempotency key.
    """
    url = f"{BASE_URL}/v2/open-platform/conversations/{conversation_id}/messages"
    payload = {"type": "TEXT", "message": text}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.post(
                url,
                headers=_oauth_headers(access_token),
                json=payload,
            )

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt < MAX_ATTEMPTS:
                    delay = _supplier_retry_delay(attempt - 1)
                    # 504 is called out separately: the upstream may have already
                    # delivered the message before the gateway gave up waiting, so a
                    # retry can duplicate it. Greppable apart from ordinary 502/503.
                    message = (
                        "supplier message retrying 504 - possible duplicate delivery risk"
                        if response.status_code == 504
                        else "supplier message attempt failed; retrying"
                    )
                    logger.warning(
                        message,
                        extra={
                            "status_code": response.status_code,
                            "response_body": response.text,
                            "conversation_id": conversation_id,
                            "attempt": attempt,
                            "max_attempts": MAX_ATTEMPTS,
                            "delay_seconds": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error(
                    "supplier message send exhausted retries",
                    extra={
                        "status_code": response.status_code,
                        "response_body": response.text,
                        "conversation_id": conversation_id,
                        "attempts": MAX_ATTEMPTS,
                    },
                )
                # Always raises: the status is one of RETRYABLE_STATUS_CODES.
                response.raise_for_status()

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error(
                    "send_supplier_message failed",
                    extra={
                        "status_code": response.status_code,
                        "response_body": response.text,
                    },
                )
                raise

            logger.debug(
                "send_supplier_message succeeded",
                extra={"status_code": response.status_code},
            )
            return True

        except RETRYABLE_EXCEPTIONS as exc:
            if attempt < MAX_ATTEMPTS:
                delay = _supplier_retry_delay(attempt - 1)
                logger.warning(
                    "supplier message network error; retrying",
                    extra={
                        "conversation_id": conversation_id,
                        "attempt": attempt,
                        "max_attempts": MAX_ATTEMPTS,
                        "delay_seconds": delay,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(delay)
                continue

            logger.error(
                "supplier message send exhausted retries",
                extra={
                    "conversation_id": conversation_id,
                    "attempts": MAX_ATTEMPTS,
                    "error": str(exc),
                },
            )
            raise

    raise RuntimeError("send_supplier_message retry loop exited without a result")


async def register_event_subscription(access_token: str) -> bool:
    url = f"{BASE_URL}/v1/open-platform/events/subscriptions"
    payload = {"event_type": "NEW_MESSAGE_ON_POST"}

    response = await client.post(
        url,
        headers=_oauth_headers(access_token),
        json=payload,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        logger.error(
            "register_event_subscription failed",
            extra={
                "status_code": response.status_code,
                "response_body": response.text,
            },
        )
        raise

    logger.debug(
        "register_event_subscription succeeded",
        extra={"status_code": response.status_code},
    )
    return True


async def get_conversation(conversation_id: str) -> dict:
    url = f"{BASE_URL}/v1/open-platform/chat/conversations/{conversation_id}"
    response = await client.get(url, headers=_api_key_headers())

    # NOTE: This endpoint authenticates via X-Api-Key, not OAuth.
    # A 401/403 here means the API key is invalid — refreshing an OAuth
    # token cannot fix it. Do not auto-refresh; let the error propagate.

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        if response.status_code in (401, 403):
            logger.error(
                "get_conversation auth failed — DIVAR_API_KEY is invalid or missing required scope. "
                "Check DIVAR_API_KEY in .env",
                extra={"status_code": response.status_code, "response_body": response.text}
            )
        else:
            logger.error("get_conversation failed", extra={
                "status_code": response.status_code, "response_body": response.text
            })
        raise

    logger.debug("get_conversation succeeded", extra={"status_code": response.status_code})
    return response.json()
