"""FastAPI application factory, middleware, and route registration."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from app.api.agent import router as agent_router
from app.api.webhooks import router as webhooks_router
from app.config import Settings, get_settings
from app.db.session import configure_engine, create_db_engine, init_db
from app.schemas import HealthResponse
from app.services.ai_engine import AIEngine
from app.services.meta_client import MetaClient

logger = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    ai_engine: AIEngine | None = None,
    meta_client: MetaClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db_engine = engine or create_db_engine(settings.database_url)
        configure_engine(db_engine)
        init_db(db_engine)
        app.state.settings = settings
        app.state.engine = db_engine
        app.state.ai_engine = ai_engine or AIEngine(settings)
        app.state.meta_client = meta_client or MetaClient(settings)
        logger.info("Application started env=%s", settings.app_env)
        try:
            yield
        finally:
            client = getattr(app.state, "meta_client", None)
            if client is not None:
                await client.aclose()
            db_engine.dispose()
            logger.info("Application shutdown complete")

    app = FastAPI(
        title="Meta Chatbot Backend",
        description=(
            "PoC backend for an AI-powered WhatsApp and Instagram chatbot "
            "with Gemini replies and human handoff."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_origin_list != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(webhooks_router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", app=settings.app_name, environment=settings.app_env)

    return app


app = create_app()
