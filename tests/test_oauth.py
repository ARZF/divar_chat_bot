import asyncio
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

import httpx
import pytest
from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
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
        "scope": [
            "USER_PHONE USER_ID offline_access "
            "CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND "
            "CHAT_SUPPLIER_ALL_CONVERSATIONS_READ USER_POSTS_GET"
        ],
        "state": ["state-1"],
    }
    assert oauth_module._login_states == {"state-1": 1_600.0}


@pytest.mark.asyncio
async def test_oauth_callback_issues_session_when_subscription_registration_fails(mocker):
    oauth_module._login_states["state-1"] = oauth_module.time.time() + 600
    token_response = mocker.Mock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {
        "access_token": "divar-access",
        "refresh_token": "divar-refresh",
        "expires_in": 604800,
    }
    mocker.patch.object(
        divar_service,
        "client",
        new=SimpleNamespace(post=mocker.AsyncMock(return_value=token_response)),
    )
    mocker.patch.object(
        divar_service,
        "get_user",
        new=mocker.AsyncMock(
            return_value={"phone_number": "09123456789", "user_id": "divar-user-1"}
        ),
    )
    mocker.patch.object(
        oauth_module,
        "find_or_create_client",
        new=mocker.AsyncMock(return_value=SimpleNamespace(id=7)),
    )
    issue_session = mocker.patch.object(
        oauth_module,
        "issue_session",
        new=mocker.AsyncMock(return_value={"access_token": "app-access", "expires_in": 1800}),
    )
    mocker.patch.object(
        divar_service,
        "register_event_subscription",
        new=mocker.AsyncMock(side_effect=httpx.HTTPError("registration failed")),
    )
    result_proxy = mocker.Mock()
    result_proxy.scalar_one_or_none.return_value = None
    db = mocker.MagicMock(spec=AsyncSession)
    db.execute = mocker.AsyncMock(return_value=result_proxy)
    db.commit = mocker.AsyncMock()

    result = await oauth_module.oauth_callback(_request("state=state-1&code=authorization-code"), db)

    assert isinstance(result, RedirectResponse)
    assert result.headers["location"] == "/dashboard"
    issue_session.assert_awaited_once()
    # The redirect carries no token material in its URL or body.
    assert "app-access" not in result.headers["location"]
    assert not result.body


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
        new=mocker.AsyncMock(return_value={"access_token": "app-access", "expires_in": 1800}),
    )
    result_proxy = mocker.Mock()
    result_proxy.scalar_one_or_none.return_value = None
    db = mocker.MagicMock(spec=AsyncSession)
    db.execute = mocker.AsyncMock(return_value=result_proxy)
    db.commit = mocker.AsyncMock()
    before = datetime.now(timezone.utc)

    result = await oauth_module.oauth_callback(
        _request("state=state-1&code=authorization-code"), db
    )

    assert isinstance(result, RedirectResponse)
    assert result.headers["location"] == "/dashboard"
    assert "state-1" not in oauth_module._login_states
    find_client.assert_awaited_once_with(
        db,
        phone_number="09123456789",
        divar_user_id="divar-user-1",
    )
    # The session is issued on the redirect response itself so the refresh cookie
    # actually reaches the browser (FastAPI drops injected-Response cookies when a
    # Response object is returned directly).
    issue_session.assert_awaited_once_with(db, client, result)
    stored = db.add.call_args.args[0]
    assert isinstance(stored, OAuthToken)
    assert stored.client_id == 7
    assert stored.divar_access_token == "divar-access"
    assert stored.divar_refresh_token == "divar-refresh"
    assert 604790 <= (stored.token_expires_at - before).total_seconds() <= 604810


