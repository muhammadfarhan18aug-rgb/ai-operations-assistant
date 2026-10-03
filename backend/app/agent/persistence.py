"""Durable Postgres-backed checkpoint support for the LangGraph foundation."""

from __future__ import annotations

import asyncio
import logging
import sys

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings

logger = logging.getLogger(__name__)


def _configure_windows_event_loop() -> None:
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except AttributeError:
            pass


def _normalize_postgres_url(conn_string: str) -> str:
    normalized = conn_string.strip()
    if normalized.startswith("postgresql+asyncpg://"):
        return normalized.replace("postgresql+asyncpg://", "postgresql://", 1)
    if normalized.startswith("postgresql+psycopg://"):
        return normalized.replace("postgresql+psycopg://", "postgresql://", 1)
    return normalized


async def create_postgres_checkpointer(conn_string: str | None = None) -> AsyncPostgresSaver | None:
    """Create and initialize a durable Postgres-backed checkpointer."""
    _configure_windows_event_loop()
    url = _normalize_postgres_url(conn_string or get_settings().database_url)
    if not url.startswith("postgresql://"):
        return None

    try:
        connection = await psycopg.AsyncConnection.connect(
            url,
            autocommit=True,
            prepare_threshold=0,
        )
        saver = AsyncPostgresSaver(conn=connection)
        await saver.setup()
        return saver
    except Exception:
        logger.warning("Could not initialize Postgres LangGraph checkpoint saver.", exc_info=True)
        return None


def create_default_checkpointer() -> AsyncPostgresSaver | None:
    """Return a connected Postgres checkpointer when the database is reachable."""
    _configure_windows_event_loop()
    try:
        return asyncio.run(create_postgres_checkpointer())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(create_postgres_checkpointer())
        finally:
            loop.close()
    except Exception:
        logger.warning("Unable to create the default Postgres checkpointer.", exc_info=True)
        return None
