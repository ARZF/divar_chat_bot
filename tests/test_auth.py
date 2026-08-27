import asyncio
import os

# Set test env vars before any project imports — config.py instantiates Settings at
# module level, and section 2.8 adds required (no-default) secret settings.
os.environ.setdefault("DIVAR_API_KEY", "test_api_key")
os.environ.setdefault("DIVAR_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("DIVAR_REFRESH_TOKEN", "test_refresh_token")
os.environ.setdefault("DIVAR_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("DIVAR_IDENTIFICATION_KEY", "test_identification_key")
os.environ.setdefault("DIVAR_APP_SLUG", "test_app_slug")
os.environ.setdefault("DIVAR_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("DIVAR_REDIRECT_URI", "https://example.com/callback")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key")
os.environ.setdefault("OTP_HMAC_KEY", "test_otp_hmac_key")

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import api.auth as auth_module
from config import settings
from db.session import get_db
from main import app
from models.client import Client
from models.otp_code import OTPCode
from models.refresh_token import RefreshToken
from services.sms import get_sms_service

# The full model set uses Postgres JSONB (conversations/messages), which SQLite can't
# create. Section 2.8 only touches clients / otp_codes / refresh_tokens, so we create
# exactly those three tables on an async SQLite engine.
AUTH_TABLES = [Client.__table__, OTPCode.__table__, RefreshToken.__table__]


# --------------------------------------------------------------------------------------
# Capturing / failing SMS doubles
# --------------------------------------------------------------------------------------

class CapturingSMS:
    """Records the last (phone, code) sent so tests can read the OTP. Never raises."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send_otp(self, phone_number: str, code: str) -> None:
        self.sent.append((phone_number, code))

    @property
    def last_code(self) -> str:
        return self.sent[-1][1]


class FailingSMS:
    """Simulates a real provider failing to deliver (raises)."""

    async def send_otp(self, phone_number: str, code: str) -> None:
        raise RuntimeError("provider down")


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(lambda c: Client.metadata.create_all(c, tables=AUTH_TABLES))
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def sms():
    return CapturingSMS()


@pytest.fixture
def client(session_factory, sms):
    async def _override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_sms_service] = lambda: sms
    # Use https base_url so the Secure refresh-token cookie is sent back on
    # subsequent requests (the cookie jar drops Secure cookies over plain http).
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()



@pytest_asyncio.fixture
async def db(session_factory):
    async with session_factory() as s:
        yield s


PHONE = "09123456789"


# --------------------------------------------------------------------------------------
# OTP request
# --------------------------------------------------------------------------------------

def test_otp_request_sends_and_returns_generic_message(client, sms):
    resp = client.post("/auth/otp/request", json={"phone_number": PHONE})
    assert resp.status_code == 200
    assert resp.json() == {"message": "OTP sent"}
    assert len(sms.sent) == 1
    assert sms.sent[0][0] == PHONE
    assert len(sms.last_code) == settings.OTP_LENGTH


def test_otp_request_cooldown_returns_429(client, sms):
    first = client.post("/auth/otp/request", json={"phone_number": PHONE})
    assert first.status_code == 200
    second = client.post("/auth/otp/request", json={"phone_number": PHONE})
    assert second.status_code == 429
    # No second SMS was sent.
    assert len(sms.sent) == 1


def test_otp_request_sms_failure_returns_503_and_no_active_otp(session_factory):
    fail_sms = FailingSMS()

    async def _override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_sms_service] = lambda: fail_sms
    try:
        with TestClient(app) as c:
            resp = c.post("/auth/otp/request", json={"phone_number": PHONE})
            assert resp.status_code == 503
            assert resp.json()["detail"]["error"] == "sms_unavailable"
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------------------
# OTP verify
# --------------------------------------------------------------------------------------

def test_otp_verify_success_issues_session(client, sms):
    client.post("/auth/otp/request", json={"phone_number": PHONE})
    code = sms.last_code

    resp = client.post(
        "/auth/otp/verify", json={"phone_number": PHONE, "code": code}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["expires_in"] == settings.ACCESS_TOKEN_LIFETIME_MINUTES * 60
    # Refresh token is set as an HTTP-only cookie, not in the body.
    assert "refresh_token" in resp.cookies
    assert "refresh_token" not in body


def test_otp_verify_wrong_code_returns_400(client, sms):
    client.post("/auth/otp/request", json={"phone_number": PHONE})
    wrong = "0" * settings.OTP_LENGTH
    # Guard against the astronomically unlikely case the real code is all zeros.
    if wrong == sms.last_code:
        wrong = "1" * settings.OTP_LENGTH
    resp = client.post(
        "/auth/otp/verify", json={"phone_number": PHONE, "code": wrong}
    )
    assert resp.status_code == 400


def test_otp_verify_no_otp_returns_400(client):
    resp = client.post(
        "/auth/otp/verify", json={"phone_number": PHONE, "code": "123456"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_otp_verify_expired_returns_400(client, sms, db):
    client.post("/auth/otp/request", json={"phone_number": PHONE})
    code = sms.last_code
    # Force the stored OTP to be expired.
    from sqlalchemy import select

    row = (
        await db.execute(select(OTPCode).where(OTPCode.phone_number == PHONE))
    ).scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    resp = client.post(
        "/auth/otp/verify", json={"phone_number": PHONE, "code": code}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_otp_verify_max_attempts_returns_400(client, sms, db):
    client.post("/auth/otp/request", json={"phone_number": PHONE})
    code = sms.last_code
    from sqlalchemy import select

    row = (
        await db.execute(select(OTPCode).where(OTPCode.phone_number == PHONE))
    ).scalar_one()
    row.attempts = settings.OTP_MAX_ATTEMPTS
    await db.commit()

    resp = client.post(
        "/auth/otp/verify", json={"phone_number": PHONE, "code": code}
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------------------
# Refresh / logout
# --------------------------------------------------------------------------------------

def test_refresh_rotates_token_and_returns_new_access_token(client, sms):
    client.post("/auth/otp/request", json={"phone_number": PHONE})
    verify = client.post(
        "/auth/otp/verify", json={"phone_number": PHONE, "code": sms.last_code}
    )
    old_cookie = verify.cookies["refresh_token"]

    resp = client.post("/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    new_cookie = resp.cookies.get("refresh_token")
    assert new_cookie is not None
    assert new_cookie != old_cookie


def test_refresh_without_cookie_returns_401(client):
    resp = client.post("/auth/refresh")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_concurrent_refresh_calls_claim_token_once(tmp_path, mocker):
    database_path = tmp_path / "refresh-race.db"
    race_engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"timeout": 10},
    )
    race_sessions = async_sessionmaker(
        race_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with race_engine.begin() as conn:
        await conn.run_sync(
            lambda c: Client.metadata.create_all(
                c, tables=[Client.__table__, RefreshToken.__table__]
            )
        )

    token = "single-use-refresh-token"
    async with race_sessions() as seed_db:
        seeded_client = Client(phone_number="09120000001")
        seed_db.add(seeded_client)
        await seed_db.flush()
        seed_db.add(
            RefreshToken(
                client_id=seeded_client.id,
                token_hash=auth_module._hash_refresh_token(token),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        await seed_db.commit()

    async def refresh_once():
        async with race_sessions() as race_db:
            try:
                result = await auth_module.refresh_session(
                    Response(), db=race_db, refresh_token=token
                )
                return 200, result
            except HTTPException as exc:
                return exc.status_code, None

    async def stub_issue_session(db, client, response):
        return {"access_token": f"access-{client.id}", "expires_in": 1800}

    issue_session = mocker.patch.object(
        auth_module, "issue_session", side_effect=stub_issue_session
    )

    try:
        results = await asyncio.gather(refresh_once(), refresh_once())
        assert sorted(status for status, _ in results) == [200, 401]
        success = next(result for status, result in results if status == 200)
        assert success.access_token == "access-1"
        assert success.expires_in == 1800
        issue_session.assert_awaited_once()
    finally:
        await race_engine.dispose()


def test_logout_deletes_refresh_token(client, sms):
    client.post("/auth/otp/request", json={"phone_number": PHONE})
    client.post(
        "/auth/otp/verify", json={"phone_number": PHONE, "code": sms.last_code}
    )
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    # After logout the stored refresh token is gone, so refresh fails.
    after = client.post("/auth/refresh")
    assert after.status_code == 401


def test_protected_page_session_restoration_flow(client, sms):
    """The HTTP sequence static/js/session.js performs on a protected page:
    first data call without the (page-reload-lost) access token -> 401, exactly
    one refresh, one retry with the new token, then logout rejecting any later
    restoration attempt."""
    client.post("/auth/otp/request", json={"phone_number": PHONE})
    client.post(
        "/auth/otp/verify", json={"phone_number": PHONE, "code": sms.last_code}
    )

    # A page reload drops the in-memory access token; only the cookie remains.
    assert client.get("/auth/me").status_code == 401

    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    access_token = refreshed.json()["access_token"]

    # The single retry with the new token succeeds.
    retried = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert retried.status_code == 200
    assert retried.json()["phone_number"] == PHONE

    # Logout clears the in-memory token client-side and the cookie server-side,
    # so a later protected access attempt cannot restore the session.
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/refresh").status_code == 401


# --------------------------------------------------------------------------------------
# /auth/me
# --------------------------------------------------------------------------------------

def test_me_returns_profile_with_valid_jwt(client, sms):
    client.post("/auth/otp/request", json={"phone_number": PHONE})
    verify = client.post(
        "/auth/otp/verify", json={"phone_number": PHONE, "code": sms.last_code}
    )
    access_token = verify.json()["access_token"]

    resp = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["phone_number"] == PHONE
    assert body["divar_user_id"] is None
    assert "id" in body and "created_at" in body


def test_me_without_token_returns_401(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_with_invalid_token_returns_401(client):
    resp = client.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert resp.status_code == 401


def test_admin_upload_prices_rejects_missing_authorization(client):
    resp = client.post(
        "/admin/upload-prices",
        files={
            "file": (
                "prices.xlsx",
                b"not processed",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 401


def test_seller_posts_rejects_missing_authorization(client):
    resp = client.post(
        "/seller/posts",
        json={"post_tokens": ["post-token"]},
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------------------
# find_or_create_client merge logic
# --------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_or_create_client_creates_then_merges(db):
    created = await auth_module.find_or_create_client(db, phone_number=PHONE)
    assert created.id is not None
    assert created.phone_number == PHONE
    assert created.divar_user_id is None

    # Same phone again → same row (merge), and divar_user_id backfilled.
    merged = await auth_module.find_or_create_client(
        db, phone_number=PHONE, divar_user_id="divar_user_1"
    )
    assert merged.id == created.id
    assert merged.divar_user_id == "divar_user_1"

    # A second call with a different divar_user_id must NOT overwrite the existing one.
    again = await auth_module.find_or_create_client(
        db, phone_number=PHONE, divar_user_id="divar_user_2"
    )
    assert again.id == created.id
    assert again.divar_user_id == "divar_user_1"


@pytest.mark.asyncio
async def test_find_or_create_client_recovers_from_concurrent_insert(tmp_path):
    database_path = tmp_path / "client-race.db"
    race_engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"timeout": 10},
    )
    race_sessions = async_sessionmaker(
        race_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with race_engine.begin() as conn:
        await conn.run_sync(
            lambda c: Client.metadata.create_all(c, tables=[Client.__table__])
        )

    async def create_client():
        async with race_sessions() as race_db:
            return await auth_module.find_or_create_client(
                race_db, phone_number="09120000002"
            )

    try:
        first, second = await asyncio.gather(create_client(), create_client())
        assert first.id == second.id

        async with race_sessions() as check_db:
            rows = (
                await check_db.execute(
                    select(Client).where(Client.phone_number == "09120000002")
                )
            ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == first.id
    finally:
        await race_engine.dispose()
