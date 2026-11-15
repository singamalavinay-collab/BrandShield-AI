from typing import Callable, Optional
import uuid

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_tenant_context
from app.core.security import decode_access_token
from app.models.organization import Organization
from app.models.user import User

# HTTP Bearer scheme for token extraction
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Resolve and verify the authenticated human user from the JWT Bearer token.
    
    Security Guarantees:
    1. Validates JWT signature, expiration, subject, and organization claims.
    2. Fetches active User from database to confirm account status.
    3. Prevents client-side identity spoofing (X-Reviewer-Email is never trusted).
    4. Automatically binds PostgreSQL transaction tenant context to the user's organization.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: Optional[str] = payload.get("sub")
    org_id_str: Optional[str] = payload.get("org_id")

    if not user_id_str or not org_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token claims: missing subject or organization identifier.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
        org_uuid = uuid.UUID(org_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token claims: invalid UUID format in token claims.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch user strictly scoped by user ID and organization ID
    stmt = (
        select(User)
        .where(
            User.id == user_uuid,
            User.organization_id == org_uuid,
        )
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account does not exist or has been removed.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated. Access denied.",
        )

    # Establish transaction-local tenant context in PostgreSQL
    await set_tenant_context(session, user.organization_id)

    return user


async def get_current_organization(
    current_user: User = Depends(get_current_user),
    x_org_id: Optional[str] = Header(None, alias="X-Organization-Id"),
) -> Organization:
    """Resolve the active tenant organization strictly bound to the authenticated user.
    
    Security Invariants:
    1. Client-supplied X-Organization-Id header CANNOT override the authenticated organization.
    2. Any attempted cross-tenant override attempt is explicitly rejected with 403 Forbidden.
    """
    if x_org_id:
        try:
            supplied_uuid = uuid.UUID(x_org_id.strip())
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid X-Organization-Id header: '{x_org_id}' is not a valid UUID.",
            )
        if supplied_uuid != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-tenant access forbidden. Client tenant identifier does not match authenticated organization context.",
            )

    return current_user.organization


def require_roles(*allowed_roles: str) -> Callable:
    """Factory creating an endpoint dependency that enforces role-based access control (RBAC)."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access denied: Action requires one of {allowed_roles}. "
                    f"Current user role '{current_user.role}' is not authorized."
                ),
            )
        return current_user

    return role_checker


async def get_current_reviewer(
    current_user: User = Depends(get_current_user),
) -> User:
    """Resolve the authenticated human reviewer for governance actions.
    
    Architectural Invariant:
    Only an authenticated, authorized human reviewer (ADMIN or REVIEWER) can make review decisions.
    CREATOR and AUDITOR roles are strictly forbidden from approving content.
    Automated bots, AI agents, and unverified actors are strictly forbidden.
    """
    if current_user.role not in {"ADMIN", "REVIEWER"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"User lacks required human governance permissions (ADMIN or REVIEWER role required). "
                f"Your role '{current_user.role}' is not authorized to approve, reject, or edit submissions."
            ),
        )

    return current_user
