"""Conversation persistence and bot/human handoff orchestration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.db.models import Conversation, ConversationStatus, Message, Platform, SenderType, User
from app.schemas.inbound import InboundMessage
from app.services.ai_engine import AIEngine
from app.services.meta_client import MetaClient, MetaClientError

logger = logging.getLogger(__name__)


class ConversationNotFoundError(LookupError):
    pass


class ConversationService:
    def __init__(
        self,
        db: Session,
        ai_engine: AIEngine,
        meta_client: MetaClient,
        settings: Optional[Settings] = None,
    ) -> None:
        self.db = db
        self.ai_engine = ai_engine
        self.meta_client = meta_client
        self.settings = settings or get_settings()

    def get_or_create_user(self, inbound: InboundMessage) -> User:
        user = self.db.scalar(
            select(User).where(
                User.platform == inbound.platform,
                User.platform_user_id == inbound.platform_user_id,
            )
        )
        if user is None:
            user = User(
                platform=inbound.platform,
                platform_user_id=inbound.platform_user_id,
                name=inbound.name,
            )
            self.db.add(user)
            self.db.flush()
            return user
        if inbound.name and user.name != inbound.name:
            user.name = inbound.name
        return user

    def get_or_create_conversation(self, user: User) -> Conversation:
        conversation = self.db.scalar(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.last_activity_at.desc())
        )
        if conversation is None:
            conversation = Conversation(
                user_id=user.id,
                status=ConversationStatus.BOT_HANDLED,
                last_activity_at=datetime.now(timezone.utc),
            )
            self.db.add(conversation)
            self.db.flush()
        return conversation

    def add_message(
        self,
        conversation: Conversation,
        sender_type: SenderType,
        text: str,
        timestamp: Optional[datetime] = None,
        external_id: Optional[str] = None,
    ) -> Optional[Message]:
        if external_id:
            existing = self.db.scalar(select(Message).where(Message.external_id == external_id))
            if existing is not None:
                logger.info("Skipping duplicate inbound message external_id=%s", external_id)
                return None

        message = Message(
            conversation_id=conversation.id,
            sender_type=sender_type,
            text=text,
            timestamp=timestamp or datetime.now(timezone.utc),
            external_id=external_id,
        )
        conversation.last_activity_at = message.timestamp
        self.db.add(message)
        self.db.flush()
        return message

    def list_conversations(
        self,
        status: Optional[ConversationStatus] = None,
        channel: Optional[Platform] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Conversation], int]:
        query = select(Conversation).options(joinedload(Conversation.user))
        count_query = select(func.count(Conversation.id))
        if status is not None:
            query = query.where(Conversation.status == status)
            count_query = count_query.where(Conversation.status == status)
        if channel is not None:
            query = query.join(User).where(User.platform == channel)
            count_query = count_query.join(User).where(User.platform == channel)
        total = int(self.db.scalar(count_query) or 0)
        items = list(
            self.db.scalars(
                query.order_by(Conversation.last_activity_at.desc()).offset(skip).limit(limit)
            ).unique()
        )
        return items, total

    def get_conversation(self, conversation_id: int) -> Conversation:
        conversation = self.db.scalar(
            select(Conversation)
            .options(joinedload(Conversation.user), joinedload(Conversation.messages))
            .where(Conversation.id == conversation_id)
        )
        if conversation is None:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        return conversation

    def list_messages(self, conversation_id: int) -> list[Message]:
        conversation = self.db.scalar(select(Conversation).where(Conversation.id == conversation_id))
        if conversation is None:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        return list(
            self.db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.timestamp.asc(), Message.id.asc())
            )
        )

    def recent_history(self, conversation_id: int) -> list[Message]:
        limit = self.settings.conversation_history_limit
        rows = list(
            self.db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.timestamp.desc(), Message.id.desc())
                .limit(limit)
            )
        )
        rows.reverse()
        return rows

    def toggle_status(self, conversation_id: int, status: ConversationStatus) -> Conversation:
        conversation = self.get_conversation(conversation_id)
        conversation.status = status
        conversation.last_activity_at = datetime.now(timezone.utc)
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    async def handle_inbound(self, inbound: InboundMessage) -> dict[str, object]:
        user = self.get_or_create_user(inbound)
        conversation = self.get_or_create_conversation(user)
        stored = self.add_message(
            conversation,
            SenderType.USER,
            inbound.text,
            timestamp=inbound.timestamp,
            external_id=inbound.external_id,
        )
        self.db.commit()
        if stored is None:
            return {"status": "duplicate", "conversation_id": conversation.id}

        if conversation.status != ConversationStatus.BOT_HANDLED:
            logger.info(
                "Bot paused for conversation_id=%s status=%s",
                conversation.id,
                conversation.status.value,
            )
            return {
                "status": "stored_only",
                "conversation_id": conversation.id,
                "bot_active": False,
            }

        history = self.recent_history(conversation.id)
        prior = [message for message in history if message.id != stored.id]
        reply = self.ai_engine.generate_reply(prior, inbound.text)
        if not reply.text.strip() and not reply.requires_human:
            reply.requires_human = True

        if reply.requires_human:
            conversation.status = ConversationStatus.REQUIRES_HUMAN
            conversation.last_activity_at = datetime.now(timezone.utc)
            self.db.add(conversation)
            self.db.commit()
            logger.info("Handoff triggered for conversation_id=%s", conversation.id)
            return {
                "status": "requires_human",
                "conversation_id": conversation.id,
                "sent": False,
            }

        dispatched = False
        try:
            await self.meta_client.send_text(user.platform, user.platform_user_id, reply.text)
            dispatched = True
        except MetaClientError:
            logger.exception("Failed to dispatch bot reply for conversation_id=%s", conversation.id)

        self.add_message(conversation, SenderType.BOT, reply.text)
        self.db.commit()
        return {
            "status": "bot_replied",
            "conversation_id": conversation.id,
            "sent": dispatched,
        }

    async def agent_reply(self, conversation_id: int, text: str) -> tuple[Message, bool]:
        conversation = self.get_conversation(conversation_id)
        user = conversation.user
        dispatched = False
        try:
            await self.meta_client.send_text(user.platform, user.platform_user_id, text)
            dispatched = True
        except MetaClientError:
            logger.exception("Failed to dispatch human reply for conversation_id=%s", conversation.id)
            raise

        message = self.add_message(conversation, SenderType.HUMAN_AGENT, text)
        conversation.status = ConversationStatus.REQUIRES_HUMAN
        conversation.last_activity_at = datetime.now(timezone.utc)
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(message)
        return message, dispatched
