import re
from datetime import timedelta
from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_organization, get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_db, set_tenant_context
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.user import User
from app.schemas.common import RuleType, SeverityLevel
from app.schemas.auth import (
    InitialProvisionRequest,
    LoginRequest,
    OnboardRequest,
    RegisterRequest,
    Token,
    UserAuthResponse,
    UserRole,
)

router = APIRouter()


@router.post(
    "/auth/login",
    response_model=Token,
    summary="Human User Authentication Login",
    description="Authenticates human credentials and issues a signed JWT access token. Password hashes are never returned.",
)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> Token:
    email_clean = payload.email.strip().lower()

    # Query user by normalized email
    stmt = select(User).where(func.lower(User.email) == email_clean)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    # Constant-time-like check preventing user enumeration
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated. Please contact your organization administrator.",
        )

    # Establish tenant RLS context
    await set_tenant_context(session, user.organization_id)

    # Generate cryptographically signed JWT
    access_token = create_access_token(
        subject=str(user.id),
        org_id=str(user.organization_id),
        role=user.role,
        email=user.email,
        full_name=user.full_name,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserAuthResponse(
            id=user.id,
            organization_id=user.organization_id,
            email=user.email,
            full_name=user.full_name,
            role=UserRole(user.role),
            is_active=user.is_active,
            organization_name=user.organization.name if user.organization else None,
        ),
    )


@router.post(
    "/auth/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Public Self-Service User Registration",
    description="Registers a new user with the CREATOR role. REVIEWER and ADMIN roles cannot be self-assigned.",
)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_db),
) -> Token:
    email_clean = payload.email.strip().lower()

    # Enforce email uniqueness across the system
    stmt = select(User).where(func.lower(User.email) == email_clean)
    res = await session.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An account with email '{email_clean}' already exists.",
        )

    # Ensure primary organization exists
    org_stmt = select(Organization).where(Organization.slug == "brandshield-primary")
    org_res = await session.execute(org_stmt)
    org = org_res.scalar_one_or_none()
    if not org:
        org_stmt_any = select(Organization).limit(1)
        org = (await session.execute(org_stmt_any)).scalar_one_or_none()
        if not org:
            org = Organization(
                id=uuid.uuid4(),
                name="BrandShield Primary Organization",
                slug="brandshield-primary",
                is_active=True,
            )
            session.add(org)
            await session.flush()

    # Public self-registration is strictly restricted to CREATOR role
    hashed_pw = get_password_hash(payload.password)
    new_user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=email_clean,
        hashed_password=hashed_pw,
        full_name=payload.full_name.strip(),
        role=UserRole.CREATOR.value,
        is_active=True,
    )
    session.add(new_user)
    try:
        await session.commit()
        await session.refresh(new_user)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{email_clean}' already exists.",
        )

    # Establish tenant RLS context and generate signed JWT
    await set_tenant_context(session, new_user.organization_id)
    access_token = create_access_token(
        subject=str(new_user.id),
        org_id=str(new_user.organization_id),
        role=new_user.role,
        email=new_user.email,
        full_name=new_user.full_name,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserAuthResponse(
            id=new_user.id,
            organization_id=new_user.organization_id,
            email=new_user.email,
            full_name=new_user.full_name,
            role=UserRole(new_user.role),
            is_active=new_user.is_active,
            organization_name=org.name,
        ),
    )


def generate_organization_slug(name: str) -> str:
    """Generate a clean URL-friendly slug from an organization name."""
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return clean[:60] if clean else "workspace"


