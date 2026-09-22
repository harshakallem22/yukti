"""Database engine and session.

SQLite by default so the stack runs with no external service; the same models work
on Postgres via DATABASE_URL. See ADR 002 (amended).

The engine is bound lazily rather than at import. Binding at import would make the
database URL unchangeable for the life of the process, which forces tests to
reload modules — and reloading a declarative model module re-registers its tables
on the same MetaData and raises.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def configure(url: str | None = None) -> Engine:
    """(Re)bind the engine. Tests use this to point at a temporary database."""
    global _engine, _session_factory
    url = url or get_settings().database_url
    # check_same_thread=False: runs execute on background threads and share the
    # connection pool with request handlers.
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    _engine = create_engine(url, future=True, **kwargs)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure()
    return _engine  # type: ignore[return-value]


def _factory() -> sessionmaker[Session]:
    if _session_factory is None:
        configure()
    return _session_factory  # type: ignore[return-value]


def init_db() -> None:
    from apps.api.app import models  # noqa: F401 - registers mappers before create_all

    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    session = _factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    session = _factory()()
    try:
        yield session
    finally:
        session.close()
