"""Outbound Meta Graph API client for WhatsApp Cloud API and Instagram Messaging."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_none

from app.config import Settings, get_settings
from app.db.models import Platform

logger = logging.getLogger(__name__)


class MetaClientError(RuntimeError):
    """Raised when Meta Graph API rejects or cannot send a message."""


class MetaClient:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        return self._http_client

    async def send_text(self, platform: Platform | str, recipient_id: str, text: str) -> dict[str, Any]:
        platform_value = Platform(platform) if not isinstance(platform, Platform) else platform
        if not text.strip():
            raise MetaClientError("Cannot send an empty message")
        if not self.settings.meta_access_token:
            raise MetaClientError("META_ACCESS_TOKEN is not configured")

        if platform_value == Platform.WHATSAPP:
            return await self._send_whatsapp(recipient_id, text)
        if platform_value == Platform.INSTAGRAM:
            return await self._send_instagram(recipient_id, text)
        raise MetaClientError(f"Unsupported platform: {platform_value}")

    async def _send_whatsapp(self, to: str, text: str) -> dict[str, Any]:
        if not self.settings.phone_number_id:
            raise MetaClientError("PHONE_NUMBER_ID is not configured")
        url = f"{self.settings.meta_graph_root}/{self.settings.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        return await self._post(url, payload)

    async def _send_instagram(self, recipient_id: str, text: str) -> dict[str, Any]:
        if not self.settings.instagram_account_id:
            raise MetaClientError("INSTAGRAM_ACCOUNT_ID is not configured")
        url = f"{self.settings.meta_graph_root}/{self.settings.instagram_account_id}/messages"
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        }
        return await self._post(url, payload)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_none(),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    )
    async def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.settings.meta_access_token}",
            "Content-Type": "application/json",
        }
        logger.info("Dispatching Meta message url=%s", url)
        response = await self._client().post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.error("Meta API error status=%s body=%s", response.status_code, response.text)
            raise MetaClientError(f"Meta API error {response.status_code}: {response.text}")
        try:
            return response.json()
        except ValueError:
            return {"status": "ok", "raw": response.text}