@router.post(
    "/auth/onboard",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Self-Service Multi-Tenant Onboarding",
    description=(
        "Provisions a brand-new isolated organization workspace for a customer, registers the initial administrator, "
        "seeds starter brand guidelines, and returns an authenticated JWT access token."
    ),
)
async def onboard(
    payload: OnboardRequest,
    session: AsyncSession = Depends(get_db),
) -> Token:
    email_clean = payload.email.strip().lower()

    # 1. Enforce global email uniqueness
    stmt = select(User).where(func.lower(User.email) == email_clean)
    res = await session.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An account with email '{email_clean}' already exists.",
        )

    # 2. Generate unique organization slug
    base_slug = generate_organization_slug(payload.organization_name)
    slug = base_slug
    counter = 1
    while True:
        slug_stmt = select(Organization).where(Organization.slug == slug)
        slug_res = await session.execute(slug_stmt)
        if not slug_res.scalar_one_or_none():
            break
        counter += 1
        slug = f"{base_slug}-{counter}"

    # 3. Create isolated Organization
    org_id = uuid.uuid4()
    org = Organization(
        id=org_id,
        name=payload.organization_name.strip(),
        slug=slug,
        is_active=True,
    )
    session.add(org)
    await session.flush()

    # 4. Create initial administrator user for this new organization
    user_id = uuid.uuid4()
    hashed_pw = get_password_hash(payload.password)
    new_admin = User(
        id=user_id,
        organization_id=org.id,
        email=email_clean,
        hashed_password=hashed_pw,
        full_name=payload.full_name.strip(),
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    session.add(new_admin)
    await session.flush()

    # 5. Associate organization owner with initial administrator
    org.owner_id = new_admin.id

    # 6. Seed starter brand guidelines into the new organization (isolated tenant data)
    starter_guidelines = [
        BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=f"{org.name} Naming & Capitalization",
            rule_type=RuleType.TRADEMARK_USAGE.value,
            severity=SeverityLevel.CRITICAL.value,
            description=f"Enforces correct naming and capitalization for {org.name}.",
            directive=f"Always spell and capitalize the brand name strictly as '{org.name}'.",
            examples_approved=[f"{org.name} protects brand integrity."],
            examples_prohibited=[f"{org.name.lower()} is poorly written."],
            tags=["naming", "branding", "trademark"],
            is_active=True,
            created_by=new_admin.id,
        ),
        BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Prohibited Absolute Claims",
            rule_type=RuleType.PROHIBITED_CLAIMS.value,
            severity=SeverityLevel.HIGH.value,
            description="Prohibits unqualified guarantees of 100% compliance or absolute immunity.",
            directive="Never state that products provide 100% violation-free output or replace legal counsel.",
            examples_approved=["Substantially reduces brand guideline deviations by over 90%."],
            examples_prohibited=["Guarantees 100% brand safety everywhere."],
            tags=["legal", "claims", "compliance"],
            is_active=True,
            created_by=new_admin.id,
        ),
        BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Empowering & Professional Tone of Voice",
            rule_type=RuleType.TONE_OF_VOICE.value,
            severity=SeverityLevel.MEDIUM.value,
            description="Maintains an objective, confident, and professional tone.",
            directive="Maintain an objective, confident tone. Avoid hyperbolic jargon such as 'miracle' or 'revolutionary magic'.",
            examples_approved=[f"{org.name} provides rigorous brand management for modern teams."],
            examples_prohibited=["Our revolutionary miracle will blow your mind!"],
            tags=["tone", "voice", "messaging"],
            is_active=True,
            created_by=new_admin.id,
        ),
    ]
    session.add_all(starter_guidelines)
    try:
        await session.commit()
        await session.refresh(new_admin)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{email_clean}' or workspace slug '{slug}' already exists.",
        )

    # 7. Establish tenant context and generate cryptographically signed JWT
    await set_tenant_context(session, new_admin.organization_id)
    access_token = create_access_token(
        subject=str(new_admin.id),
        org_id=str(new_admin.organization_id),
        role=new_admin.role,
        email=new_admin.email,
        full_name=new_admin.full_name,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserAuthResponse(
            id=new_admin.id,
            organization_id=new_admin.organization_id,
            email=new_admin.email,
            full_name=new_admin.full_name,
            role=UserRole(new_admin.role),
            is_active=new_admin.is_active,
            organization_name=org.name,
        ),
    )


@router.get(
    "/auth/me",
    response_model=UserAuthResponse,
    summary="Current Authenticated User Profile",
    description="Returns the profile of the verified user without exposing credentials or password hashes.",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserAuthResponse:
    return UserAuthResponse(
        id=current_user.id,
        organization_id=current_user.organization_id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=UserRole(current_user.role),
        is_active=current_user.is_active,
        organization_name=current_user.organization.name if current_user.organization else None,
    )


@router.post(
    "/auth/logout",
    summary="Logout Current Session",
    description="Terminates the client session and instructs the client to discard the access token.",
)
async def logout(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return {
        "success": True,
        "message": f"Session for user '{current_user.email}' terminated successfully.",
    }


@router.post(
    "/auth/provision-initial-user",
    response_model=UserAuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision Initial Organization and Administrator",
    description=(
        "Securely bootstraps the initial organization and administrative user if and only if "
        "no users exist in the system. Once initialized, this endpoint is permanently disabled."
    ),
)
async def provision_initial_user(
    payload: InitialProvisionRequest,
    session: AsyncSession = Depends(get_db),
) -> UserAuthResponse:
    # Ensure no users already exist
    count_stmt = select(func.count(User.id))
    result = await session.execute(count_stmt)
    total_users = result.scalar_one()

    if total_users > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System is already provisioned. Subsequent users must be invited by an ADMIN.",
        )

    # Create primary tenant organization
    org = Organization(
        id=uuid.uuid4(),
        name="BrandShield Primary Organization",
        slug="brandshield-primary",
        is_active=True,
    )
    session.add(org)
    await session.flush()

    # Hash password securely
    hashed_pw = get_password_hash(payload.password)

    # Create initial administrative user
    user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=payload.email.strip().lower(),
        hashed_password=hashed_pw,
        full_name=payload.full_name.strip(),
        role=payload.role.value,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return UserAuthResponse(
        id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        full_name=user.full_name,
        role=UserRole(user.role),
        is_active=user.is_active,
    )


@router.post(
    "/auth/users",
    response_model=UserAuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create User in Tenant Organization (ADMIN only)",
    description="Allows an authenticated ADMIN to provision additional users within their tenant boundary.",
)
async def create_tenant_user(
    payload: InitialProvisionRequest,
    session: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_roles("ADMIN")),
    org: Organization = Depends(get_current_organization),
) -> UserAuthResponse:
    # Check if email is already taken
    email_clean = payload.email.strip().lower()
    existing_stmt = select(User).where(func.lower(User.email) == email_clean)
    existing_res = await session.execute(existing_stmt)
    if existing_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email '{payload.email}' already exists.",
        )

    hashed_pw = get_password_hash(payload.password)
    new_user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=email_clean,
        hashed_password=hashed_pw,
        full_name=payload.full_name.strip(),
        role=payload.role.value,
        is_active=True,
    )
    session.add(new_user)
    try:
        await session.commit()
        await session.refresh(new_user)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{email_clean}' already exists.",
        )

    return UserAuthResponse(
        id=new_user.id,
        organization_id=new_user.organization_id,
        email=new_user.email,
        full_name=new_user.full_name,
        role=UserRole(new_user.role),
        is_active=new_user.is_active,
    )