@pytest.mark.asyncio
async def test_oauth_callback_recovers_from_concurrent_token_insert(mocker):
    barrier = asyncio.Barrier(2)
    state = {"commit_count": 0, "row": None}

    class RaceDB:
        def __init__(self):
            self.added = None
            self.commit_count = 0
            self.rollback = mocker.AsyncMock()

        async def execute(self, _statement):
            if self.added is None:
                result = mocker.Mock()
                result.scalar_one_or_none.return_value = None
                return result
            result = mocker.Mock()
            result.scalar_one.return_value = state["row"]
            return result

        def add(self, value):
            self.added = value

        async def commit(self):
            self.commit_count += 1
            if self.commit_count > 1:
                return
            await barrier.wait()
            state["commit_count"] += 1
            if state["commit_count"] == 1:
                state["row"] = self.added
                return
            raise IntegrityError("duplicate client_id", {}, Exception("duplicate"))

    token_response = mocker.Mock()
    token_response.raise_for_status.return_value = None
    token_response.json.side_effect = [
        {
            "access_token": "divar-access-1",
            "refresh_token": "divar-refresh-1",
            "expires_in": 604800,
        },
        {
            "access_token": "divar-access-2",
            "refresh_token": "divar-refresh-2",
            "expires_in": 604800,
        },
    ]
    mocker.patch.object(
        divar_service,
        "client",
        new=SimpleNamespace(
            post=mocker.AsyncMock(return_value=token_response)
        ),
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
    mocker.patch.object(
        oauth_module,
        "find_or_create_client",
        new=mocker.AsyncMock(return_value=SimpleNamespace(id=7)),
    )
    mocker.patch.object(
        oauth_module,
        "issue_session",
        new=mocker.AsyncMock(return_value={"access_token": "app-access", "expires_in": 1800}),
    )
    oauth_module._login_states.update(
        {
            "state-1": oauth_module.time.time() + 600,
            "state-2": oauth_module.time.time() + 600,
        }
    )
    dbs = [RaceDB(), RaceDB()]

    results = await asyncio.gather(
        oauth_module.oauth_callback(
            _request("state=state-1&code=authorization-code-1"), dbs[0]
        ),
        oauth_module.oauth_callback(
            _request("state=state-2&code=authorization-code-2"), dbs[1]
        ),
    )

    assert all(isinstance(r, RedirectResponse) for r in results)
    assert {r.headers["location"] for r in results} == {"/dashboard"}
    assert state["row"] is not None
    assert state["row"].client_id == 7
    assert state["row"].divar_access_token in {
        "divar-access-1",
        "divar-access-2",
    }
    assert state["row"].divar_refresh_token in {
        "divar-refresh-1",
        "divar-refresh-2",
    }
    assert state["row"].token_expires_at is not None
    assert dbs[0].rollback.await_count + dbs[1].rollback.await_count == 1


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
        _request("state=state-1&code=authorization-code"), db
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 403
    assert "state-1" not in oauth_module._login_states
    find_client.assert_not_awaited()
    issue_session.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.add.assert_not_called()


# --------------------------------------------------------------------------------------
# Step 11 — redirect handoff contract and state-validation security
# --------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,expected_detail",
    [
        ("code=authorization-code", "Missing state parameter"),
        ("state=never-issued&code=authorization-code", "Invalid state parameter"),
        ("state=state-1", "Authorization code not provided"),
    ],
)
async def test_oauth_callback_rejects_invalid_requests_without_session(query, expected_detail, mocker):
    oauth_module._login_states["state-1"] = oauth_module.time.time() + 600
    issue_session = mocker.patch.object(
        oauth_module, "issue_session", new=mocker.AsyncMock()
    )
    db = mocker.MagicMock(spec=AsyncSession)

    result = await oauth_module.oauth_callback(_request(query), db)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 400
    assert result.body.decode() == f'{{"detail":"{expected_detail}"}}'
    issue_session.assert_not_awaited()
    # A rejected callback never leaks a token in its body or URL.
    assert "access_token" not in result.body.decode().lower()


