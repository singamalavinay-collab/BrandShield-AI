from datetime import datetime
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Structured response schema for service health status."""

    status: str = Field(default="healthy", description="Current service health status")
    app_name: str = Field(description="Name of the application")
    version: str = Field(description="Current application version")
    environment: str = Field(description="Runtime environment (e.g. development, production)")
    timestamp: datetime = Field(description="UTC timestamp of the health check inspection")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "app_name": "BrandShield AI Backend",
                "version": "0.1.0",
                "environment": "development",
                "timestamp": "2026-11-13T15:30:00Z",
            }
        }
    }
