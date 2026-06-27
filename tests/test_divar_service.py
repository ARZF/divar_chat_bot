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
async def test_send_message_401_triggers_refresh_and_retry(httpx_mock, mocker):
    url = SEND_MSG_URL.format(conv_id="conv_123")
    # First call returns 401, second returns 200
    route = httpx_mock.post(url)
    route.side_effect = [
        httpx.Response(401),
        httpx.Response(200, json={"status": "ok"}),
    ]
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock, return_value="new_token"
    )

    result = await divar.send_message("conv_123", "Hello")

    assert result is True
    mock_refresh.assert_awaited_once()
    assert settings.DIVAR_ACCESS_TOKEN == "new_token"


@pytest.mark.asyncio
async def test_send_message_403_triggers_refresh_and_retry(httpx_mock, mocker):
    url = SEND_MSG_URL.format(conv_id="conv_123")
    route = httpx_mock.post(url)
    route.side_effect = [
        httpx.Response(403),
        httpx.Response(200, json={"status": "ok"}),
    ]
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock, return_value="new_token"
    )

    result = await divar.send_message("conv_123", "Hello")

    assert result is True
    mock_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_retry_exactly_once(httpx_mock, mocker):
    """If the retried request also fails, the error propagates — no infinite retry loop."""
    url = SEND_MSG_URL.format(conv_id="conv_123")
    route = httpx_mock.post(url)
    route.side_effect = [
        httpx.Response(401),
        httpx.Response(401),
    ]
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock, return_value="new_token"
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar.send_message("conv_123", "Hello")

    # refresh called exactly once, request made exactly twice (original + 1 retry)
    mock_refresh.assert_awaited_once()


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
async def test_get_conversation_401_with_invalid_token_text_triggers_refresh(
    httpx_mock, mocker
):
    """
    get_conversation only retries when status is 401/403 AND 'Invalid access token'
    is in the response text.  This is different from send_message, which retries on
    status code alone.
    """
    url = GET_CONV_URL.format(conv_id="conv_123")
    route = httpx_mock.get(url)
    route.side_effect = [
        httpx.Response(401, text="Invalid access token"),
        httpx.Response(200, json={"id": "conv_123"}),
    ]
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock, return_value="new_token"
    )

    result = await divar.get_conversation("conv_123")

    assert result == {"id": "conv_123"}
    mock_refresh.assert_awaited_once()
    assert settings.DIVAR_ACCESS_TOKEN == "new_token"


@pytest.mark.asyncio
async def test_get_conversation_403_with_invalid_token_text_triggers_refresh(
    httpx_mock, mocker
):
    url = GET_CONV_URL.format(conv_id="conv_123")
    route = httpx_mock.get(url)
    route.side_effect = [
        httpx.Response(403, text="Invalid access token"),
        httpx.Response(200, json={"id": "conv_123"}),
    ]
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock, return_value="new_token"
    )

    result = await divar.get_conversation("conv_123")

    assert result == {"id": "conv_123"}
    mock_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_conversation_401_without_matching_text_no_refresh(httpx_mock, mocker):
    """401 without 'Invalid access token' in body → no refresh, error propagates."""
    url = GET_CONV_URL.format(conv_id="conv_123")
    httpx_mock.get(url).respond(401, text="Some other error")
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar.get_conversation("conv_123")

    mock_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_conversation_403_without_matching_text_no_refresh(httpx_mock, mocker):
    url = GET_CONV_URL.format(conv_id="conv_123")
    httpx_mock.get(url).respond(403, text="Forbidden")
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar.get_conversation("conv_123")

    mock_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_conversation_retry_exactly_once(httpx_mock, mocker):
    url = GET_CONV_URL.format(conv_id="conv_123")
    route = httpx_mock.get(url)
    route.side_effect = [
        httpx.Response(401, text="Invalid access token"),
        httpx.Response(401, text="Invalid access token"),
    ]
    mock_refresh = mocker.patch.object(
        divar, "refresh_access_token", new_callable=AsyncMock, return_value="new_token"
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar.get_conversation("conv_123")

    mock_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# refresh_access_token — bug 1.B1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_access_token_currently_broken_missing_code_and_redirect_uri(
    httpx_mock,
):
    """
    PLAN.md bug 1.B1: refresh_access_token() is missing the `code` and `redirect_uri`
    fields in the refresh request body.  Per docs/oauth/ReadMe.md step 5, the request
    must include `code` (set to the *current* access token) and `redirect_uri`.

    The attribute-name portion of 1.B1 (DIVAR_CLIENT_ID → DIVAR_APP_SLUG) has already
    been fixed in the current source, so this function no longer raises AttributeError.
    But the request body is still incomplete.  When 1.B1 is fully fixed (adding `code`
    and `redirect_uri`), the assertions below about their absence will FAIL — that is the
    signal to delete this test and activate the xfail test at the bottom of this file.
    """
    route = httpx_mock.post(TOKEN_URL).respond(200, json={"access_token": "new_token"})

    result = await divar.refresh_access_token()

    assert result == "new_token"
    assert route.called

    request = route.calls[0].request
    body = parse_qs(request.content.decode())

    assert body["grant_type"] == ["refresh_token"]
    assert body["client_id"] == ["test_app_slug"]
    assert body["client_secret"] == ["test_client_secret"]
    assert body["refresh_token"] == ["test_refresh_token"]

    # BUG (1.B1): these fields are MISSING from the current request body.
    # When the fix lands, these assertions will fail — replace this test.
    assert "code" not in body, "code field should be absent (bug 1.B1 not yet fixed)"
    assert "redirect_uri" not in body, (
        "redirect_uri field should be absent (bug 1.B1 not yet fixed)"
    )


@pytest.mark.asyncio
async def test_refresh_access_token_returns_only_access_token(httpx_mock):
    """
    PLAN.md 1.B1: a successful refresh returns BOTH a new access_token and a new
    refresh_token (the old refresh_token becomes invalid).  The current implementation
    only returns access_token — the caller never sees the new refresh_token and cannot
    persist it.  When 1.B1 is fixed, update this test to verify both are returned.
    """
    httpx_mock.post(TOKEN_URL).respond(
        200,
        json={
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "token_type": "bearer",
        },
    )

    result = await divar.refresh_access_token()

    # Current behavior: only returns the access_token string
    assert result == "new_access_token"


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="PLAN.md 1.B1 not yet fully fixed — missing `code` and `redirect_uri` in request body",
    strict=True,
)
async def test_refresh_access_token_correct_post_fix_behavior(httpx_mock):
    """
    Post-fix behavior per PLAN.md 1.B1 and docs/oauth/ReadMe.md step 5:
    - Request body includes `code` (current access token), `redirect_uri`,
      `client_id` (=DIVAR_APP_SLUG), `client_secret`, `grant_type=refresh_token`,
      `refresh_token`
    """
    route = httpx_mock.post(TOKEN_URL).respond(
        200,
        json={
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
        },
    )

    await divar.refresh_access_token()

    assert route.called
    request = route.calls[0].request
    body = parse_qs(request.content.decode())

    assert body["code"] == ["test_access_token"]
    assert body["redirect_uri"] == ["https://example.com/callback"]
