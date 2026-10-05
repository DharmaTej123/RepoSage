"""FastAPI dependencies (DI wiring)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_session


def settings_dependency() -> Settings:
    return get_settings()


def db_session() -> Iterator[Session]:
    yield from get_session()
