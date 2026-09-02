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
USER_URL = "https://open-api.divar.ir/v1/open-platform/users"


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


SUBSCRIPTION_URL = f"{divar.BASE_URL}/v1/open-platform/events/subscriptions"


@pytest.mark.asyncio
async def test_register_event_subscription_success(httpx_mock):
    route = httpx_mock.post(SUBSCRIPTION_URL).respond(201, json={"status": "ok"})

    assert await divar.register_event_subscription("seller_access_token") is True

    request = route.calls[0].request
    assert request.headers["x-api-key"] == "test_api_key"
    assert request.headers["authorization"] == "Bearer seller_access_token"
    assert json.loads(request.content) == {"event_type": "NEW_MESSAGE_ON_POST"}


@pytest.mark.asyncio
async def test_register_event_subscription_failure_logs_and_reraises(
    httpx_mock, caplog
):
    httpx_mock.post(SUBSCRIPTION_URL).respond(
        403,
        text="subscription denied",
        headers={"Content-Type": "text/plain"},
    )

    with pytest.raises(httpx.HTTPStatusError):
        await divar.register_event_subscription("seller_access_token")

    record = next(
        record
        for record in caplog.records
        if record.message.startswith("register_event_subscription failed")
    )
    assert "status=403" in record.message
    assert "content_type=text/plain" in record.message
    assert "event_type=NEW_MESSAGE_ON_POST" in record.message
    assert f"url={SUBSCRIPTION_URL}" in record.message
    assert "body='subscription denied'" in record.message
    assert "seller_access_token" not in record.message


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


# ---------------------------------------------------------------------------
# send_supplier_message — logging and retry on transient failures
# ---------------------------------------------------------------------------

SUPPLIER_MSG_URL = (
    f"{divar.BASE_URL}/v2/open-platform/conversations/conv_123/messages"
)


@pytest.fixture
def no_sleep(mocker):
    """Retry backoff must never actually sleep in tests."""
    return mocker.patch("asyncio.sleep", new_callable=AsyncMock)


# NOTE: `record.conversation_id` is not asserted below — logging_config.ContextFilter
# overwrites it from the request contextvar, which these service-level tests do not set.


@pytest.mark.asyncio
async def test_send_supplier_message_success_logs_debug(httpx_mock, caplog, no_sleep):
    route = httpx_mock.post(SUPPLIER_MSG_URL).respond(200, json={"status": "ok"})

    with caplog.at_level("DEBUG", logger="divar"):
        assert await divar.send_supplier_message(
            "conv_123", "Hello", "seller_access_token"
        ) is True

    assert route.call_count == 1
    no_sleep.assert_not_awaited()
    record = next(
        record
        for record in caplog.records
        if record.message == "send_supplier_message succeeded"
    )
    assert record.status_code == 200


@pytest.mark.asyncio
async def test_send_supplier_message_retries_502_then_succeeds(
    httpx_mock, caplog, no_sleep
):
    route = httpx_mock.post(SUPPLIER_MSG_URL).mock(
        side_effect=[
            httpx.Response(502, text="Bad Gateway"),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )

    with caplog.at_level("WARNING", logger="divar"):
        assert await divar.send_supplier_message(
            "conv_123", "Hello", "seller_access_token"
        ) is True

    assert route.call_count == 2
    assert no_sleep.await_count == 1
    record = next(
        record
        for record in caplog.records
        if record.message == "supplier message attempt failed; retrying"
    )
    assert record.status_code == 502
    assert record.response_body == "Bad Gateway"
    assert record.attempt == 1
    assert record.max_attempts == 4
    assert 1.0 <= record.delay_seconds <= 1.25


@pytest.mark.asyncio
async def test_send_supplier_message_retries_502_three_times_then_succeeds(
    httpx_mock, no_sleep
):
    route = httpx_mock.post(SUPPLIER_MSG_URL).mock(
        side_effect=[
            httpx.Response(502, text="Bad Gateway"),
            httpx.Response(502, text="Bad Gateway"),
            httpx.Response(502, text="Bad Gateway"),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )

    assert await divar.send_supplier_message(
        "conv_123", "Hello", "seller_access_token"
    ) is True

    assert route.call_count == 4
    assert no_sleep.await_count == 3
    delays = [call.args[0] for call in no_sleep.await_args_list]
    assert 1.0 <= delays[0] <= 1.25
    assert 2.0 <= delays[1] <= 2.25
    assert 4.0 <= delays[2] <= 4.25


@pytest.mark.asyncio
async def test_send_supplier_message_exhausts_retries_and_reraises(
    httpx_mock, caplog, no_sleep
):
    route = httpx_mock.post(SUPPLIER_MSG_URL).respond(502, text="Bad Gateway")

    with caplog.at_level("ERROR", logger="divar"):
        with pytest.raises(httpx.HTTPStatusError):
            await divar.send_supplier_message(
                "conv_123", "Hello", "seller_access_token"
            )

    assert route.call_count == 4
    assert no_sleep.await_count == 3
    record = next(
        record
        for record in caplog.records
        if record.message == "supplier message send exhausted retries"
    )
    assert record.status_code == 502
    assert record.response_body == "Bad Gateway"
    assert record.attempts == 4


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422, 500])
@pytest.mark.asyncio
async def test_send_supplier_message_does_not_retry_non_transient_status(
    httpx_mock, caplog, no_sleep, status_code
):
    route = httpx_mock.post(SUPPLIER_MSG_URL).respond(status_code, text="nope")

    with caplog.at_level("ERROR", logger="divar"):
        with pytest.raises(httpx.HTTPStatusError):
            await divar.send_supplier_message(
                "conv_123", "Hello", "seller_access_token"
            )

    assert route.call_count == 1
    no_sleep.assert_not_awaited()
    record = next(
        record
        for record in caplog.records
        if record.message == "send_supplier_message failed"
    )
    assert record.status_code == status_code
    assert record.response_body == "nope"


