"""Durable Postgres-backed checkpoint support for the LangGraph foundation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings

def _normalize_postgres_url(conn_string: str) -> str:
    normalized = conn_string.strip()
    if normalized.startswith("postgresql+asyncpg://"):
        return normalized.replace("postgresql+asyncpg://", "postgresql://", 1)
    if normalized.startswith("postgresql+psycopg://"):
        return normalized.replace("postgresql+psycopg://", "postgresql://", 1)
    return normalized


@asynccontextmanager
async def open_postgres_checkpointer(
    conn_string: str | None = None,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open and initialize the durable PostgreSQL checkpointer for an app lifespan."""
    url = _normalize_postgres_url(conn_string or get_settings().database_url)
    if not url.startswith("postgresql://"):
        raise RuntimeError("LangGraph checkpointing requires a PostgreSQL DATABASE_URL.")

    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
        yield saver