@pytest.mark.asyncio
async def test_oauth_callback_state_expires_after_ten_minutes(mocker):
    mocker.patch.object(oauth_module.time, "time", return_value=1_000.0)
    # State was issued at t=1 and expires at t=601; the callback arrives at t=1_000.
    oauth_module._login_states["stale-state"] = 601.0
    issue_session = mocker.patch.object(
        oauth_module, "issue_session", new=mocker.AsyncMock()
    )
    db = mocker.MagicMock(spec=AsyncSession)

    result = await oauth_module.oauth_callback(
        _request("state=stale-state&code=authorization-code"), db
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 400
    assert "stale-state" not in oauth_module._login_states
    issue_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_oauth_callback_replayed_state_is_rejected(mocker):
    """A state that already produced a redirect must not issue a second session."""
    oauth_module._login_states["state-1"] = oauth_module.time.time() + 600
    token_response = mocker.Mock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {
        "access_token": "divar-access",
        "refresh_token": "divar-refresh",
        "expires_in": 604800,
    }
    mocker.patch.object(
        divar_service,
        "client",
        new=SimpleNamespace(post=mocker.AsyncMock(return_value=token_response)),
    )
    mocker.patch.object(
        divar_service,
        "get_user",
        new=mocker.AsyncMock(
            return_value={"phone_number": "09123456789", "user_id": "divar-user-1"}
        ),
    )
    mocker.patch.object(
        oauth_module,
        "find_or_create_client",
        new=mocker.AsyncMock(return_value=SimpleNamespace(id=7)),
    )
    issue_session = mocker.patch.object(
        oauth_module,
        "issue_session",
        new=mocker.AsyncMock(return_value={"access_token": "app-access", "expires_in": 1800}),
    )
    result_proxy = mocker.Mock()
    result_proxy.scalar_one_or_none.return_value = None
    db = mocker.MagicMock(spec=AsyncSession)
    db.execute = mocker.AsyncMock(return_value=result_proxy)
    db.commit = mocker.AsyncMock()

    first = await oauth_module.oauth_callback(
        _request("state=state-1&code=authorization-code"), db
    )
    assert isinstance(first, RedirectResponse)
    assert first.headers["location"] == "/dashboard"
    issue_session.assert_awaited_once()

    replay = await oauth_module.oauth_callback(
        _request("state=state-1&code=authorization-code"), db
    )
    assert isinstance(replay, JSONResponse)
    assert replay.status_code == 400
    issue_session.assert_awaited_once()  # still exactly one session


@pytest.mark.asyncio
async def test_oauth_callback_redirect_sets_http_only_secure_refresh_cookie(mocker):
    """End-to-end through the REAL issue_session: the redirect must carry the
    existing refresh-cookie attributes (HttpOnly, Secure, SameSite=Lax, Path=/auth)
    and expose no access token anywhere in the response."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from models.client import Client
    from models.refresh_token import RefreshToken

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Client.metadata.create_all(
                c,
                tables=[Client.__table__, RefreshToken.__table__, OAuthToken.__table__],
            )
        )
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    oauth_module._login_states["state-1"] = oauth_module.time.time() + 600
    token_response = mocker.Mock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {
        "access_token": "divar-access",
        "refresh_token": "divar-refresh",
        "expires_in": 604800,
    }
    mocker.patch.object(
        divar_service,
        "client",
        new=SimpleNamespace(post=mocker.AsyncMock(return_value=token_response)),
    )
    mocker.patch.object(
        divar_service,
        "get_user",
        new=mocker.AsyncMock(
            return_value={"phone_number": "09123456789", "user_id": "divar-user-1"}
        ),
    )
    mocker.patch.object(
        divar_service,
        "register_event_subscription",
        new=mocker.AsyncMock(return_value=None),
    )

    try:
        async with sessions() as db:
            # The REAL issue_session runs — nothing about the session mechanism is mocked.
            response = await oauth_module.oauth_callback(
                _request("state=state-1&code=authorization-code"),
                db,
            )
    finally:
        await engine.dispose()

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard"
    assert "access_token" not in response.body.decode().lower()
    assert "divar-access" not in response.body.decode()
    assert "divar-refresh" not in response.body.decode()
    assert "?" not in response.headers["location"]
    assert "=" not in response.headers["location"]

    cookie = response.headers.get("set-cookie")
    assert cookie is not None, "redirect must carry the refresh cookie"
    assert "httponly" in cookie.lower()
    assert "secure" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    assert "path=/auth" in cookie.lower()
    assert cookie.split(";")[0].split("=", 1)[1]  # refresh token value present
    assert len(response.headers.getlist("set-cookie")) == 1