@pytest.mark.asyncio
async def test_send_supplier_message_retries_503(httpx_mock, no_sleep):
    route = httpx_mock.post(SUPPLIER_MSG_URL).mock(
        side_effect=[
            httpx.Response(503, text="Service Unavailable"),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )

    assert await divar.send_supplier_message(
        "conv_123", "Hello", "seller_access_token"
    ) is True

    assert route.call_count == 2
    assert no_sleep.await_count == 1


@pytest.mark.asyncio
async def test_send_supplier_message_retries_504_with_duplicate_risk_warning(
    httpx_mock, caplog, no_sleep
):
    route = httpx_mock.post(SUPPLIER_MSG_URL).mock(
        side_effect=[
            httpx.Response(504, text="Gateway Timeout"),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )

    with caplog.at_level("WARNING", logger="divar"):
        assert await divar.send_supplier_message(
            "conv_123", "Hello", "seller_access_token"
        ) is True

    assert route.call_count == 2
    assert no_sleep.await_count == 1
    record = next(
        record
        for record in caplog.records
        if "possible duplicate delivery risk" in record.message
    )
    assert "504" in record.message
    assert record.status_code == 504
    assert record.attempt == 1


@pytest.mark.asyncio
async def test_send_supplier_message_retries_transient_network_error(
    httpx_mock, caplog, no_sleep
):
    route = httpx_mock.post(SUPPLIER_MSG_URL).mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )

    with caplog.at_level("WARNING", logger="divar"):
        assert await divar.send_supplier_message(
            "conv_123", "Hello", "seller_access_token"
        ) is True

    assert route.call_count == 2
    assert no_sleep.await_count == 1
    record = next(
        record
        for record in caplog.records
        if record.message == "supplier message network error; retrying"
    )
    assert record.attempt == 1
    assert record.max_attempts == 4
    assert "connection refused" in record.error


@pytest.mark.asyncio
async def test_send_supplier_message_exhausts_retries_on_network_error(
    httpx_mock, caplog, no_sleep
):
    route = httpx_mock.post(SUPPLIER_MSG_URL).mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with caplog.at_level("ERROR", logger="divar"):
        with pytest.raises(httpx.ConnectError):
            await divar.send_supplier_message(
                "conv_123", "Hello", "seller_access_token"
            )

    assert route.call_count == 4
    assert no_sleep.await_count == 3
    record = next(
        record
        for record in caplog.records
        if record.message == "supplier message send exhausted retries"
    )
    assert record.attempts == 4


# ---------------------------------------------------------------------------
# get_user / get_user_phone_number — section 2.3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_returns_phone_and_user_id_from_live_shape(httpx_mock):
    route = httpx_mock.get(USER_URL).respond(
        200,
        json={
            "phone_numbers": ["09123456789"],
            "phone_number": "09123456789",
            "user_id": "divar-user-1",
        },
    )

    result = await divar.get_user("seller_access_token")

    assert result == {
        "phone_number": "09123456789",
        "user_id": "divar-user-1",
    }
    request = route.calls[0].request
    assert request.method == "GET"
    assert request.headers["x-api-key"] == "test_api_key"
    assert request.headers["authorization"] == "Bearer seller_access_token"


@pytest.mark.asyncio
async def test_get_user_falls_back_to_first_non_empty_phone_number(httpx_mock):
    httpx_mock.get(USER_URL).respond(
        200,
        json={"phone_number": "", "phone_numbers": ["", " 09120000000 "]},
    )

    result = await divar.get_user("seller_access_token")

    assert result == {"phone_number": "09120000000", "user_id": None}


@pytest.mark.asyncio
async def test_get_user_phone_number_wrapper_returns_only_phone(httpx_mock):
    httpx_mock.get(USER_URL).respond(
        200,
        json={"phone_number": "09121111111", "user_id": "divar-user-2"},
    )

    result = await divar.get_user_phone_number("seller_access_token")

    assert result == "09121111111"


@pytest.mark.asyncio
async def test_get_user_returns_none_on_api_failure(httpx_mock):
    route = httpx_mock.get(USER_URL).respond(
        401, json={"message": "Invalid access token"}
    )

    assert await divar.get_user("bad_token") is None
    assert route.call_count == 1


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
    - Returns a tuple of (new_access_token, new_refresh_token, expires_in)
    """
    route = httpx_mock.post(TOKEN_URL).respond(
        200,
        json={
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": "1234",
        },
    )

    result = await divar.refresh_access_token(
        "caller_access_token", "caller_refresh_token"
    )

    assert result == ("new_access_token", "new_refresh_token", 1234)
    assert route.called
    request = route.calls[0].request
    body = parse_qs(request.content.decode())

    assert body["code"] == ["caller_access_token"]
    assert body["redirect_uri"] == ["https://example.com/callback"]
    assert body["client_id"] == ["test_app_slug"]
    assert body["client_secret"] == ["test_client_secret"]
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["caller_refresh_token"]


@pytest.mark.asyncio
async def test_refresh_access_token_uses_callers_refresh_token_not_global_setting(
    httpx_mock,
):
    """Regression: the refresh token must come from the caller, never from `.env`.

    Tokens are per-seller (§2.9). Reading `settings.DIVAR_REFRESH_TOKEN` here meant any
    seller's refresh was attempted with the global bootstrap credential, and the result
    was then persisted onto that seller's row.
    """
    route = httpx_mock.post(TOKEN_URL).respond(
        200,
        json={
            "access_token": "seller_new_access",
            "refresh_token": "seller_new_refresh",
            "expires_in": 3600,
        },
    )

    await divar.refresh_access_token("seller_access", "seller_refresh")

    body = parse_qs(route.calls[0].request.content.decode())
    assert body["refresh_token"] == ["seller_refresh"]
    assert body["refresh_token"] != [settings.DIVAR_REFRESH_TOKEN]


# ---------------------------------------------------------------------------
# Shared client timeout — main.py's lifespan (2026-08-19 incident)
# ---------------------------------------------------------------------------


@pytest.fixture
def lifespan_isolation(mocker):
    """Run main.lifespan without its unrelated global side effects.

    ``_warm_price_caches`` would hit the real DB, and ``setup_logging`` replaces the root
    handlers (evicting pytest's caplog handler) and pins the root level. Neither is under
    test here. The lifespan also ``aclose()``s ``divar.client`` on exit, so the original
    module-level client is restored afterwards for the tests that follow.
    """
    mocker.patch("main._warm_price_caches", new_callable=AsyncMock)
    mocker.patch("main.setup_logging")
    original_client = divar.client
    yield
    divar.client = original_client


@pytest.mark.asyncio
async def test_lifespan_client_timeout_comes_from_settings(mocker, lifespan_isolation):
    """The shared client must not carry the old hardcoded `timeout=60`.

    Patching the settings to values no literal in the codebase uses means this can only
    pass if the values are genuinely read from `settings` at lifespan time.
    """
    import main

    mocker.patch.object(settings, "DIVAR_CLIENT_CONNECT_TIMEOUT_SECONDS", 3.5)
    mocker.patch.object(settings, "DIVAR_CLIENT_TOTAL_TIMEOUT_SECONDS", 11.25)

    async with main.lifespan(main.app):
        timeout = divar.client.timeout

    assert timeout.connect == 3.5
    # httpx.Timeout(total, connect=...) applies `total` to the other three phases.
    assert (timeout.read, timeout.write, timeout.pool) == (11.25, 11.25, 11.25)


@pytest.mark.asyncio
async def test_lifespan_client_timeout_reaches_outgoing_requests(
    mocker, lifespan_isolation
):
    """End-to-end: a settings override must change the timeout httpx actually applies.

    Asserting on the constructed client alone would not prove the per-request transport
    sees it — no call site in divar.py overrides the timeout, so every Divar call inherits
    this. `send_message` stands in for the whole module (it shares the same client).
    """
    mocker.patch.object(settings, "DIVAR_CLIENT_CONNECT_TIMEOUT_SECONDS", 1.5)
    mocker.patch.object(settings, "DIVAR_CLIENT_TOTAL_TIMEOUT_SECONDS", 2.5)
    import main

    with respx.mock(assert_all_called=False) as router:
        route = router.post(SEND_MSG_URL.format(conv_id="conv_123")).respond(
            200, json={"status": "ok"}
        )
        async with main.lifespan(main.app):
            await divar.send_message("conv_123", "Hello")

    assert route.calls[0].request.extensions["timeout"] == {
        "connect": 1.5,
        "read": 2.5,
        "write": 2.5,
        "pool": 2.5,
    }

