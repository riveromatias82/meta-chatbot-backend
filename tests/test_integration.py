"""End-to-end flow: webhook ingest -> SQLite persistence -> Gemini -> Meta dispatch."""

from sqlalchemy import select

from app.db.models import Conversation, ConversationStatus, Message, SenderType, User
from app.services.ai_engine import AIReply, HANDOFF_FLAG
from tests.conftest import WHATSAPP_TEXT_PAYLOAD


def test_integration_webhook_to_automated_reply(client, db, fake_ai, fake_meta):
    fake_ai.reply = AIReply(
        text="We're open 9am–6pm Monday to Friday.",
        requires_human=False,
        raw_text="We're open 9am–6pm Monday to Friday.",
    )

    response = client.post("/api/v1/webhooks", json=WHATSAPP_TEXT_PAYLOAD)
    assert response.status_code == 200
    payload = response.json()
    assert payload["received"] == 1
    assert payload["results"][0]["status"] == "bot_replied"
    assert payload["results"][0]["sent"] is True

    user = db.scalar(select(User).where(User.platform_user_id == "16315551181"))
    assert user is not None
    conversation = db.scalar(select(Conversation).where(Conversation.user_id == user.id))
    assert conversation is not None
    assert conversation.status == ConversationStatus.BOT_HANDLED

    messages = list(
        db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id))
    )
    assert len(messages) == 2
    assert messages[0].sender_type == SenderType.USER
    assert messages[1].sender_type == SenderType.BOT
    assert messages[1].text == "We're open 9am–6pm Monday to Friday."

    assert len(fake_ai.calls) == 1
    assert fake_ai.calls[0][1] == "What are your opening hours?"
    assert fake_meta.sent == [
        {
            "platform": "whatsapp",
            "recipient_id": "16315551181",
            "text": "We're open 9am–6pm Monday to Friday.",
        }
    ]


def test_integration_handoff_skips_automated_reply(client, db, fake_ai, fake_meta):
    fake_ai.reply = AIReply(
        text="User requested a refund.",
        requires_human=True,
        raw_text=f"{HANDOFF_FLAG} User requested a refund.",
    )
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "contacts": [{"profile": {"name": "Jane Doe"}, "wa_id": "16315551181"}],
                            "messages": [
                                {
                                    "from": "16315551181",
                                    "id": "wamid.refund-1",
                                    "timestamp": "1710000000",
                                    "text": {"body": "I want a refund, this is ridiculous."},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/api/v1/webhooks", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["status"] == "requires_human"
    assert body["results"][0]["sent"] is False
    assert fake_meta.sent == []

    conversation = db.scalar(select(Conversation))
    assert conversation is not None
    assert conversation.status == ConversationStatus.REQUIRES_HUMAN
    messages = list(db.scalars(select(Message)))
    assert len(messages) == 1
    assert messages[0].sender_type == SenderType.USER


def test_integration_paused_conversation_stores_without_bot(client, db, fake_ai, fake_meta):
    first = client.post("/api/v1/webhooks", json=WHATSAPP_TEXT_PAYLOAD)
    assert first.status_code == 200
    conversation = db.scalar(select(Conversation))
    assert conversation is not None

    toggle = client.post(
        f"/api/v1/agent/conversations/{conversation.id}/toggle-bot",
        json={"status": "DISABLED"},
    )
    assert toggle.status_code == 200
    fake_meta.sent.clear()
    fake_ai.calls.clear()

    follow_up = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "contacts": [{"profile": {"name": "Jane Doe"}, "wa_id": "16315551181"}],
                            "messages": [
                                {
                                    "from": "16315551181",
                                    "id": "wamid.follow-up-2",
                                    "timestamp": "1710000100",
                                    "text": {"body": "Are you still there?"},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    response = client.post("/api/v1/webhooks", json=follow_up)
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "stored_only"
    assert fake_ai.calls == []
    assert fake_meta.sent == []

    db.expire_all()
    messages = list(db.scalars(select(Message).order_by(Message.id)))
    assert messages[-1].text == "Are you still there?"
    assert messages[-1].sender_type == SenderType.USER
