"""REST API for human agents and operator frontends."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_conversation_service
from app.db.models import ConversationStatus, Platform
from app.schemas import (
    AgentReplyRequest,
    AgentReplyResponse,
    ConversationListResponse,
    ConversationRead,
    MessageListResponse,
    MessageRead,
    ToggleBotRequest,
    ToggleBotResponse,
)
from app.services.conversation_service import ConversationNotFoundError, ConversationService
from app.services.meta_client import MetaClientError

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    status_filter: ConversationStatus | None = Query(default=None, alias="status"),
    channel: Platform | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationListResponse:
    items, total = service.list_conversations(
        status=status_filter,
        channel=channel,
        skip=skip,
        limit=limit,
    )
    return ConversationListResponse(
        items=[ConversationRead.model_validate(item) for item in items],
        total=total,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: int,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationRead:
    try:
        conversation = service.get_conversation(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ConversationRead.model_validate(conversation)


@router.get("/conversations/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: int,
    service: ConversationService = Depends(get_conversation_service),
) -> MessageListResponse:
    try:
        messages = service.list_messages(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return MessageListResponse(
        items=[MessageRead.model_validate(message) for message in messages],
        total=len(messages),
    )


@router.post("/conversations/{conversation_id}/reply", response_model=AgentReplyResponse)
async def reply_as_agent(
    conversation_id: int,
    payload: AgentReplyRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> AgentReplyResponse:
    try:
        message, dispatched = await service.agent_reply(conversation_id, payload.text)
        conversation = service.get_conversation(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MetaClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to dispatch message to Meta: {exc}",
        ) from exc
    return AgentReplyResponse(
        message=MessageRead.model_validate(message),
        dispatched=dispatched,
        conversation_status=conversation.status,
    )


@router.post("/conversations/{conversation_id}/toggle-bot", response_model=ToggleBotResponse)
def toggle_bot(
    conversation_id: int,
    payload: ToggleBotRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ToggleBotResponse:
    if payload.status not in {ConversationStatus.BOT_HANDLED, ConversationStatus.DISABLED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="toggle-bot accepts BOT_HANDLED or DISABLED",
        )
    try:
        conversation = service.toggle_status(conversation_id, payload.status)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ToggleBotResponse(conversation=ConversationRead.model_validate(conversation))
