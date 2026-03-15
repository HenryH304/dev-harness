"""SQLite database setup with SQLAlchemy async engine."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def get_engine(url: str = "sqlite+aiosqlite:///data/devharness.db") -> AsyncEngine:
    """Create and return an async SQLAlchemy engine."""
    return create_async_engine(url, echo=False)


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for database operations."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
