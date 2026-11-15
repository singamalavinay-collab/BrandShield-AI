from enum import Enum
from typing import Optional
import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRole(str, Enum):
    """Allowed user roles for role-based access control (RBAC)."""

    ADMIN = "ADMIN"
    REVIEWER = "REVIEWER"
    CREATOR = "CREATOR"
    AUDITOR = "AUDITOR"


class LoginRequest(BaseModel):
    """Credentials payload for human user authentication."""

    email: EmailStr = Field(description="User email address")
    password: str = Field(min_length=1, max_length=128, description="Plaintext password")


class UserAuthResponse(BaseModel):
    """Safe public representation of an authenticated user (passwords never exposed)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="User UUID identifier")
    organization_id: uuid.UUID = Field(description="Tenant Organization UUID")
    email: EmailStr = Field(description="User verified email address")
    full_name: str = Field(description="User full display name")
    role: UserRole = Field(description="Assigned RBAC role")
    is_active: bool = Field(description="Active account status")
    organization_name: Optional[str] = Field(default=None, description="Tenant organization display name")


class Token(BaseModel):
    """JWT Bearer access token response."""

    access_token: str = Field(description="Cryptographically signed JWT access token")
    token_type: str = Field(default="bearer", description="Token type header prefix")
    expires_in: int = Field(description="Lifespan of token in seconds")
    user: UserAuthResponse = Field(description="Authenticated user identity")


class InitialProvisionRequest(BaseModel):
    """Payload for provisioning initial administrative or reviewer user accounts."""

    email: EmailStr = Field(description="Initial user email")
    password: str = Field(min_length=8, max_length=128, description="Initial secure password")
    full_name: str = Field(min_length=2, max_length=150, description="Full name")
    role: UserRole = Field(default=UserRole.REVIEWER, description="Initial role")


class RegisterRequest(BaseModel):
    """Payload for self-service public user registration (strictly CREATOR role only)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(description="User work email address")
    password: str = Field(min_length=8, max_length=128, description="Secure password (minimum 8 characters)")
    full_name: str = Field(min_length=2, max_length=150, description="User full display name")


class OnboardRequest(BaseModel):
    """Payload for public self-service tenant onboarding (creates organization + initial ADMIN user)."""

    model_config = ConfigDict(extra="forbid")

    organization_name: str = Field(min_length=2, max_length=150, description="Organization / Brand Workspace Name")
    full_name: str = Field(min_length=2, max_length=150, description="Administrator full display name")
    email: EmailStr = Field(description="Administrator work email address")
    password: str = Field(min_length=8, max_length=128, description="Secure password (minimum 8 characters)")


