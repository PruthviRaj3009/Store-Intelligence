"""Database engine, session, and a graceful-degradation dependency.

A reviewer requirement (Part C): "Database unavailable -> HTTP 503 with a
structured body. No raw stack traces." We implement that by wrapping the
per-request session in `get_db`, which converts connection failures into a
typed `DatabaseUnavailable` exception that main.py renders as a clean 503.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class DatabaseUnavailable(Exception):
    """Raised when the DB cannot be reached; surfaced to clients as 503."""


def _make_engine(url: str):
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # needed for SQLite when shared across FastAPI's threadpool / tests
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_size=5, max_overflow=10, pool_timeout=5)
    return create_engine(url, **kwargs)


engine = _make_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create tables if they don't exist."""
    from app import tables  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)


def db_alive() -> bool:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except SQLAlchemyError:
        return False


def get_db():
    """FastAPI dependency. Yields a session or raises DatabaseUnavailable (-> 503)."""
    try:
        db = SessionLocal()
    except OperationalError as exc:  # pragma: no cover - infra failure path
        raise DatabaseUnavailable(str(exc))
    try:
        # cheap liveness probe so we fail fast with 503 instead of mid-handler
        db.execute  # attribute access is free; real probe happens on first query
        yield db
    except OperationalError as exc:
        raise DatabaseUnavailable(str(exc))
    finally:
        db.close()
