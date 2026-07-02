import os

# Set test env vars before any project imports — config.py instantiates Settings at module level
os.environ.setdefault("DIVAR_API_KEY", "test_api_key")
os.environ.setdefault("DIVAR_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("DIVAR_REFRESH_TOKEN", "test_refresh_token")
os.environ.setdefault("DIVAR_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("DIVAR_IDENTIFICATION_KEY", "test_identification_key")
os.environ.setdefault("DIVAR_APP_SLUG", "test_app_slug")
os.environ.setdefault("DIVAR_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("DIVAR_REDIRECT_URI", "https://example.com/callback")
os.environ.setdefault("admin_token", "test_admin_token")

import json
import pytest
import httpx
import respx
from urllib.parse import parse_qs
from unittest.mock import AsyncMock

from services import divar
from config import settings

SEND_MSG_URL = (
    "https://open-api.divar.ir/v1/open-platform/chat/bot/conversations/{conv_id}/messages"
)
GET_CONV_URL = "https://open-api.divar.ir/v1/open-platform/chat/conversations/{conv_id}"
TOKEN_URL = "https://oauth.divar.ir/oauth2/token"


@pytest.fixture(autouse=True)
def mock_settings(mocker):
    mocker.patch.object(settings, "DIVAR_API_KEY", "test_api_key")
    mocker.patch.object(settings, "DIVAR_ACCESS_TOKEN", "test_access_token")
    mocker.patch.object(settings, "DIVAR_REFRESH_TOKEN", "test_refresh_token")
    mocker.patch.object(settings, "DIVAR_APP_SLUG", "test_app_slug")
    mocker.patch.object(settings, "DIVAR_CLIENT_SECRET", "test_client_secret")
    mocker.patch.object(settings, "DIVAR_REDIRECT_URI", "https://example.com/callback")


@pytest.fixture
def httpx_mock():
    with respx.mock(assert_all_called=False) as router:
        divar.client = httpx.AsyncClient()
        yield router


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_success(httpx_mock):
    url = SEND_MSG_URL.format(conv_id="conv_123")
    route = httpx_mock.post(url).respond(200, json={"status": "ok"})

    result = await divar.send_message("conv_123", "Hello Divar!")

    assert result is True
    assert route.called

    request = route.calls[0].request
    # X-Api-Key is the correct auth header per Divar docs for this endpoint
    assert request.headers["x-api-key"] == "test_api_key"

    body = json.loads(request.content)
    assert body == {"type": "TEXT", "text_message": "Hello Divar!"}


@pytest.mark.asyncio
async def test_send_message_non_200_raises(httpx_mock):
    url = SEND_MSG_URL.format(conv_id="conv_123")
    httpx_mock.post(url).respond(400, text="Bad Request")

    with pytest.raises(httpx.HTTPStatusError):
        await divar.send_message("conv_123", "Hello")


@pytest.mark.asyncio
async def test_send_message_500_raises(httpx_mock):
    url = SEND_MSG_URL.format(conv_id="conv_123")
    httpx_mock.post(url).respond(500, text="Internal Server Error")

    with pytest.raises(httpx.HTTPStatusError):
        await divar.send_message("conv_123", "Hello")


@pytest.mark.asyncio
async def test_send_message_401_raises_without_refresh(httpx_mock, mocker):
    """401 from X-Api-Key auth means the API key is wrong — no OAuth refresh attempted."""
    url = SEND_MSG_URL.format(conv_id="conv_123")
    httpx_mock.post(url).respond(401, text="Unauthorized")
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar.send_message("conv_123", "Hello")

    mock_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_403_raises_without_refresh(httpx_mock, mocker):
    """403 from X-Api-Key auth means the API key lacks permission — no OAuth refresh attempted."""
    url = SEND_MSG_URL.format(conv_id="conv_123")
    httpx_mock.post(url).respond(403, text="Forbidden")
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar.send_message("conv_123", "Hello")

    mock_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_401_logs_api_key_error(httpx_mock, caplog):
    """401 must log a clear message pointing at DIVAR_API_KEY in .env."""
    url = SEND_MSG_URL.format(conv_id="conv_123")
    httpx_mock.post(url).respond(401, text="Unauthorized")

    with pytest.raises(httpx.HTTPStatusError):
        await divar.send_message("conv_123", "Hello")

    assert any("DIVAR_API_KEY" in record.message for record in caplog.records)
    assert any("X-Api-Key" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# get_conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_conversation_success(httpx_mock):
    url = GET_CONV_URL.format(conv_id="conv_123")
    route = httpx_mock.get(url).respond(200, json={"id": "conv_123", "messages": []})

    result = await divar.get_conversation("conv_123")

    assert result == {"id": "conv_123", "messages": []}
    assert route.called

    request = route.calls[0].request
    assert request.headers["x-api-key"] == "test_api_key"


@pytest.mark.asyncio
async def test_get_conversation_non_200_raises(httpx_mock):
    url = GET_CONV_URL.format(conv_id="conv_123")
    httpx_mock.get(url).respond(500, text="Internal Server Error")

    with pytest.raises(httpx.HTTPStatusError):
        await divar.get_conversation("conv_123")


@pytest.mark.asyncio
async def test_get_conversation_401_raises_without_refresh(httpx_mock, mocker):
    """401 from X-Api-Key auth means the API key is wrong — no OAuth refresh attempted."""
    url = GET_CONV_URL.format(conv_id="conv_123")
    httpx_mock.get(url).respond(401, text="Invalid access token")
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar.get_conversation("conv_123")

    mock_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_conversation_403_raises_without_refresh(httpx_mock, mocker):
    """403 from X-Api-Key auth means the API key lacks permission — no OAuth refresh attempted."""
    url = GET_CONV_URL.format(conv_id="conv_123")
    httpx_mock.get(url).respond(403, text="Forbidden")
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar.get_conversation("conv_123")

    mock_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_conversation_401_logs_api_key_error(httpx_mock, caplog):
    """401 must log a clear message pointing at DIVAR_API_KEY in .env."""
    url = GET_CONV_URL.format(conv_id="conv_123")
    httpx_mock.get(url).respond(401, text="Unauthorized")

    with pytest.raises(httpx.HTTPStatusError):
        await divar.get_conversation("conv_123")

    assert any("DIVAR_API_KEY" in record.message for record in caplog.records)
    assert any("X-Api-Key" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# refresh_access_token — bug 1.B1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_access_token_correct_post_fix_behavior(httpx_mock):
    """
    Post-fix behavior per PLAN.md 1.B1 and docs/oauth/ReadMe.md step 5:
    - Request body includes `code` (current access token), `redirect_uri`,
      `client_id` (=DIVAR_APP_SLUG), `client_secret`, `grant_type=refresh_token`,
      `refresh_token`
    - Returns a tuple of (new_access_token, new_refresh_token)
    """
    route = httpx_mock.post(TOKEN_URL).respond(
        200,
        json={
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
        },
    )

    result = await divar.refresh_access_token(settings.DIVAR_ACCESS_TOKEN)

    assert result == ("new_access_token", "new_refresh_token")
    assert route.called
    request = route.calls[0].request
    body = parse_qs(request.content.decode())

    assert body["code"] == ["test_access_token"]
    assert body["redirect_uri"] == ["https://example.com/callback"]
    assert body["client_id"] == ["test_app_slug"]
    assert body["client_secret"] == ["test_client_secret"]
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["test_refresh_token"]
