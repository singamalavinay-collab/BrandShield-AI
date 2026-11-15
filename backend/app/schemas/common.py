from enum import Enum


class RuleType(str, Enum):
    """Categories of brand governance rules."""

    TERMINOLOGY = "terminology"
    TONE_OF_VOICE = "tone_of_voice"
    MESSAGING_PILLAR = "messaging_pillar"
    FACTUAL_ACCURACY = "factual_accuracy"
    FORBIDDEN_CLAIM = "forbidden_claim"
    PROHIBITED_CLAIMS = "prohibited_claims"
    COMPETITOR_REFERENCE = "competitor_reference"
    REGULATORY_DISCLOSURE = "regulatory_disclosure"
    LEGAL_REGULATORY = "legal_regulatory"
    TRADEMARK_USAGE = "trademark_usage"
    FORMATTING = "formatting"


class SeverityLevel(str, Enum):
    """Severity ratings for rule violations."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SubmissionStatus(str, Enum):
    """Lifecycle states of a content submission."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    ANALYZING = "analyzing"
    VIOLATIONS_FOUND = "violations_found"
    PASSED_CHECKS = "passed_checks"
    UNDER_HUMAN_REVIEW = "under_human_review"
    REVISION_REQUESTED = "revision_requested"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewAction(str, Enum):
    """Explicit human-in-the-loop review actions."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_REVISION = "request_revision"
    EDIT_AND_APPROVE = "edit_and_approve"


class TargetChannel(str, Enum):
    """Publishing channels with distinct brand tone requirements."""

    TWITTER_X = "twitter_x"
    LINKEDIN = "linkedin"
    EMAIL = "email"
    EMAIL_NEWSLETTER = "email_newsletter"
    AD_COPY = "ad_copy"
    ADVERTISEMENT = "advertisement"
    BLOG_POST = "blog_post"
    PRESS_RELEASE = "press_release"
    OTHER = "other"
