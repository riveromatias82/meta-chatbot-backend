"""Webhook verification and inbound payload parsing tests."""

from sqlalchemy import select

from app.db.models import Conversation, Message, Platform, SenderType, User
from app.services.webhook_parser import parse_webhook_payload
from tests.conftest import INSTAGRAM_TEXT_PAYLOAD, WHATSAPP_STATUS_ONLY_PAYLOAD, WHATSAPP_TEXT_PAYLOAD


def test_webhook_verification_success(client):
    response = client.get(
        "/api/v1/webhooks",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test-verify-token",
            "hub.challenge": "challenge-token-42",
        },
    )
    assert response.status_code == 200
    assert response.text == "challenge-token-42"


def test_webhook_verification_rejects_bad_token(client):
    response = client.get(
        "/api/v1/webhooks",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-token-42",
        },
    )
    assert response.status_code == 403


def test_parse_whatsapp_text_payload():
    inbound = parse_webhook_payload(WHATSAPP_TEXT_PAYLOAD)
    assert len(inbound) == 1
    assert inbound[0].platform == Platform.WHATSAPP
    assert inbound[0].platform_user_id == "16315551181"
    assert inbound[0].name == "Jane Doe"
    assert inbound[0].text == "What are your opening hours?"
    assert inbound[0].external_id == "wamid.HBgNMTYzMTU1NTExODE"


def test_parse_instagram_text_payload():
    inbound = parse_webhook_payload(INSTAGRAM_TEXT_PAYLOAD)
    assert len(inbound) == 1
    assert inbound[0].platform == Platform.INSTAGRAM
    assert inbound[0].platform_user_id == "ig-user-567"
    assert inbound[0].text == "Hi, I need help with my order"


def test_parse_status_only_payload_yields_no_messages():
    assert parse_webhook_payload(WHATSAPP_STATUS_ONLY_PAYLOAD) == []


def test_whatsapp_payload_is_persisted(client, db, fake_meta):
    response = client.post("/api/v1/webhooks", json=WHATSAPP_TEXT_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["received"] == 1
    assert body["results"][0]["status"] == "bot_replied"

    user = db.scalar(select(User).where(User.platform_user_id == "16315551181"))
    assert user is not None
    assert user.platform == Platform.WHATSAPP
    assert user.name == "Jane Doe"

    conversation = db.scalar(select(Conversation).where(Conversation.user_id == user.id))
    assert conversation is not None

    messages = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id)))
    assert [item.sender_type for item in messages] == [SenderType.USER, SenderType.BOT]
    assert messages[0].text == "What are your opening hours?"
    assert fake_meta.sent[0]["recipient_id"] == "16315551181"


def test_instagram_payload_is_persisted(client, db):
    response = client.post("/api/v1/webhooks", json=INSTAGRAM_TEXT_PAYLOAD)
    assert response.status_code == 200
    user = db.scalar(select(User).where(User.platform_user_id == "ig-user-567"))
    assert user is not None
    assert user.platform == Platform.INSTAGRAM


def test_status_only_webhook_is_acknowledged_without_storage(client, db):
    response = client.post("/api/v1/webhooks", json=WHATSAPP_STATUS_ONLY_PAYLOAD)
    assert response.status_code == 200
    assert response.json()["received"] == 0
    assert db.scalar(select(User)) is None


def test_invalid_json_webhook_returns_400(client):
    response = client.post(
        "/api/v1/webhooks",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
