from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_organization, get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash
from app.models.invitation import TeamInvitation
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import Token, UserAuthResponse, UserRole
from app.schemas.invitations import (
    InvitationAcceptRequest,
    InvitationCreate,
    InvitationResponse,
    InvitationValidationResponse,
    OrganizationMemberResponse,
)

router = APIRouter()


def _hash_token(raw_token: str) -> str:
    """Computes SHA-256 digest of a raw invitation token for secure storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _normalize_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensures datetime is timezone-aware UTC for consistent SQLite and PostgreSQL comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.post(
    "",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Team Invitation",
    description="Invites a new team member with CREATOR or REVIEWER role into the administrator's organization.",
)
async def create_invitation(
    payload: InvitationCreate,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_admin: User = Depends(require_roles("ADMIN")),
) -> InvitationResponse:
    # 1. Invariant: Only CREATOR and REVIEWER roles allowed
    if payload.role not in {"CREATOR", "REVIEWER"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Privilege escalation prevented: Invitations can only be issued for CREATOR or REVIEWER roles.",
        )

    clean_email = payload.email.lower().strip()

    # 2. Check if user already exists
    user_stmt = select(User).where(User.email == clean_email)
    existing_user = (await session.execute(user_stmt)).scalar_one_or_none()
    if existing_user:
        if existing_user.organization_id == org.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A user with email '{clean_email}' is already a member of your organization.",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A user with email '{clean_email}' is already registered in the platform.",
            )

    now = datetime.now(timezone.utc)

    # 3. Check for existing pending invitation in this organization
    invite_stmt = select(TeamInvitation).where(
        TeamInvitation.organization_id == org.id,
        TeamInvitation.email == clean_email,
        TeamInvitation.status == "PENDING",
    )
    existing_invite = (await session.execute(invite_stmt)).scalar_one_or_none()
    if existing_invite:
        existing_expires = _normalize_utc(existing_invite.expires_at)
        if existing_expires and existing_expires > now:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"An active pending invitation for '{clean_email}' already exists in your organization. "
                    "Please revoke it first if you wish to re-invite."
                ),
            )
        else:
            existing_invite.status = "EXPIRED"
            await session.flush()

    # 4. Generate cryptographically secure token & SHA-256 hash
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = now + timedelta(days=7)

    invitation = TeamInvitation(
        id=uuid.uuid4(),
        organization_id=org.id,
        inviter_id=current_admin.id,
        email=clean_email,
        role=payload.role,
        token_hash=token_hash,
        status="PENDING",
        expires_at=expires_at,
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)

    # 5. Build response including the single-use token and clear delivery disclosure
    return InvitationResponse(
        id=invitation.id,
        organization_id=invitation.organization_id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        inviter_id=invitation.inviter_id,
        inviter_name=current_admin.full_name,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        created_at=invitation.created_at,
        invitation_token=raw_token,
        invitation_link=f"/invitations/accept?token={raw_token}",
        email_delivery_status="Email delivery infrastructure is not configured. Safe invitation link provided for development/admin sharing.",
    )


@router.get(
    "",
    response_model=List[InvitationResponse],
    summary="List Organization Invitations",
    description="Retrieves all invitations created for the administrator's organization.",
)
async def list_invitations(
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_admin: User = Depends(require_roles("ADMIN")),
) -> List[InvitationResponse]:
    stmt = (
        select(TeamInvitation)
        .where(TeamInvitation.organization_id == org.id)
        .order_by(TeamInvitation.created_at.desc())
    )
    invitations = list((await session.execute(stmt)).scalars().all())

    now = datetime.now(timezone.utc)
    updated = False
    for inv in invitations:
        inv_expires = _normalize_utc(inv.expires_at)
        if inv.status == "PENDING" and inv_expires and inv_expires < now:
            inv.status = "EXPIRED"
            updated = True

    if updated:
        await session.commit()

    return [
        InvitationResponse(
            id=inv.id,
            organization_id=inv.organization_id,
            email=inv.email,
            role=inv.role,
            status=inv.status,
            inviter_id=inv.inviter_id,
            inviter_name=inv.inviter.full_name if inv.inviter else None,
            expires_at=inv.expires_at,
            accepted_at=inv.accepted_at,
            created_at=inv.created_at,
            invitation_token=None,  # Token hash is never leaked
            invitation_link=None,
            email_delivery_status=None,
        )
        for inv in invitations
    ]


@router.get(
    "/members",
    response_model=List[OrganizationMemberResponse],
    summary="List Active Organization Members",
    description="Retrieves all active registered users belonging to the administrator's organization.",
)
async def list_organization_members(
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_admin: User = Depends(require_roles("ADMIN")),
) -> List[OrganizationMemberResponse]:
    stmt = (
        select(User)
        .where(
            User.organization_id == org.id,
            User.is_active == True,
        )
        .order_by(User.created_at.asc())
    )
    users = list((await session.execute(stmt)).scalars().all())

    return [
        OrganizationMemberResponse(
            id=user.id,
            organization_id=user.organization_id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            is_owner=(user.id == org.owner_id),
            created_at=user.created_at,
        )
        for user in users
    ]


@router.delete(
    "/{invitation_id}",
    response_model=InvitationResponse,
    summary="Revoke Team Invitation",
    description="Revokes an active invitation within the administrator's organization.",
)
@router.post(
    "/{invitation_id}/revoke",
    response_model=InvitationResponse,
    summary="Revoke Team Invitation (POST alias)",
    description="Revokes an active invitation within the administrator's organization.",
)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_admin: User = Depends(require_roles("ADMIN")),
) -> InvitationResponse:
    stmt = select(TeamInvitation).where(
        TeamInvitation.id == invitation_id,
        TeamInvitation.organization_id == org.id,
    )
    invitation = (await session.execute(stmt)).scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invitation with id '{invitation_id}' not found in your organization.",
        )

    if invitation.status == "ACCEPTED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot revoke an invitation that has already been accepted.",
        )

    invitation.status = "REVOKED"
    invitation.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(invitation)

    return InvitationResponse(
        id=invitation.id,
        organization_id=invitation.organization_id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        inviter_id=invitation.inviter_id,
        inviter_name=invitation.inviter.full_name if invitation.inviter else None,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        created_at=invitation.created_at,
        invitation_token=None,
        invitation_link=None,
        email_delivery_status=None,
    )


@router.get(
    "/validate",
    response_model=InvitationValidationResponse,
    summary="Validate Invitation Token",
    description="Public endpoint to inspect and validate an invitation token before accepting.",
)
async def validate_invitation(
    token: str = Query(..., description="Raw invitation token string"),
    session: AsyncSession = Depends(get_db),
) -> InvitationValidationResponse:
    token_hash = _hash_token(token.strip())

    stmt = select(TeamInvitation).where(TeamInvitation.token_hash == token_hash)
    invitation = (await session.execute(stmt)).scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation token is invalid or does not exist.",
        )

    now = datetime.now(timezone.utc)

    if invitation.status == "REVOKED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has been revoked by an organization administrator.",
        )
    if invitation.status == "ACCEPTED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has already been accepted.",
        )
    inv_expires = _normalize_utc(invitation.expires_at)
    if invitation.status == "EXPIRED" or (inv_expires and inv_expires <= now):
        if invitation.status != "EXPIRED":
            invitation.status = "EXPIRED"
            await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has expired. Please contact your organization administrator for a new invitation.",
        )

    return InvitationValidationResponse(
        valid=True,
        email=invitation.email,
        role=invitation.role,
        organization_id=invitation.organization_id,
        organization_name=invitation.organization.name,
        organization_slug=invitation.organization.slug,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/accept",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Accept Team Invitation",
    description="Public endpoint to accept an invitation, creating a user account in the invited organization with the assigned role.",
)
async def accept_invitation(
    payload: InvitationAcceptRequest,
    session: AsyncSession = Depends(get_db),
) -> Token:
    token_hash = _hash_token(payload.token.strip())
    now = datetime.now(timezone.utc)

    # 1. Atomic Check-and-Set State Transition within single transaction
    # Only one concurrent request can successfully update the PENDING row
    update_stmt = (
        update(TeamInvitation)
        .where(
            TeamInvitation.token_hash == token_hash,
            TeamInvitation.status == "PENDING",
            TeamInvitation.expires_at > now,
        )
        .values(
            status="ACCEPTED",
            accepted_at=now,
            updated_at=now,
        )
    )
    result = await session.execute(update_stmt)

    if result.rowcount == 0:
        # Atomic claim lost or token invalid/expired/revoked. Investigate state for exact error
        inv_stmt = select(TeamInvitation).where(TeamInvitation.token_hash == token_hash)
        inv = (await session.execute(inv_stmt)).scalar_one_or_none()

        if not inv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation token is invalid or does not exist.",
            )
        if inv.status == "ACCEPTED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This invitation has already been accepted.",
            )
        if inv.status == "REVOKED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This invitation has been revoked by an organization administrator.",
            )
        inv_expires = _normalize_utc(inv.expires_at)
        if inv.status == "EXPIRED" or (inv_expires and inv_expires <= now):
            if inv.status != "EXPIRED":
                inv.status = "EXPIRED"
                await session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This invitation has expired. Please contact your organization administrator for a new invitation.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation is no longer valid or has already been accepted.",
        )

    # Fetch updated invitation record within the SAME transaction
    inv_stmt = select(TeamInvitation).where(TeamInvitation.token_hash == token_hash)
    invitation = (await session.execute(inv_stmt)).scalar_one()

    # Invariant: Invitation cannot grant ADMIN
    if invitation.role not in {"CREATOR", "REVIEWER"}:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Privilege escalation prevented: Invitations cannot grant administrator access.",
        )

    # Verify email uniqueness
    user_stmt = select(User).where(User.email == invitation.email)
    existing_user = (await session.execute(user_stmt)).scalar_one_or_none()
    if existing_user:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email '{invitation.email}' already exists.",
        )

    # 2. In the SAME transaction, create new team member user entity
    hashed_password = get_password_hash(payload.password)
    user_id = uuid.uuid4()
    new_user = User(
        id=user_id,
        organization_id=invitation.organization_id,
        email=invitation.email,
        hashed_password=hashed_password,
        full_name=payload.full_name.strip(),
        role=invitation.role,
        is_active=True,
    )
    session.add(new_user)

    # 3. Single commit covering status update and user creation with rollback trap
    try:
        await session.commit()
        await session.refresh(new_user)
    except IntegrityError:
        # If user account creation fails (e.g. concurrent email collision), rollback invitation status change
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email '{invitation.email}' already exists.",
        )

    # Issue signed JWT for newly registered team member
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
            organization_name=invitation.organization.name if invitation.organization else None,
        ),
    )
