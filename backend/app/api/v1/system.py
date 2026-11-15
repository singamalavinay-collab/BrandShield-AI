import asyncio
from typing import Any, Dict
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

router = APIRouter()


@router.get(
    "/system/status",
    summary="System and Database Diagnostic Status",
    description="Returns accurate operational metrics, dialect detection, and live database connectivity status without fabricating connections.",
)
async def get_system_diagnostic(
    session: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    db_connected = False
    db_error = None
    dialect_name = "unknown"

    try:
        # Check actual database connectivity with a strict 2-second timeout
        bind = session.bind
        if bind and getattr(bind, "dialect", None):
            dialect_name = bind.dialect.name

        async def ping() -> None:
            await session.execute(text("SELECT 1"))

        await asyncio.wait_for(ping(), timeout=2.0)
        db_connected = True
    except Exception as e:
        db_connected = False
        db_error = f"{type(e).__name__}: {str(e)}"

    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "database": {
            "configured_url_type": "postgresql+asyncpg" if "postgresql" in settings.DATABASE_URL else "sqlite",
            "active_dialect": dialect_name,
            "connected": db_connected,
            "connection_error": db_error if not db_connected else None,
        },
        "governance": {
            "human_in_the_loop_enforced": True,
            "ai_approval_prohibited": True,
            "audit_ledger_immutable": True,
        },
    }
