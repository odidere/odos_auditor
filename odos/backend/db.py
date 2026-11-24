"""Database access. One engine factory used by the agent, API, CLI and UI.

The URL comes from, in order: ``DATABASE_URL``; ``database.url`` in config;
``POSTGRES_*`` environment variables (when ``POSTGRES_HOST`` is set);
otherwise a local SQLite file ``odos.db``.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

from odos.config import section


def database_url() -> str | URL:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    configured = section("database").get("url")
    if configured:
        return configured
    if os.getenv("POSTGRES_HOST"):
        return URL.create(
            "postgresql+psycopg2",
            username=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),  # URL.create escapes special characters
            host=os.getenv("POSTGRES_HOST"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "odos_observability"),
        )
    return "sqlite:///./odos.db"


@lru_cache(maxsize=None)
def _engine_for(url: str | URL) -> Engine:
    kwargs = {"pool_pre_ping": True}
    if str(url).startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def get_engine(url: str | URL | None = None) -> Engine:
    return _engine_for(url or database_url())


def session_factory(engine: Engine | None = None) -> sessionmaker:
    return sessionmaker(bind=engine or get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    session = session_factory(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> Engine:
    """Create any missing Odos tables (safe to run repeatedly)."""
    from odos.backend.models import Base

    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    return engine


# --- backwards-compatible names -------------------------------------------
def get_db_engine() -> Engine:
    return get_engine()


def get_db_connection():
    """DB-API connection from the shared engine's pool (caller must close it)."""
    return get_engine().raw_connection()
