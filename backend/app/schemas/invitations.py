from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class InvitationCreate(BaseModel):
    """Payload to create an organization-scoped team member invitation."""

    email: EmailStr = Field(
        ...,
        description="Recipient email address for the invitation",
    )
    role: Literal["CREATOR", "REVIEWER"] = Field(
        ...,
        description="Role assigned to invited user. Strictly restricted to CREATOR or REVIEWER.",
    )

    model_config = ConfigDict(extra="forbid")


class InvitationResponse(BaseModel):
    """Metadata response for a team member invitation."""

    id: UUID
    organization_id: UUID
    email: str
    role: str
    status: str
    inviter_id: UUID
    inviter_name: Optional[str] = None
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    created_at: datetime
    invitation_token: Optional[str] = None
    invitation_link: Optional[str] = None
    email_delivery_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class InvitationValidationResponse(BaseModel):
    """Public validation response for invitation acceptance workflow."""

    valid: bool
    email: str
    role: str
    organization_id: UUID
    organization_name: str
    organization_slug: str
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InvitationAcceptRequest(BaseModel):
    """Payload to accept an invitation and complete team member onboarding."""

    token: str = Field(
        ...,
        min_length=16,
        max_length=128,
        description="Secure single-use invitation token",
    )
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Full name of the user joining the organization",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password for the user account (minimum 8 characters)",
    )

    model_config = ConfigDict(extra="forbid")


class OrganizationMemberResponse(BaseModel):
    """Metadata response for an active registered organization member."""

    id: UUID
    organization_id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    is_owner: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

