"""Normalized inbound webhook event."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.db.models import Platform


@dataclass(slots=True)
class InboundMessage:
    platform: Platform
    platform_user_id: str
    name: Optional[str]
    text: str
    timestamp: datetime
    external_id: Optional[str] = None
