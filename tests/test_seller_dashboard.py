"""Dashboard summary endpoint tests (Phase 3 step 13).

Covers the JWT gate (401 paths) and two-tenant isolation: every count must
derive from the JWT's client_id, never from browser input.
"""

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from config import settings
from db.session import get_db
from main import app
from models.client import Client
from models.conversation import Conversation
from models.post import Post
from models.post_conversation import PostConversation
from models.post_message import PostMessage


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    """Allow the production PostgreSQL JSONB model to be tested on SQLite
    (same adapter as tests/test_chatbot.py)."""
    return "JSON"

# Same tables as the chatbot tests (minus OTP/refresh, which the summary
# endpoint never touches). PostMessage keeps FK targets resolvable.
DASHBOARD_TABLES = [
    Client.__table__,
    Post.__table__,
    Conversation.__table__,
    PostConversation.__table__,
    PostMessage.__table__,
]


def make_access_token(client_id: int) -> str:
    payload = {
        "client_id": client_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Client.metadata.create_all(c, tables=DASHBOARD_TABLES)
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def two_tenants(session_factory):
    """Seller A with 2 posts, 3 chatbot conversations, 1 post conversation;
    seller B with 1 post and nothing else. A's summary must ignore B's rows."""
    async with session_factory() as db:
        seller_a = Client(phone_number="09120000001")
        seller_b = Client(phone_number="09120000002")
        db.add_all([seller_a, seller_b])
        await db.flush()

        db.add_all([
            Post(post_token="A_TOKEN_1", client_id=seller_a.id),
            Post(post_token="A_TOKEN_2", client_id=seller_a.id),
            Post(post_token="B_TOKEN_1", client_id=seller_b.id),
        ])
        for i in range(3):
            db.add(
                Conversation(
                    client_id=seller_a.id,
                    divar_conversation_id=f"a-conv-{i}",
                )
            )
        db.add(
            PostConversation(
                client_id=seller_a.id,
                divar_conversation_id="a-post-conv-1",
                post_token="A_TOKEN_1",
            )
        )
        await db.commit()
        return seller_a.id, seller_b.id


@pytest.fixture
def client(session_factory):
    async def _override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_summary_requires_authorization_header(client):
    response = client.get("/api/v1/seller/dashboard/summary")
    assert response.status_code == 401


def test_summary_rejects_invalid_token(client):
    response = client.get(
        "/api/v1/seller/dashboard/summary",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


def test_summary_rejects_unknown_client(client):
    """A syntactically valid JWT for a deleted/unknown client gets 401, not
    zeroed counts."""
    response = client.get(
        "/api/v1/seller/dashboard/summary",
        headers={"Authorization": f"Bearer {make_access_token(99999)}"},
    )
    assert response.status_code == 401


def test_summary_is_scoped_to_the_jwt_client(client, two_tenants):
    seller_a_id, seller_b_id = two_tenants

    summary_a = client.get(
        "/api/v1/seller/dashboard/summary",
        headers={"Authorization": f"Bearer {make_access_token(seller_a_id)}"},
    )
    assert summary_a.status_code == 200
    body_a = summary_a.json()
    assert body_a == {
        "phone_number": "09120000001",
        "post_count": 2,
        "conversation_count": 3,
        "post_conversation_count": 1,
    }

    summary_b = client.get(
        "/api/v1/seller/dashboard/summary",
        headers={"Authorization": f"Bearer {make_access_token(seller_b_id)}"},
    )
    assert summary_b.status_code == 200
    body_b = summary_b.json()
    assert body_b == {
        "phone_number": "09120000002",
        "post_count": 1,
        "conversation_count": 0,
        "post_conversation_count": 0,
    }

    # Changing only the token (no other input) changes the tenant — no field
    # of the request can steer the counts to another seller's rows.
    assert body_a["post_count"] != body_b["post_count"]
    assert body_a["conversation_count"] != body_b["conversation_count"]


def test_summary_ignores_client_id_from_browser(client, two_tenants):
    """Seller A cannot steer the summary to seller B's rows: a `client_id`
    query param is ignored — the scope comes from the JWT alone."""
    seller_a_id, seller_b_id = two_tenants

    response = client.get(
        "/api/v1/seller/dashboard/summary",
        params={"client_id": str(seller_b_id)},
        headers={"Authorization": f"Bearer {make_access_token(seller_a_id)}"},
    )
    assert response.status_code == 200
    assert response.json()["phone_number"] == "09120000001"
    assert response.json()["post_count"] == 2
