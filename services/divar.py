import httpx
from config import settings


class DivarService:
    BASE_URL = "https://open-api.divar.ir"

    def __init__(self):
        self.headers = {
            "X-API-Key": settings.DIVAR_API_KEY,
            "Authorization": f"Bearer {settings.DIVAR_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def send_message(
        self,
        conversation_id: str,
        message: str,
    ) -> dict:
        """ارسال پیام به مکالمه"""
        url = (
            f"{self.BASE_URL}"
            f"/v2/open-platform/conversations"
            f"/{conversation_id}/messages"
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self.headers,
                json={"message": message},
                timeout=10,
            )
        response.raise_for_status()
        return response.json()

    async def get_conversation(
        self,
        conversation_id: str,
    ) -> dict:
        """دریافت اطلاعات مکالمه"""
        url = (
            f"{self.BASE_URL}"
            f"/v1/open-platform/chat/conversations"
            f"/{conversation_id}"
        )
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self.headers,
                timeout=10,
            )
        response.raise_for_status()
        return response.json()