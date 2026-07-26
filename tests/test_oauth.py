import os
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("CORS_ALLOWED_ORIGINS", '["http://localhost"]')
os.environ.setdefault("DIVAR_API_KEY", "test_api_key")
os.environ.setdefault("DIVAR_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("DIVAR_REFRESH_TOKEN", "test_refresh_token")
os.environ.setdefault("DIVAR_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("DIVAR_IDENTIFICATION_KEY", "test_identification_key")
os.environ.setdefault("DIVAR_APP_SLUG", "test_app_slug")
os.environ.setdefault("DIVAR_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("DIVAR_REDIRECT_URI", "https://example.com/oauth/callback")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key")
os.environ.setdefault("OTP_HMAC_KEY", "test_otp_hmac_key")

import pytest
from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import api.oauth as oauth_module
from config import settings
from models.oauth_token import OAuthToken
from schemas.auth import TokenResponse
import services.divar as divar_service


def _request(query: str) -> Request:
    return Request({"type": "http", "query_string": query.encode("utf-8")})


@pytest.fixture(autouse=True)
def clear_login_states():
    oauth_module._login_states.clear()
    yield
    oauth_module._login_states.clear()


@pytest.mark.asyncio
async def test_oauth_start_redirects_and_stores_state_for_ten_minutes(mocker):
    mocker.patch.object(oauth_module.time, "time", return_value=1_000.0)
    mocker.patch.object(oauth_module.secrets, "token_urlsafe", return_value="state-1")

    response = await oauth_module.oauth_start()

    assert isinstance(response, RedirectResponse)
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query == {
        "response_type": ["code"],
        "client_id": [settings.DIVAR_APP_SLUG],
        "redirect_uri": [settings.DIVAR_REDIRECT_URI],
        "scope": ["USER_PHONE USER_ID offline_access"],
        "state": ["state-1"],
    }
    assert oauth_module._login_states == {"state-1": 1_600.0}


@pytest.mark.asyncio
async def test_oauth_callback_persists_tokens_and_issues_session(mocker):
    oauth_module._login_states["state-1"] = oauth_module.time.time() + 600
    token_response = mocker.Mock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {
        "access_token": "divar-access",
        "refresh_token": "divar-refresh",
        "expires_in": 604800,
    }
    post = mocker.AsyncMock(return_value=token_response)
    mocker.patch.object(
        divar_service,
        "client",
        new=SimpleNamespace(post=post),
    )
    mocker.patch.object(
        divar_service,
        "get_user",
        new=mocker.AsyncMock(
            return_value={
                "phone_number": "09123456789",
                "user_id": "divar-user-1",
            }
        ),
    )
    client = SimpleNamespace(id=7)
    find_client = mocker.patch.object(
        oauth_module,
        "find_or_create_client",
        new=mocker.AsyncMock(return_value=client),
    )
    issue_session = mocker.patch.object(
        oauth_module,
        "issue_session",
        new=mocker.AsyncMock(
            return_value={"access_token": "app-access", "expires_in": 1800}
        ),
    )
    result_proxy = mocker.Mock()
    result_proxy.scalar_one_or_none.return_value = None
    db = mocker.MagicMock(spec=AsyncSession)
    db.execute = mocker.AsyncMock(return_value=result_proxy)
    db.commit = mocker.AsyncMock()
    before = datetime.now(timezone.utc)

    result = await oauth_module.oauth_callback(
        _request("state=state-1&code=authorization-code"), Response(), db
    )

    assert result == TokenResponse(access_token="app-access", expires_in=1800)
    assert "state-1" not in oauth_module._login_states
    find_client.assert_awaited_once_with(
        db,
        phone_number="09123456789",
        divar_user_id="divar-user-1",
    )
    issue_session.assert_awaited_once()
    stored = db.add.call_args.args[0]
    assert isinstance(stored, OAuthToken)
    assert stored.client_id == 7
    assert stored.divar_access_token == "divar-access"
    assert stored.divar_refresh_token == "divar-refresh"
    assert 604790 <= (stored.token_expires_at - before).total_seconds() <= 604810


@pytest.mark.asyncio
async def test_oauth_callback_without_phone_returns_403_and_writes_nothing(mocker):
    oauth_module._login_states["state-1"] = oauth_module.time.time() + 600
    token_response = mocker.Mock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {
        "access_token": "divar-access",
        "refresh_token": "divar-refresh",
        "expires_in": 604800,
    }
    post = mocker.AsyncMock(return_value=token_response)
    mocker.patch.object(
        divar_service,
        "client",
        new=SimpleNamespace(post=post),
    )
    mocker.patch.object(
        divar_service,
        "get_user",
        new=mocker.AsyncMock(
            return_value={"phone_number": None, "user_id": "divar-user-1"}
        ),
    )
    find_client = mocker.patch.object(
        oauth_module, "find_or_create_client", new=mocker.AsyncMock()
    )
    issue_session = mocker.patch.object(
        oauth_module, "issue_session", new=mocker.AsyncMock()
    )
    db = mocker.MagicMock(spec=AsyncSession)
    db.execute = mocker.AsyncMock()
    db.commit = mocker.AsyncMock()

    result = await oauth_module.oauth_callback(
        _request("state=state-1&code=authorization-code"), Response(), db
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 403
    assert "state-1" not in oauth_module._login_states
    find_client.assert_not_awaited()
    issue_session.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.add.assert_not_called()