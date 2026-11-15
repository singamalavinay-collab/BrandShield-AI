from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from app.schemas.common import ReviewAction, SubmissionStatus


class ReviewDecisionCreate(BaseModel):
    """Payload schema submitted by an authenticated human reviewer to record a decision.

    Security Rule:
    Reviewer identity and actor_type are NEVER accepted from client input.
    They are established exclusively by verified server-side authentication.
    """

    action: ReviewAction = Field(
        ...,
        description="Explicit human review decision (approve, reject, request_revision, edit_and_approve)",
    )
    feedback: Optional[str] = Field(
        default=None,
        description="Mandatory feedback when rejecting or requesting revisions",
    )
    edited_content: Optional[str] = Field(
        default=None,
        description="Human-authored replacement copy when choosing edit_and_approve",
    )
    override_reason: Optional[str] = Field(
        default=None,
        description="Formal justification required if approving as-is when unresolved rule violations exist",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "action": "edit_and_approve",
                "feedback": "Corrected brand name capitalization in accordance with guidelines.",
                "edited_content": "We are proud to introduce BrandShield AI — the fastest way to audit content.",
            }
        }
    )

    @model_validator(mode="after")
    def validate_action_requirements(self) -> Self:
        """Enforce strict payload consistency based on the selected action."""
        if self.action == ReviewAction.EDIT_AND_APPROVE:
            if not self.edited_content or not self.edited_content.strip():
                raise ValueError(
                    "edited_content must be provided and non-empty when action is 'edit_and_approve'."
                )
            self.edited_content = self.edited_content.strip()

        if self.action in {ReviewAction.REJECT, ReviewAction.REQUEST_REVISION}:
            if not self.feedback or not self.feedback.strip():
                raise ValueError(
                    f"feedback is mandatory when action is '{self.action.value}' to guide revision."
                )
            self.feedback = self.feedback.strip()

        return self


class ReviewDecision(BaseModel):
    """Formal human review decision for a content submission.
    
    Architectural Invariant:
    A human must always make the final approval decision. The system never
    auto-approves content.
    """

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this review record",
    )
    submission_id: UUID = Field(
        ...,
        description="UUID of the submission undergoing human review",
    )
    submission_version: int = Field(
        default=1,
        ge=1,
        description="Version of the submission being evaluated",
    )
    reviewer_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique identifier of the authorized human reviewer",
    )
    reviewer_name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Display name of the human reviewer",
    )
    action: ReviewAction = Field(
        ...,
        description="Explicit human review decision (approve, reject, request_revision, edit_and_approve)",
    )
    feedback: Optional[str] = Field(
        default=None,
        description="Mandatory feedback when rejecting or requesting revisions",
    )
    edited_content: Optional[str] = Field(
        default=None,
        description="Human-authored replacement copy when choosing edit_and_approve",
    )
    override_reason: Optional[str] = Field(
        default=None,
        description="Formal justification required if approving as-is when unresolved rule violations exist",
    )
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the human decision",
    )

    model_config = ConfigDict(from_attributes=True)

    @field_validator("reviewer_id", "reviewer_name", mode="before")
    @classmethod
    def validate_human_reviewer(cls, v: str) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Reviewer identity cannot be empty.")
            # Disallow automated bots or system impersonation
            disallowed_actors = {"system", "ai", "bot", "auto_approver", "agent", "automated"}
            if stripped.lower() in disallowed_actors:
                raise ValueError(
                    f"'{stripped}' is not an authorized human reviewer. "
                    "Final governance decisions require human authorization."
                )
            return stripped
        return v

    @model_validator(mode="after")
    def validate_action_requirements(self) -> Self:
        """Enforce strict payload consistency based on the selected action."""
        if self.action == ReviewAction.EDIT_AND_APPROVE:
            if not self.edited_content or not self.edited_content.strip():
                raise ValueError(
                    "edited_content must be provided and non-empty when action is 'edit_and_approve'."
                )
            self.edited_content = self.edited_content.strip()

        if self.action in {ReviewAction.REJECT, ReviewAction.REQUEST_REVISION}:
            if not self.feedback or not self.feedback.strip():
                raise ValueError(
                    f"feedback is mandatory when action is '{self.action.value}' to guide revision."
                )
            self.feedback = self.feedback.strip()

        return self


class AuditEntry(BaseModel):
    """Immutable record tracking state transitions and governance events."""

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this audit ledger event",
    )
    submission_id: UUID = Field(
        ...,
        description="UUID of the affected content submission",
    )
    previous_status: SubmissionStatus = Field(
        ...,
        description="Status prior to this transition",
    )
    new_status: SubmissionStatus = Field(
        ...,
        description="Status achieved after this transition",
    )
    action_type: str = Field(
        ...,
        min_length=1,
        description="Category of action executed (e.g. submit, check, human_review, edit)",
    )
    actor_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the entity performing the action",
    )
    actor_type: Literal["human", "system", "ai_agent"] = Field(
        ...,
        description="Classification of the actor triggering this transition",
    )
    actor_name: str = Field(
        ...,
        min_length=1,
        description="Display name or service label of the actor",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional explanatory notes or comments",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the event occurred",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured contextual metadata associated with the event",
    )

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def enforce_human_approval_invariant(self) -> Self:
        """Inviolable Architectural Invariant: Only human actors can transition
        a submission into the APPROVED state.
        """
        if self.new_status == SubmissionStatus.APPROVED and self.actor_type != "human":
            raise ValueError(
                f"Inviolable governance rule: Only human reviewers can approve content. "
                f"Actor of type '{self.actor_type}' is strictly forbidden from approving."
            )
        return self
