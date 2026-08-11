"""Shared fixtures and fakes for the test suite."""

from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.session import SessionLocal, create_db_engine, init_db
from app.main import create_app
from app.services.ai_engine import AIReply


class FakeAIEngine:
    def __init__(self, reply: AIReply | Callable[..., AIReply] | None = None) -> None:
        self.reply = reply or AIReply(
            text="Sure — our store is open 9am–6pm Monday to Friday.",
            requires_human=False,
            raw_text="Sure — our store is open 9am–6pm Monday to Friday.",
        )
        self.calls: list[tuple[list[Any], str]] = []

    def generate_reply(self, history, user_text: str) -> AIReply:
        self.calls.append((list(history), user_text))
        if callable(self.reply):
            return self.reply(history, user_text)
        return self.reply


class FakeMetaClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = False

    async def send_text(self, platform, recipient_id: str, text: str) -> dict[str, Any]:
        if self.fail:
            from app.services.meta_client import MetaClientError

            raise MetaClientError("forced failure")
        payload = {
            "platform": getattr(platform, "value", platform),
            "recipient_id": recipient_id,
            "text": text,
        }
        self.sent.append(payload)
        return {"messages": [{"id": "wamid.fake-test"}]}

    async def aclose(self) -> None:
        return None


WHATSAPP_TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "15550555555",
                            "phone_number_id": "PHONE_NUMBER_ID",
                        },
                        "contacts": [
                            {
                                "profile": {"name": "Jane Doe"},
                                "wa_id": "16315551181",
                            }
                        ],
                        "messages": [
                            {
                                "from": "16315551181",
                                "id": "wamid.HBgNMTYzMTU1NTExODE",
                                "timestamp": "1518694315",
                                "text": {"body": "What are your opening hours?"},
                                "type": "text",
                            }
                        ],
                    },
                }
            ],
        }
    ],
}

INSTAGRAM_TEXT_PAYLOAD = {
    "object": "instagram",
    "entry": [
        {
            "id": "INSTAGRAM_ACCOUNT_ID",
            "time": 1569262486,
            "messaging": [
                {
                    "sender": {"id": "ig-user-567"},
                    "recipient": {"id": "INSTAGRAM_ACCOUNT_ID"},
                    "timestamp": 1569262485000,
                    "message": {
                        "mid": "mid.INSTAGRAM.123",
                        "text": "Hi, I need help with my order",
                    },
                }
            ],
        }
    ],
}

WHATSAPP_STATUS_ONLY_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "statuses": [
                            {
                                "id": "wamid.status",
                                "status": "delivered",
                                "timestamp": "1518694316",
                                "recipient_id": "16315551181",
                            }
                        ],
                    },
                }
            ],
        }
    ],
}


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(
        app_name="meta-chatbot-backend-test",
        app_env="test",
        log_level="WARNING",
        database_url="sqlite:///:memory:",
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.6-flash",
        meta_access_token="test-meta-token",
        meta_verify_token="test-verify-token",
        phone_number_id="phone-123",
        instagram_account_id="ig-123",
    )


@pytest.fixture
def engine(tmp_path, settings):
    # File-backed SQLite so the TestClient session and assertion session share one DB.
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    settings.database_url = database_url
    db_engine = create_db_engine(database_url)
    init_db(db_engine)
    yield db_engine
    db_engine.dispose()


@pytest.fixture
def fake_ai() -> FakeAIEngine:
    return FakeAIEngine()


@pytest.fixture
def fake_meta() -> FakeMetaClient:
    return FakeMetaClient()


@pytest.fixture
def app(settings, engine, fake_ai, fake_meta):
    application = create_app(
        settings=settings,
        engine=engine,
        ai_engine=fake_ai,
        meta_client=fake_meta,
    )
    application.dependency_overrides[get_settings] = lambda: settings
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
