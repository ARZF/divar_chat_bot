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

async def send_message(conversation_id: str, text: str) -> bool:
    url = f"{BASE_URL}/v2/open-platform/conversations/{conversation_id}/messages"
    response = await client.post(url, headers=_headers(), json={"message": text})
    response.raise_for_status()
    return True

async def get_conversation(conversation_id: str) -> dict:
    url = f"{BASE_URL}/v1/open-platform/chat/conversations/{conversation_id}"
    response = await client.get(url, headers=_headers())
    response.raise_for_status()
    return response.json()
