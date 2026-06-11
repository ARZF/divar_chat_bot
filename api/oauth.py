import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from config import settings

router = APIRouter()


@router.get("/oauth/callback")
async def oauth_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

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
    print(response_json)

    return JSONResponse(content=response_json)
