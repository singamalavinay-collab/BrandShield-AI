from datetime import datetime, timezone
from fastapi import APIRouter
from app.core.config import settings
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service Health Check",
    description="Returns the operational status, application version, environment, and current UTC timestamp.",
    tags=["Health"],
)
async def get_health() -> HealthResponse:
    """Return structured health status for monitoring and orchestration."""
    return HealthResponse(
        status="healthy",
        app_name=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
    )
