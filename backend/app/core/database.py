import logging
from typing import Any, AsyncGenerator, Dict
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger("brandshield.database")


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


class ImmutableAuditError(Exception):
    """Raised when an attempt is made to mutate or delete an immutable audit entry."""

    pass


def get_engine_options(url: str) -> Dict[str, Any]:
    """Derive appropriate engine parameters based on database dialect."""
    opts: Dict[str, Any] = {
        "echo": settings.DEBUG,
    }
    # SQLite async testing requires distinct options from PostgreSQL
    if url.startswith("sqlite"):
        return opts

    # Production PostgreSQL pooling options
    opts.update(
        {
            "pool_size": settings.DATABASE_POOL_SIZE,
            "max_overflow": settings.DATABASE_MAX_OVERFLOW,
            "pool_pre_ping": settings.DATABASE_POOL_PRE_PING,
            "pool_recycle": settings.DATABASE_POOL_RECYCLE,
        }
    )
    return opts


# Asynchronous database engine
engine = create_async_engine(
    settings.DATABASE_URL,
    **get_engine_options(settings.DATABASE_URL),
)

# Async session factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency providing transactional database sessions."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def set_tenant_context(session: AsyncSession, organization_id: UUID) -> None:
    """Safely configure the tenant context for the active transaction.
    
    Sets the transaction-local variable 'app.current_org_id' in PostgreSQL.
    This enables Row-Level Security (RLS) policies to strictly isolate tenant data.
    If the session is running on SQLite (unit test suite), it safely skips the call.
    """
    bind = session.bind
    if bind and getattr(bind, "dialect", None) and bind.dialect.name == "postgresql":
        # Safe parameterized execution preventing SQL injection using transaction-local set_config
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(organization_id)},
        )
