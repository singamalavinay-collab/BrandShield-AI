from fastapi import APIRouter

from app.api.v1 import (
    auth,
    guidelines,
    health,
    invitations,
    reports,
    reviews,
    submissions,
    system,
)

api_router = APIRouter()

# Authentication & Identity
api_router.include_router(auth.router, tags=["Authentication & Identity"])
api_router.include_router(
    invitations.router,
    prefix="/invitations",
    tags=["Team Invitations"],
)

# Health & Diagnostics
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(system.router, tags=["System Diagnostics"])

# Core Governance Modules
api_router.include_router(
    guidelines.router,
    prefix="/guidelines",
    tags=["Brand Guidelines"],
)
api_router.include_router(
    submissions.router,
    prefix="/submissions",
    tags=["Content Submissions"],
)
api_router.include_router(
    reports.router,
    tags=["Compliance Reports"],
)
api_router.include_router(
    reviews.router,
    tags=["Human Review & Governance"],
)
