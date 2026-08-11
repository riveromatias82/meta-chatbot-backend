"""Parse WhatsApp Cloud API and Instagram Graph API webhook payloads."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.models import Platform
from app.schemas.inbound import InboundMessage

logger = logging.getLogger(__name__)


def parse_webhook_payload(payload: dict[str, Any]) -> list[InboundMessage]:
    """Return normalized inbound text messages from a Meta webhook body."""
    object_type = str(payload.get("object") or "").lower()
    entries = payload.get("entry") or []
    messages: list[InboundMessage] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if object_type in {"whatsapp_business_account", "whatsapp"}:
            messages.extend(_parse_whatsapp_entry(entry))
        elif object_type in {"instagram", "page"}:
            messages.extend(_parse_instagram_entry(entry, default_platform=_platform_for_object(object_type)))
        else:
            # Unknown object: try both shapes so tests / mixed payloads still work.
            parsed = _parse_whatsapp_entry(entry) or _parse_instagram_entry(entry)
            messages.extend(parsed)
    return messages


def _platform_for_object(object_type: str) -> Platform:
    if object_type == "instagram":
        return Platform.INSTAGRAM
    return Platform.INSTAGRAM


def _parse_whatsapp_entry(entry: dict[str, Any]) -> list[InboundMessage]:
    messages: list[InboundMessage] = []
    for change in entry.get("changes") or []:
        if not isinstance(change, dict):
            continue
        value = change.get("value") or {}
        if not isinstance(value, dict):
            continue
        contacts = {c.get("wa_id"): c for c in (value.get("contacts") or []) if isinstance(c, dict)}
        for raw in value.get("messages") or []:
            if not isinstance(raw, dict):
                continue
            if raw.get("type") not in (None, "text"):
                logger.info("Skipping non-text WhatsApp message type=%s", raw.get("type"))
                continue
            text = ((raw.get("text") or {}) if isinstance(raw.get("text"), dict) else {}).get("body")
            if not text:
                continue
            sender = str(raw.get("from") or "")
            contact = contacts.get(sender) or {}
            profile = contact.get("profile") if isinstance(contact.get("profile"), dict) else {}
            name = profile.get("name") if isinstance(profile, dict) else None
            messages.append(
                InboundMessage(
                    platform=Platform.WHATSAPP,
                    platform_user_id=sender,
                    name=name,
                    text=str(text),
                    timestamp=_parse_timestamp(raw.get("timestamp")),
                    external_id=raw.get("id"),
                )
            )
    return messages


def _parse_instagram_entry(
    entry: dict[str, Any],
    default_platform: Platform = Platform.INSTAGRAM,
) -> list[InboundMessage]:
    messages: list[InboundMessage] = []
    for event in entry.get("messaging") or []:
        parsed = _parse_instagram_messaging_event(event, default_platform)
        if parsed:
            messages.append(parsed)
    for change in entry.get("changes") or []:
        if not isinstance(change, dict):
            continue
        value = change.get("value") or {}
        if isinstance(value, dict):
            for event in value.get("messaging") or []:
                parsed = _parse_instagram_messaging_event(event, default_platform)
                if parsed:
                    messages.append(parsed)
            # Some Instagram payloads put sender/message directly on `value`.
            parsed_value = _parse_instagram_messaging_event(value, default_platform)
            if parsed_value:
                messages.append(parsed_value)
    return messages


def _parse_instagram_messaging_event(
    event: dict[str, Any],
    platform: Platform,
) -> Optional[InboundMessage]:
    if not isinstance(event, dict):
        return None
    message = event.get("message")
    if not isinstance(message, dict):
        return None
    if message.get("is_echo") or event.get("message", {}).get("is_echo"):
        return None
    text = message.get("text")
    if not text:
        return None
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_id = str(sender.get("id") or event.get("from") or "")
    if not sender_id:
        return None
    return InboundMessage(
        platform=platform,
        platform_user_id=sender_id,
        name=None,
        text=str(text),
        timestamp=_parse_timestamp(event.get("timestamp") or message.get("timestamp")),
        external_id=message.get("mid") or message.get("id"),
    )


def _parse_timestamp(value: Any) -> datetime:
    now = datetime.now(timezone.utc)
    if value is None or value == "":
        return now
    try:
        numeric = int(value)
        if numeric > 10_000_000_000:
            numeric = numeric / 1000
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        logger.debug("Could not parse timestamp %r", value)
        return now
