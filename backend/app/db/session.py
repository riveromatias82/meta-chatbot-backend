"""Database engine, WAL configuration, and session factory."""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, class_=Session, expire_on_commit=False)


def _is_sqlite_memory_url(database_url: str) -> bool:
    """True for in-memory SQLite URLs (`sqlite://`, `sqlite:///:memory:`, etc.)."""
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return False
    database = url.database
    return not database or database == ":memory:"


def _ensure_sqlite_directory(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return
    database = url.database
    if not database or database == ":memory:":
        return
    path = Path(database)
    if path.parent and str(path.parent) not in {"", "."}:
        path.parent.mkdir(parents=True, exist_ok=True)


def _enable_sqlite_wal(engine: Engine) -> None:
    """Enable WAL + foreign keys on every SQLite connection."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


def create_db_engine(database_url: str | None = None) -> Engine:
    settings = get_settings()
    url = database_url or settings.database_url
    _ensure_sqlite_directory(url)

    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {"future": True}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if _is_sqlite_memory_url(url):
            engine_kwargs["poolclass"] = StaticPool

    engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
    if url.startswith("sqlite"):
        _enable_sqlite_wal(engine)
        with engine.connect() as connection:
            mode = connection.execute(text("PRAGMA journal_mode")).scalar()
            logger.info("SQLite journal_mode=%s url=%s", mode, url)
    return engine


def configure_engine(engine: Engine) -> Engine:
    """Bind the global session factory to an engine (used by tests)."""
    global _engine
    _engine = engine
    SessionLocal.configure(bind=engine)
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        configure_engine(create_db_engine())
    return _engine


def init_db(engine: Engine | None = None) -> None:
    bind = engine or get_engine()
    Base.metadata.create_all(bind=bind)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
