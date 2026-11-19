from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from typing_extensions import Self

from app.schemas.common import SubmissionStatus, TargetChannel
from app.schemas.violations import ComplianceReport


class SubmissionBase(BaseModel):
    """Core attributes for a content draft submission."""

    title: str = Field(
        ...,
        min_length=2,
        max_length=250,
        description="Descriptive title or campaign label for this content draft",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=50000,
        description="Draft copy to be checked against brand guidelines",
    )
    target_channel: TargetChannel = Field(
        ...,
        description="Destination publishing channel (e.g. twitter_x, linkedin, email)",
    )
    target_audience: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Intended readership or audience segment",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata", "metadata_payload"),
        serialization_alias="metadata",
        description="Optional operational or campaign metadata",
    )
    media_type: str = Field(
        default="text",
        description="Media format category (e.g. text, image, document, audio, video)",
    )
    file_hash_sha256: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Cryptographic SHA-256 hash of the uploaded media file",
    )
    mime_type: Optional[str] = Field(
        default=None,
        max_length=100,
        description="MIME content type of the uploaded media asset",
    )
    file_size_bytes: Optional[int] = Field(
        default=None,
        ge=0,
        description="Byte size of the uploaded media asset",
    )
    multimodal_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Validated media dimensions, page counts, durations, or OCR markers",
    )

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_and_validate_text(cls, v: str) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Title and content cannot be empty or whitespace only.")
            return stripped
        return v


class SubmissionCreate(SubmissionBase):
    """Payload schema for submitting new draft content for verification."""

    author_id: Optional[str] = Field(
        default=None,
        description="Identifier of the author or creator submitting the draft",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Q4 Enterprise Product Launch Announcement",
                "content": "We are proud to introduce BrandShield AI — the fastest way to audit content.",
                "target_channel": "linkedin",
                "target_audience": "Enterprise Compliance & Brand Officers",
                "metadata": {"campaign": "Q4_Launch"},
                "author_id": "author_user_102",
            }
        }
    )


class SubmissionResponse(SubmissionBase):
    """Complete representation of a content submission record."""

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this submission",
    )
    status: SubmissionStatus = Field(
        default=SubmissionStatus.DRAFT,
        description="Current workflow status of the submission",
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Iteration version number of this draft",
    )
    author_id: Optional[str] = Field(
        default=None,
        description="Author or submitter identifier",
    )
    author_name: Optional[str] = Field(
        default=None,
        description="Human-readable display name of the submission author",
    )
    compliance_report: Optional[ComplianceReport] = Field(
        default=None,
        description="Latest automated compliance inspection report, if executed",
    )
    latest_review_id: Optional[UUID] = Field(
        default=None,
        description="UUID of the most recent human review decision, if reviewed",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when submission was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when submission was last modified",
    )
    is_archived: bool = Field(
        default=False,
        description="Whether this submission has been archived",
    )
    archived_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp when submission was archived",
    )

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def resolve_orm_metadata(cls, data: Any) -> Any:
        """Resolve SQLAlchemy model instances to dict, ensuring metadata_payload
        is extracted properly without colliding with SQLAlchemy's internal MetaData.
        """
        if hasattr(data, "metadata_payload"):
            author_obj = getattr(data, "author", None)
            author_name = getattr(author_obj, "full_name", None) if author_obj else None
            if not author_name and hasattr(data, "author_name"):
                author_name = getattr(data, "author_name")
            elif not author_name and isinstance(data, dict):
                author_name = data.get("author_name")

            return {
                "id": getattr(data, "id", None),
                "title": getattr(data, "title", None),
                "content": getattr(data, "content", None),
                "target_channel": getattr(data, "target_channel", None),
                "target_audience": getattr(data, "target_audience", None),
                "metadata": (
                    data.metadata_payload
                    if isinstance(getattr(data, "metadata_payload", None), dict)
                    else {}
                ),
                "status": getattr(data, "status", None),
                "version": getattr(data, "version", 1),
                "author_id": (
                    str(data.author_id) if getattr(data, "author_id", None) else None
                ),
                "author_name": author_name,
                "compliance_report": getattr(data, "compliance_report", None),
                "latest_review_id": getattr(data, "latest_review_id", None),
                "created_at": getattr(data, "created_at", None),
                "updated_at": getattr(data, "updated_at", None),
                "is_archived": getattr(data, "is_archived", False),
                "archived_at": getattr(data, "archived_at", None),
                "media_type": getattr(data, "media_type", "text") or "text",
                "file_hash_sha256": getattr(data, "file_hash_sha256", None),
                "mime_type": getattr(data, "mime_type", None),
                "file_size_bytes": getattr(data, "file_size_bytes", None),
                "multimodal_metadata": (
                    data.multimodal_metadata
                    if isinstance(getattr(data, "multimodal_metadata", None), dict)
                    else {}
                ),
            }
        return data

    @model_validator(mode="after")
    def validate_approval_invariant(self) -> Self:
        """Inviolable Architectural Invariant: Content cannot be in APPROVED status
        without an explicit human review reference (latest_review_id).
        """
        if self.status == SubmissionStatus.APPROVED and self.latest_review_id is None:
            raise ValueError(
                "Inviolable governance rule: Content cannot be set to APPROVED status "
                "without a corresponding human review record (latest_review_id)."
            )
        return self
