"""Agent REST API tests: listing, history, manual reply, and bot toggle."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Conversation, ConversationStatus, Message, Platform, SenderType, User
from tests.conftest import FakeMetaClient


def _seed_conversation(
    db: Session,
    *,
    platform: Platform = Platform.WHATSAPP,
    status: ConversationStatus = ConversationStatus.REQUIRES_HUMAN,
    platform_user_id: str = "16315551181",
    name: str = "Jane Doe",
) -> Conversation:
    user = User(platform=platform, platform_user_id=platform_user_id, name=name)
    db.add(user)
    db.flush()
    conversation = Conversation(
        user_id=user.id,
        status=status,
        last_activity_at=datetime.now(timezone.utc),
    )
    db.add(conversation)
    db.flush()
    db.add_all(
        [
            Message(
                conversation_id=conversation.id,
                sender_type=SenderType.USER,
                text="I need a human",
                timestamp=datetime.now(timezone.utc),
            ),
            Message(
                conversation_id=conversation.id,
                sender_type=SenderType.BOT,
                text="Let me check that.",
                timestamp=datetime.now(timezone.utc),
            ),
        ]
    )
    db.commit()
    db.refresh(conversation)
    return conversation


def test_list_conversations_filters_by_status_and_channel(client, db):
    _seed_conversation(db, platform=Platform.WHATSAPP, status=ConversationStatus.REQUIRES_HUMAN)
    _seed_conversation(
        db,
        platform=Platform.INSTAGRAM,
        status=ConversationStatus.BOT_HANDLED,
        platform_user_id="ig-99",
        name="Alex",
    )

    human = client.get("/api/v1/agent/conversations", params={"status": "REQUIRES_HUMAN"})
    assert human.status_code == 200
    assert human.json()["total"] == 1
    assert human.json()["items"][0]["status"] == "REQUIRES_HUMAN"

    ig = client.get("/api/v1/agent/conversations", params={"channel": "instagram"})
    assert ig.status_code == 200
    assert ig.json()["total"] == 1
    assert ig.json()["items"][0]["user"]["platform"] == "instagram"


def test_get_conversation_messages(client, db):
    conversation = _seed_conversation(db)
    response = client.get(f"/api/v1/agent/conversations/{conversation.id}/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["items"][0]["sender_type"] == "USER"
    assert body["items"][1]["sender_type"] == "BOT"


def test_missing_conversation_returns_404(client):
    response = client.get("/api/v1/agent/conversations/999/messages")
    assert response.status_code == 404


def test_agent_reply_dispatches_and_pauses_bot(client, db, fake_meta: FakeMetaClient):
    conversation = _seed_conversation(db, status=ConversationStatus.BOT_HANDLED)
    response = client.post(
        f"/api/v1/agent/conversations/{conversation.id}/reply",
        json={"text": "Hi Jane, I'm a human agent. I'll help with your refund."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dispatched"] is True
    assert body["conversation_status"] == "REQUIRES_HUMAN"
    assert body["message"]["sender_type"] == "HUMAN_AGENT"
    assert fake_meta.sent[-1]["text"].startswith("Hi Jane")
    assert fake_meta.sent[-1]["recipient_id"] == "16315551181"

    db.expire_all()
    stored = db.get(Conversation, conversation.id)
    assert stored is not None
    assert stored.status == ConversationStatus.REQUIRES_HUMAN


def test_toggle_bot_to_disabled_and_back(client, db):
    conversation = _seed_conversation(db, status=ConversationStatus.REQUIRES_HUMAN)

    disabled = client.post(
        f"/api/v1/agent/conversations/{conversation.id}/toggle-bot",
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["conversation"]["status"] == "DISABLED"

    resumed = client.post(
        f"/api/v1/agent/conversations/{conversation.id}/toggle-bot",
        json={"status": "BOT_HANDLED"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["conversation"]["status"] == "BOT_HANDLED"


def test_toggle_bot_rejects_requires_human(client, db):
    conversation = _seed_conversation(db)
    response = client.post(
        f"/api/v1/agent/conversations/{conversation.id}/toggle-bot",
        json={"status": "REQUIRES_HUMAN"},
    )
    assert response.status_code == 400


def test_agent_reply_returns_502_when_meta_fails(client, db, fake_meta: FakeMetaClient):
    conversation = _seed_conversation(db)
    fake_meta.fail = True
    response = client.post(
        f"/api/v1/agent/conversations/{conversation.id}/reply",
        json={"text": "Hello"},
    )
    assert response.status_code == 502
