import logging
import httpx
from config import settings

logger = logging.getLogger("divar")

client: httpx.AsyncClient = None  # Set at startup via lifespan in main.py

BASE_URL = "https://open-api.divar.ir"
USER_URL = f"{BASE_URL}/v1/open-platform/users"


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
) -> tuple[str, str, int]:
    response = await client.post(
        "https://oauth.divar.ir/oauth2/token",
        data={
            "code": current_access_token,
            "client_id": settings.DIVAR_APP_SLUG,
            "client_secret": settings.DIVAR_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "redirect_uri": settings.DIVAR_REDIRECT_URI,
            "refresh_token": settings.DIVAR_REFRESH_TOKEN,
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


async def send_supplier_message(
    conversation_id: str, text: str, access_token: str
) -> bool:
    url = f"{BASE_URL}/v2/open-platform/conversations/{conversation_id}/messages"
    payload = {"type": "TEXT", "message": text}

    response = await client.post(
        url,
        headers=_oauth_headers(access_token),
        json=payload,
    )
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
