import logging
import httpx
from config import settings

logger = logging.getLogger("divar")

client: httpx.AsyncClient = None  # Set at startup via lifespan in main.py

BASE_URL = "https://open-api.divar.ir"


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


async def refresh_access_token(current_access_token: str) -> tuple[str, str]:
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
    return token_data["access_token"], token_data["refresh_token"]


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
                "This endpoint uses X-Api-Key, NOT OAuth. Check DIVAR_API_KEY in .env",
                extra={"status_code": response.status_code, "response_body": response.text}
            )
        else:
            logger.error("send_message failed", extra={
                "status_code": response.status_code,
                "response_body": response.text
            })
        raise

    logger.info("send_message succeeded", extra={"status_code": response.status_code})
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
                "This endpoint uses X-Api-Key, NOT OAuth. Check DIVAR_API_KEY in .env",
                extra={"status_code": response.status_code, "response_body": response.text}
            )
        else:
            logger.error("get_conversation failed", extra={
                "status_code": response.status_code, "response_body": response.text
            })
        raise

    logger.info("get_conversation succeeded", extra={"status_code": response.status_code})
    return response.json()
