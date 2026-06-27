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

import pytest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from main import app
from config import settings

WEBHOOK_SECRET = "test_identification_key"


def _valid_payload(
    *,
    text="hello world",
    conversation_id="conv_abc123",
    message_id="msg_001",
):
    return {
        "type": "NEW_CHATBOT_MESSAGE",
        "new_chatbot_message": {
            "text": text,
            "id": message_id,
            "conversation": {"id": conversation_id, "type": "BOT"},
            "sender": {"type": "HUMAN"},
            "type": "TEXT",
            "sent_at": "2024-10-20T12:00:00Z",
        },
    }


@pytest.fixture(autouse=True)
def mock_settings(mocker):
    mocker.patch.object(settings, "DIVAR_IDENTIFICATION_KEY", WEBHOOK_SECRET)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


def test_valid_auth_and_payload_schedules_background_task(client, mocker):
    mock_handle = mocker.patch(
        "api.webhook.handle_bot_reply", new_callable=AsyncMock
    )

    response = client.post(
        "/api/v1/webhook/my_client_id",
        json=_valid_payload(text="قیمت iphone 13", conversation_id="conv_123"),
        headers={"Authorization": WEBHOOK_SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    mock_handle.assert_called_once_with(
        "my_client_id", "conv_123", "قیمت iphone 13"
    )


def test_missing_authorization_header_rejected_401(client, mocker):
    mock_handle = mocker.patch(
        "api.webhook.handle_bot_reply", new_callable=AsyncMock
    )

    response = client.post(
        "/api/v1/webhook/my_client_id",
        json=_valid_payload(),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    mock_handle.assert_not_called()


def test_incorrect_authorization_header_rejected_401(client, mocker):
    mock_handle = mocker.patch(
        "api.webhook.handle_bot_reply", new_callable=AsyncMock
    )

    response = client.post(
        "/api/v1/webhook/my_client_id",
        json=_valid_payload(),
        headers={"Authorization": "wrong_secret"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    mock_handle.assert_not_called()


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------


def test_malformed_body_missing_required_fields_returns_422(client, mocker):
    mock_handle = mocker.patch(
        "api.webhook.handle_bot_reply", new_callable=AsyncMock
    )

    response = client.post(
        "/api/v1/webhook/my_client_id",
        json={
            "type": "NEW_CHATBOT_MESSAGE",
            "new_chatbot_message": {
                "text": "hello"
                # missing required fields: id, conversation, sender, type, sent_at
            },
        },
        headers={"Authorization": WEBHOOK_SECRET},
    )

    assert response.status_code == 422
    mock_handle.assert_not_called()


def test_ignored_when_new_chatbot_message_is_none(client, mocker):
    mock_handle = mocker.patch(
        "api.webhook.handle_bot_reply", new_callable=AsyncMock
    )

    response = client.post(
        "/api/v1/webhook/my_client_id",
        json={"type": "NEW_CHATBOT_MESSAGE", "new_chatbot_message": None},
        headers={"Authorization": WEBHOOK_SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    mock_handle.assert_not_called()


# ---------------------------------------------------------------------------
# client_id pass-through
# ---------------------------------------------------------------------------


def test_client_id_path_param_passed_through_unchanged(client, mocker):
    """Phase 1: client_id is accepted but unused for any lookup — only passed through."""
    mock_handle = mocker.patch(
        "api.webhook.handle_bot_reply", new_callable=AsyncMock
    )

    response = client.post(
        "/api/v1/webhook/seller_xyz_789",
        json=_valid_payload(text="hello", conversation_id="conv_456"),
        headers={"Authorization": WEBHOOK_SECRET},
    )

    assert response.status_code == 200
    # The first positional arg to handle_bot_reply should be the exact client_id
    # from the URL path, unmodified
    call_args = mock_handle.call_args
    assert call_args.args[0] == "seller_xyz_789"
    assert call_args.args[1] == "conv_456"
    assert call_args.args[2] == "hello"


# ---------------------------------------------------------------------------
# Realistic Divar payload from docs/chat/chatbot_conversations.md
# ---------------------------------------------------------------------------


def test_realistic_divar_webhook_payload(client, mocker):
    """
    Payload shape matching the literal example in
    docs/chat/chatbot_conversations.md:
      type: NEW_CHATBOT_MESSAGE
      new_chatbot_message.text, .id, .conversation.id, .conversation.type: "BOT",
      .sender.type: "HUMAN", .type: "TEXT", .sent_at

    NOTE: The docs show sent_at as an integer (microseconds: 1729429926140000),
    but schemas/webhook.py declares sent_at as datetime.  Pydantic v2 cannot parse
    such a large integer as a Unix timestamp, so this test uses an ISO 8601 string
    instead.  The sent_at format mismatch is a real finding — see the final summary.

    NOTE: schemas/webhook.py already includes new_chatbot_message.id and
    new_chatbot_message.type fields, even though PLAN.md task 1.3 marks them as
    "[ ] not yet done."  The schema is ahead of the plan here — revisit the plan
    checkbox when confirmed.
    """
    mock_handle = mocker.patch(
        "api.webhook.handle_bot_reply", new_callable=AsyncMock
    )

    payload = {
        "type": "NEW_CHATBOT_MESSAGE",
        "new_chatbot_message": {
            "text": "hello world",
            "id": "msg_abc123",
            "conversation": {
                "id": "62c82c02-6a71-4501-a1fd-4bf226b3aa78",
                "type": "BOT",
            },
            "sender": {"type": "HUMAN"},
            "type": "TEXT",
            "sent_at": "2024-10-20T16:52:06Z",
        },
    }

    response = client.post(
        "/api/v1/webhook/client_001",
        json=payload,
        headers={"Authorization": WEBHOOK_SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    mock_handle.assert_called_once_with(
        "client_001",
        "62c82c02-6a71-4501-a1fd-4bf226b3aa78",
        "hello world",
    )
