"""Unit tests for outbound Meta Graph API dispatch."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.db.models import Platform
from app.services.meta_client import MetaClient, MetaClientError


def _settings() -> Settings:
    return Settings(
        meta_access_token="test-token",
        phone_number_id="phone-123",
        instagram_account_id="ig-123",
        meta_graph_api_base="https://graph.facebook.com",
        meta_graph_api_version="v21.0",
    )


@pytest.mark.asyncio
async def test_send_whatsapp_posts_to_phone_number_messages():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = request.read().decode()
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"messages": [{"id": "wamid.ok"}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = MetaClient(settings=_settings(), http_client=http_client)
        result = await client.send_text(Platform.WHATSAPP, "16315551181", "Hello there")

    assert result["messages"][0]["id"] == "wamid.ok"
    assert captured["url"] == "https://graph.facebook.com/v21.0/phone-123/messages"
    assert captured["authorization"] == "Bearer test-token"
    assert "16315551181" in str(captured["json"])
    assert "Hello there" in str(captured["json"])


@pytest.mark.asyncio
async def test_send_instagram_posts_to_account_messages():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = request.read().decode()
        return httpx.Response(200, json={"message_id": "mid.ok"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = MetaClient(settings=_settings(), http_client=http_client)
        result = await client.send_text(Platform.INSTAGRAM, "ig-user-1", "Hi from agent")

    assert result["message_id"] == "mid.ok"
    assert captured["url"] == "https://graph.facebook.com/v21.0/ig-123/messages"
    assert "ig-user-1" in str(captured["json"])


@pytest.mark.asyncio
async def test_send_text_raises_on_meta_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "invalid token"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = MetaClient(settings=_settings(), http_client=http_client)
        with pytest.raises(MetaClientError):
            await client.send_text(Platform.WHATSAPP, "16315551181", "Hello")
