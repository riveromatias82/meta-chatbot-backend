"""Meta webhook verification and inbound event ingestion."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from app.api.deps import get_conversation_service
from app.config import Settings, get_settings
from app.services.conversation_service import ConversationService
from app.services.webhook_parser import parse_webhook_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("", response_class=PlainTextResponse)
@router.get("/", response_class=PlainTextResponse)
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> str:
    """Meta webhook handshake. Returns `hub.challenge` when the verify token matches."""
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        logger.info("Webhook verified successfully")
        return hub_challenge or ""
    logger.warning("Webhook verification failed mode=%s", hub_mode)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")


@router.post("")
@router.post("/")
async def receive_webhook(
    request: Request,
    service: ConversationService = Depends(get_conversation_service),
) -> dict[str, Any]:
    """Ingest WhatsApp Cloud API and Instagram Graph API events."""
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Invalid webhook JSON: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook payload must be an object")

    inbound_messages = parse_webhook_payload(payload)
    results: list[dict[str, Any]] = []
    for inbound in inbound_messages:
        try:
            result = await service.handle_inbound(inbound)
            results.append(result)
        except Exception:
            logger.exception(
                "Failed to process inbound message platform=%s user=%s",
                inbound.platform,
                inbound.platform_user_id,
            )
            results.append({"status": "error", "platform": inbound.platform.value})

    return {
        "status": "ok",
        "received": len(inbound_messages),
        "results": results,
    }
