"""SQLAlchemy async database helpers."""

import asyncio
import sys
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for FastAPI dependencies with a loop-local engine."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
