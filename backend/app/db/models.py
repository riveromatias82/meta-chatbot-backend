"""ORM models for users, conversations, and messages."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Platform(str, enum.Enum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"


class ConversationStatus(str, enum.Enum):
    BOT_HANDLED = "BOT_HANDLED"
    REQUIRES_HUMAN = "REQUIRES_HUMAN"
    DISABLED = "DISABLED"


class SenderType(str, enum.Enum):
    USER = "USER"
    BOT = "BOT"
    HUMAN_AGENT = "HUMAN_AGENT"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_users_platform_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform, native_enum=False, length=32))
    platform_user_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_status_activity", "status", "last_activity_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, native_enum=False, length=32),
        default=ConversationStatus.BOT_HANDLED,
        index=True,
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.timestamp",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    sender_type: Mapped[SenderType] = mapped_column(Enum(SenderType, native_enum=False, length=32))
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
