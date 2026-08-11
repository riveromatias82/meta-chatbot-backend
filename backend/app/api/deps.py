"""FastAPI dependencies."""

from collections.abc import Generator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db
from app.services.ai_engine import AIEngine
from app.services.conversation_service import ConversationService
from app.services.meta_client import MetaClient


def get_ai_engine(request: Request) -> AIEngine:
    return request.app.state.ai_engine


def get_meta_client(request: Request) -> MetaClient:
    return request.app.state.meta_client


def get_conversation_service(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Generator[ConversationService, None, None]:
    yield ConversationService(
        db=db,
        ai_engine=get_ai_engine(request),
        meta_client=get_meta_client(request),
        settings=settings,
    )
