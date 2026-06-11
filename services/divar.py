import httpx
from config import settings

client: httpx.AsyncClient = None  # Set at startup via lifespan in main.py

BASE_URL = "https://open-api.divar.ir"


def _headers() -> dict:
    return {
        "X-API-Key": settings.DIVAR_API_KEY,
        "Authorization": f"Bearer {settings.DIVAR_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def refresh_access_token() -> str:
    response = await client.post(
        "https://oauth.divar.ir/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": settings.DIVAR_REFRESH_TOKEN,
            "client_id": settings.DIVAR_CLIENT_ID,
            "client_secret": settings.DIVAR_CLIENT_SECRET,
        }
    )
    response.raise_for_status()
    return response.json()["access_token"]


async def send_message(conversation_id: str, text: str) -> bool:
    url = f"{BASE_URL}/v1/open-platform/chat/bot/conversations/{conversation_id}/messages"
    payload = {"text_message": text}

    response = await client.post(url, headers=_headers(), json=payload)

    if response.status_code == 401:
        settings.DIVAR_ACCESS_TOKEN = await refresh_access_token()
        response = await client.post(url, headers=_headers(), json=payload)

    response.raise_for_status()
    return True


async def get_conversation(conversation_id: str) -> dict:
    url = f"{BASE_URL}/v1/open-platform/chat/conversations/{conversation_id}"
    response = await client.get(url, headers=_headers())

    if response.status_code == 401:
        settings.DIVAR_ACCESS_TOKEN = await refresh_access_token()
        response = await client.get(url, headers=_headers())

    response.raise_for_status()
    return response.json()