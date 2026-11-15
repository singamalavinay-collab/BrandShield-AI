from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import bcrypt
import jwt
from pydantic import BaseModel, Field

from app.core.config import settings


class TokenPayload(BaseModel):
    """Decoded JWT payload structure."""

    sub: str = Field(description="User UUID subject identifier")
    org_id: str = Field(description="Tenant Organization UUID")
    role: str = Field(description="User role (ADMIN | REVIEWER | CREATOR | AUDITOR)")
    email: str = Field(description="User email address")
    name: str = Field(description="User full display name")
    exp: int = Field(description="Expiration timestamp (epoch seconds)")
    iat: int = Field(description="Issued at timestamp (epoch seconds)")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Securely verify a plaintext password against a bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Generate a secure salted bcrypt hash from a plaintext password."""
    if not password:
        raise ValueError("Password cannot be empty.")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(
    subject: str,
    org_id: str,
    role: str,
    email: str,
    full_name: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Encode a cryptographically signed JWT access token."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "org_id": str(org_id),
        "role": str(role),
        "email": str(email),
        "name": str(full_name),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token signature and claims."""
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub", "org_id", "role"]},
    )
