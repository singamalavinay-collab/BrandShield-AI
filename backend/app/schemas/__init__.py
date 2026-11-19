"""Central Pydantic v2 schemas package for BrandShield AI."""

from app.schemas.auth import (
    InitialProvisionRequest,
    LoginRequest,
    Token,
    UserAuthResponse,
    UserRole,
)
from app.schemas.candidate_guidelines import (
    CandidateExtractionStatus,
    CandidateGuidelineAuditEntryResponse,
    CandidateGuidelineBase,
    CandidateGuidelineCreate,
    CandidateGuidelineResponse,
    CandidateGuidelineReviewAction,
    CandidateReviewStatus,
)
from app.schemas.common import (
    ReviewAction,
    RuleType,
    SeverityLevel,
    SubmissionStatus,
    TargetChannel,
)
from app.schemas.guidelines import (
    GuidelineCreate,
    GuidelineResponse,
    GuidelineUpdate,
)
from app.schemas.health import HealthResponse
from app.schemas.invitations import (
    InvitationAcceptRequest,
    InvitationCreate,
    InvitationResponse,
    InvitationValidationResponse,
)
from app.schemas.reviews import (
    AuditEntry,
    ReviewDecision,
    ReviewDecisionCreate,
)
from app.schemas.submissions import (
    SubmissionCreate,
    SubmissionResponse,
)
from app.schemas.violations import (
    ComplianceReport,
    CorrectionSuggestion,
    EvidenceCitation,
    ViolationDetail,
)

__all__ = [
    # Enums
    "RuleType",
    "SeverityLevel",
    "SubmissionStatus",
    "ReviewAction",
    "TargetChannel",
    # Auth & Identity
    "UserRole",
    "LoginRequest",
    "UserAuthResponse",
    "Token",
    "InitialProvisionRequest",
    # Health
    "HealthResponse",
    # Brand Guidelines
    "GuidelineCreate",
    "GuidelineUpdate",
    "GuidelineResponse",
    # Candidate Guidelines (Phase 0C)
    "CandidateReviewStatus",
    "CandidateExtractionStatus",
    "CandidateGuidelineBase",
    "CandidateGuidelineCreate",
    "CandidateGuidelineReviewAction",
    "CandidateGuidelineResponse",
    "CandidateGuidelineAuditEntryResponse",
    # Submissions
    "SubmissionCreate",
    "SubmissionResponse",
    # Team Invitations
    "InvitationCreate",
    "InvitationResponse",
    "InvitationValidationResponse",
    "InvitationAcceptRequest",
    # Violations & Evidence
    "EvidenceCitation",
    "CorrectionSuggestion",
    "ViolationDetail",
    "ComplianceReport",
    # Human Review & Audit
    "ReviewDecision",
    "ReviewDecisionCreate",
    "AuditEntry",
]
