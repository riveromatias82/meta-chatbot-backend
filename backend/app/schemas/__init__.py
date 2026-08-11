"""Pydantic v2 request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ConversationStatus, Platform, SenderType


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRead(ORMModel):
    id: int
    platform: Platform
    platform_user_id: str
    name: Optional[str] = None
    created_at: datetime


class ConversationRead(ORMModel):
    id: int
    user_id: int
    status: ConversationStatus
    last_activity_at: datetime
    user: Optional[UserRead] = None


class MessageRead(ORMModel):
    id: int
    conversation_id: int
    sender_type: SenderType
    text: str
    timestamp: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationRead]
    total: int


class MessageListResponse(BaseModel):
    items: list[MessageRead]
    total: int


class AgentReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class AgentReplyResponse(BaseModel):
    message: MessageRead
    dispatched: bool
    conversation_status: ConversationStatus


class ToggleBotRequest(BaseModel):
    status: ConversationStatus


class ToggleBotResponse(BaseModel):
    conversation: ConversationRead


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
