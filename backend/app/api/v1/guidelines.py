from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_organization, require_roles
from app.core.database import get_db
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.user import User
from app.schemas.common import RuleType, SeverityLevel
from app.schemas.guidelines import (
    GuidelineCreate,
    GuidelineResponse,
    GuidelineUpdate,
)

router = APIRouter()


@router.post(
    "",
    response_model=GuidelineResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Brand Guideline",
    description="Registers a new verified brand guideline rule for the active organization.",
)
async def create_guideline(
    payload: GuidelineCreate,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_admin: User = Depends(require_roles("ADMIN")),
) -> BrandGuideline:
    guideline = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=payload.name,
        rule_type=payload.rule_type.value,
        severity=payload.severity.value,
        description=payload.description,
        directive=payload.directive,
        examples_approved=payload.examples_approved,
        examples_prohibited=payload.examples_prohibited,
        tags=payload.tags,
        is_active=payload.is_active,
    )
    session.add(guideline)
    await session.flush()
    return guideline


@router.get(
    "",
    response_model=List[GuidelineResponse],
    summary="Retrieve Brand Guidelines",
    description="Fetches brand guidelines for the active organization with optional active and category filtering.",
)
async def list_guidelines(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    rule_type: Optional[RuleType] = Query(None, description="Filter by rule type category"),
    severity: Optional[SeverityLevel] = Query(None, description="Filter by severity level"),
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> List[BrandGuideline]:
    stmt = select(BrandGuideline).where(BrandGuideline.organization_id == org.id)

    if is_active is not None:
        stmt = stmt.where(BrandGuideline.is_active == is_active)
    if rule_type is not None:
        stmt = stmt.where(BrandGuideline.rule_type == rule_type.value)
    if severity is not None:
        stmt = stmt.where(BrandGuideline.severity == severity.value)

    stmt = stmt.order_by(BrandGuideline.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{guideline_id}",
    response_model=GuidelineResponse,
    summary="Retrieve Individual Brand Guideline",
    description="Fetches a discrete brand guideline by its unique identifier.",
)
async def get_guideline(
    guideline_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> BrandGuideline:
    stmt = select(BrandGuideline).where(
        BrandGuideline.id == guideline_id,
        BrandGuideline.organization_id == org.id,
    )
    result = await session.execute(stmt)
    guideline = result.scalar_one_or_none()

    if not guideline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand guideline with id '{guideline_id}' not found in active organization.",
        )
    return guideline


@router.patch(
    "/{guideline_id}",
    response_model=GuidelineResponse,
    summary="Update a Brand Guideline",
    description="Partially updates an existing brand guideline.",
)
async def update_guideline(
    guideline_id: uuid.UUID,
    payload: GuidelineUpdate,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_admin: User = Depends(require_roles("ADMIN")),
) -> BrandGuideline:
    stmt = select(BrandGuideline).where(
        BrandGuideline.id == guideline_id,
        BrandGuideline.organization_id == org.id,
    )
    result = await session.execute(stmt)
    guideline = result.scalar_one_or_none()

    if not guideline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand guideline with id '{guideline_id}' not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            if field in {"rule_type", "severity"} and hasattr(value, "value"):
                setattr(guideline, field, value.value)
            else:
                setattr(guideline, field, value)

    await session.flush()
    return guideline


@router.patch(
    "/{guideline_id}/toggle-active",
    response_model=GuidelineResponse,
    summary="Toggle Brand Guideline Active Status",
    description="Inverts the active status of a brand guideline.",
)
async def toggle_guideline_active(
    guideline_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_admin: User = Depends(require_roles("ADMIN")),
) -> BrandGuideline:
    stmt = select(BrandGuideline).where(
        BrandGuideline.id == guideline_id,
        BrandGuideline.organization_id == org.id,
    )
    result = await session.execute(stmt)
    guideline = result.scalar_one_or_none()

    if not guideline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand guideline with id '{guideline_id}' not found.",
        )

    guideline.is_active = not guideline.is_active
    await session.flush()
    return guideline
