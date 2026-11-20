from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_organization, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.engine.evaluator import compliance_engine
from app.engine.multimodal.service import (
    MultimodalAnalysisResult,
    MultimodalProcessingStatus,
    multimodal_service,
)
from app.engine.multimodal.temp_manager import managed_temp_file
from app.engine.multimodal.validator import (
    MediaType,
    MimeType,
    UploadValidationError,
    validate_file_content,
)
from app.models.compliance import ComplianceReport
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.review import AuditEntry
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.common import SubmissionStatus, TargetChannel
from app.schemas.submissions import (
    SubmissionCreate,
    SubmissionResponse,
)

logger = logging.getLogger("brandshield.api.submissions")

router = APIRouter()


@router.post(
    "",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Content Submission",
    description="Saves a content draft or submits it for compliance inspection.",
)
async def create_submission(
    payload: SubmissionCreate,
    submit_for_inspection: bool = Query(
        False,
        description="Whether to immediately transition status from draft to submitted for compliance analysis",
    ),
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> ContentSubmission:
    submission_id = uuid.uuid4()
    initial_status = (
        SubmissionStatus.SUBMITTED.value
        if submit_for_inspection
        else SubmissionStatus.DRAFT.value
    )

    submission = ContentSubmission(
        id=submission_id,
        organization_id=org.id,
        author_id=current_user.id,
        title=payload.title,
        content=payload.content,
        target_channel=payload.target_channel.value,
        target_audience=payload.target_audience,
        status=initial_status,
        version=1,
        latest_review_id=None,
        metadata_payload=payload.metadata,
        media_type=getattr(payload, "media_type", "text") or "text",
        file_hash_sha256=getattr(payload, "file_hash_sha256", None),
        mime_type=getattr(payload, "mime_type", None),
        file_size_bytes=getattr(payload, "file_size_bytes", None),
        multimodal_metadata=getattr(payload, "multimodal_metadata", {}) or {},
    )
    session.add(submission)
    await session.flush()

    # Record Audit Entry with verified authenticated user identity
    audit = AuditEntry(
        id=uuid.uuid4(),
        organization_id=org.id,
        submission_id=submission.id,
        previous_status=SubmissionStatus.DRAFT.value,
        new_status=initial_status,
        action_type="submit_content" if submit_for_inspection else "create_draft",
        actor_id=str(current_user.id),
        actor_type="human",
        actor_name=current_user.full_name,
        notes="Submitted content for compliance evaluation" if submit_for_inspection else "Saved draft",
        details={
            "channel": payload.target_channel.value,
            "author_email": current_user.email,
        },
    )
    session.add(audit)
    await session.flush()

    submission.author = current_user
    return submission


@router.post(
    "/upload",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Content Submission via Multipart Media Upload",
    description=(
        "Uploads a media asset (image, audio, video, document) with optional accompanying text, "
        "validates format and size ceilings, executes multimodal extraction, and creates a submission. "
        "Optionally triggers immediate automated compliance inspection."
    ),
)
async def upload_submission(
    title: str = Form(..., description="Descriptive title for this content draft"),
    content: Optional[str] = Form(None, description="Accompanying copy, caption, or post text"),
    media_type: str = Form("text", description="Selected media category: text, image, audio, video, document"),
    target_channel: str = Form(..., description="Destination channel (e.g. twitter_x, linkedin, email)"),
    target_audience: Optional[str] = Form(None, description="Intended audience segment"),
    submit_for_inspection: bool = Form(False, description="Whether to immediately run compliance analysis"),
    file: Optional[UploadFile] = File(None, description="Media asset file (max 10MB)"),
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> ContentSubmission:
    # 1. Clean and validate scalar form fields
    clean_title = (title or "").strip()
    if len(clean_title) < 2 or len(clean_title) > 250:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Submission title must be between 2 and 250 characters long.",
        )

    clean_channel = (target_channel or "").strip().lower()
    valid_channels = {c.value: c for c in TargetChannel}
    if clean_channel not in valid_channels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target_channel '{target_channel}'. Must be one of: {sorted(list(valid_channels.keys()))}.",
        )

    clean_media_type = (media_type or "text").strip().lower()
    valid_types = {"text", "image", "audio", "video", "document"}
    if clean_media_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported media_type '{media_type}'. Supported: {sorted(list(valid_types))}.",
        )

    clean_content = (content or "").strip()
    clean_audience = (target_audience or "").strip() if target_audience else None

    normalized_content: str = ""
    file_hash: Optional[str] = None
    detected_mime: Optional[str] = None
    file_size: Optional[int] = None
    multimodal_meta: Dict[str, Any] = {}

    # 2. Process based on presence of file
    has_file = file is not None and bool(file.filename)

    if not has_file:
        if clean_media_type != "text":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A media file must be uploaded when media_type is '{clean_media_type}'.",
            )
        if not clean_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content text is required when no media file is uploaded.",
            )
        normalized_content = clean_content

    else:
        assert file is not None
        if clean_media_type == "text":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Media type cannot be 'text' when a media file is uploaded. Choose image, audio, video, or document.",
            )

        clean_suffix = Path(file.filename or "").suffix.lower()
        suffix = clean_suffix if len(clean_suffix) <= 10 else ".tmp"

        async with managed_temp_file(suffix=suffix) as temp_path:
            # Stream chunks to temp scratch file, enforcing 10MB ceiling
            hasher = hashlib.sha256()
            total_bytes = 0

            with open(temp_path, "wb") as f:
                while chunk := await file.read(65536):
                    total_bytes += len(chunk)
                    if total_bytes > settings.MAX_UPLOAD_SIZE_BYTES:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=(
                                f"Uploaded file exceeds maximum limit of "
                                f"{settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB."
                            ),
                        )
                    hasher.update(chunk)
                    f.write(chunk)

            if total_bytes == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file is empty (0 bytes).",
                )

            file_hash = hasher.hexdigest()
            file_size = total_bytes

            # Validate binary format, magic bytes, dimensions/duration limits
            try:
                val_res = validate_file_content(temp_path, file.filename or "upload")
            except UploadValidationError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Upload validation failed: {e.message}",
                )

            # Match declared media_type against actual binary detected media_type
            if val_res.media_type.value != clean_media_type:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Mismatch between selected media_type '{clean_media_type}' and "
                        f"detected file format '{val_res.media_type.value}' ({val_res.mime_type.value})."
                    ),
                )

            detected_mime = val_res.mime_type.value

            # Fetch active tenant brand guidelines for extraction context
            gl_stmt = select(BrandGuideline).where(
                BrandGuideline.organization_id == org.id,
                BrandGuideline.is_active.is_(True),
            )
            active_guidelines = (await session.execute(gl_stmt)).scalars().all()
            serialized_guidelines = [
                {
                    "id": str(g.id),
                    "name": g.name,
                    "rule_type": g.rule_type,
                    "severity": g.severity,
                    "directive": g.directive,
                    "examples_approved": g.examples_approved or [],
                    "examples_prohibited": g.examples_prohibited or [],
                }
                for g in active_guidelines
            ]

            # Execute multimodal extraction & analysis
            analysis_res: MultimodalAnalysisResult = await multimodal_service.analyze_input(
                media_type=clean_media_type,
                content_text=clean_content or None,
                file_path=temp_path,
                mime_type=val_res.mime_type,
                guidelines=serialized_guidelines,
            )

            if analysis_res.status == MultimodalProcessingStatus.FAILED:
                reason = analysis_res.fallback_reason or "Document or media parsing failed."
                notes = analysis_res.uncertainty_notes or ""
                detail_msg = f"Upload validation failed: {reason}. {notes}".strip()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=detail_msg,
                )

            # Synthesize normalized content string for compliance & claim engines
            if analysis_res.extracted_text and analysis_res.extracted_text.strip():
                normalized_content = analysis_res.extracted_text.strip()
            elif clean_content:
                normalized_content = clean_content
            else:
                status_str = analysis_res.status.value
                normalized_content = (
                    f"[{val_res.media_type.value.capitalize()} asset: {file.filename} | "
                    f"SHA-256: {file_hash[:12]} | Size: {total_bytes} bytes | "
                    f"Analysis Status: {status_str}]"
                )

            multimodal_meta = {
                "original_filename": file.filename,
                "media_type": val_res.media_type.value,
                "mime_type": detected_mime,
                "file_size_bytes": file_size,
                "file_hash_sha256": file_hash,
                "dimensions": val_res.dimensions,
                "duration_seconds": val_res.duration_seconds,
                "page_count": val_res.page_count,
                "paragraph_count": val_res.paragraph_count,
                "processing_status": analysis_res.status.value,
                "analysis_engine": analysis_res.analysis_engine,
                "fallback_reason": analysis_res.fallback_reason,
                "uncertainty_notes": analysis_res.uncertainty_notes,
                "confidence_score": analysis_res.confidence_score,
                "visual_observations": [
                    {
                        "entity": vo.entity,
                        "label": vo.label,
                        "confidence": vo.confidence,
                        "box_2d": vo.box_2d,
                        "details": vo.details,
                    }
                    for vo in analysis_res.visual_observations
                ],
                "dialogue_segments": [
                    {
                        "speaker": ds.speaker,
                        "start_time_seconds": ds.start_time_seconds,
                        "end_time_seconds": ds.end_time_seconds,
                        "text": ds.text,
                        "confidence": ds.confidence,
                    }
                    for ds in analysis_res.dialogue_segments
                ],
                "evidence_references": analysis_res.evidence_references,
            }

    # 3. Create ContentSubmission record within atomic transaction
    submission_id = uuid.uuid4()
    initial_status = (
        SubmissionStatus.SUBMITTED.value
        if submit_for_inspection
        else SubmissionStatus.DRAFT.value
    )

    submission = ContentSubmission(
        id=submission_id,
        organization_id=org.id,
        author_id=current_user.id,
        title=clean_title,
        content=normalized_content,
        target_channel=clean_channel,
        target_audience=clean_audience,
        status=initial_status,
        version=1,
        latest_review_id=None,
        metadata_payload={},
        media_type=clean_media_type,
        file_hash_sha256=file_hash,
        mime_type=detected_mime,
        file_size_bytes=file_size,
        multimodal_metadata=multimodal_meta,
    )
    session.add(submission)
    await session.flush()

    # 4. Record immutable AuditEntry
    action_type = "submit_multimodal_content" if submit_for_inspection else "create_multimodal_draft"
    audit_notes = (
        f"Uploaded {clean_media_type} submission '{clean_title}' by {current_user.full_name} "
        + ("and submitted for compliance inspection" if submit_for_inspection else "saved as draft")
    )
    audit = AuditEntry(
        id=uuid.uuid4(),
        organization_id=org.id,
        submission_id=submission.id,
        previous_status=SubmissionStatus.DRAFT.value,
        new_status=initial_status,
        action_type=action_type,
        actor_id=str(current_user.id),
        actor_type="human",
        actor_name=current_user.full_name,
        notes=audit_notes,
        details={
            "channel": clean_channel,
            "author_email": current_user.email,
            "media_type": clean_media_type,
            "file_hash_sha256": file_hash,
            "file_size_bytes": file_size,
            "multimodal_status": multimodal_meta.get("processing_status"),
        },
    )
    session.add(audit)
    await session.flush()

    # 5. Optionally trigger immediate compliance inspection
    if submit_for_inspection:
        await compliance_engine.run_inspection(
            session=session,
            submission=submission,
            actor=current_user,
        )

    await session.flush()
    submission.author = current_user
    return submission


@router.get(
    "",
    response_model=List[SubmissionResponse],
    summary="Retrieve Content Submissions",
    description="Lists all submissions for the active organization with optional status filtering.",
)
async def list_submissions(
    status_filter: Optional[SubmissionStatus] = Query(None, alias="status", description="Filter by status"),
    include_archived: bool = Query(False, description="Whether to include archived submissions"),
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> List[ContentSubmission]:
    stmt = select(ContentSubmission).where(ContentSubmission.organization_id == org.id)

    if not include_archived:
        stmt = stmt.where(ContentSubmission.is_archived.is_(False))

    if status_filter is not None:
        stmt = stmt.where(ContentSubmission.status == status_filter.value)

    stmt = stmt.order_by(ContentSubmission.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/audit-trail",
    response_model=List[Dict[str, Any]],
    summary="Retrieve Organization Recent Audit Trail",
    description="Fetches recent immutable audit ledger records for the authenticated user's organization.",
)
async def get_organization_audit_trail(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    stmt = (
        select(AuditEntry)
        .where(AuditEntry.organization_id == org.id)
        .order_by(AuditEntry.timestamp.desc())
        .limit(limit)
    )
    entries = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": str(entry.id),
            "organization_id": str(entry.organization_id),
            "organization_name": org.name,
            "submission_id": str(entry.submission_id),
            "previous_status": entry.previous_status,
            "new_status": entry.new_status,
            "action_type": entry.action_type,
            "actor_id": entry.actor_id,
            "actor_type": entry.actor_type,
            "actor_name": entry.actor_name,
            "notes": entry.notes,
            "details": entry.details,
            "timestamp": entry.timestamp.isoformat(),
        }
        for entry in entries
    ]


@router.get(
    "/{submission_id}",
    response_model=SubmissionResponse,
    summary="Retrieve Individual Submission",
    description="Fetches a discrete content submission by its unique identifier.",
)
async def get_submission(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> ContentSubmission:
    stmt = select(ContentSubmission).where(
        ContentSubmission.id == submission_id,
        ContentSubmission.organization_id == org.id,
    )
    result = await session.execute(stmt)
    submission = result.scalar_one_or_none()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content submission with id '{submission_id}' not found.",
        )
    return submission


@router.post(
    "/{submission_id}/submit",
    response_model=SubmissionResponse,
    summary="Submit Draft for Inspection",
    description="Transitions a draft or revision_requested submission to submitted for brand compliance inspection.",
)
async def submit_draft_for_inspection(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> ContentSubmission:
    stmt = select(ContentSubmission).where(
        ContentSubmission.id == submission_id,
        ContentSubmission.organization_id == org.id,
    )
    result = await session.execute(stmt)
    submission = result.scalar_one_or_none()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content submission with id '{submission_id}' not found.",
        )

    # Workflow validation: only draft or revision_requested can be submitted
    if submission.status not in {SubmissionStatus.DRAFT.value, SubmissionStatus.REVISION_REQUESTED.value}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot submit content with status '{submission.status}'. "
                "Submissions can only be submitted from 'draft' or 'revision_requested' status."
            ),
        )

    previous_status = submission.status
    submission.status = SubmissionStatus.SUBMITTED.value
    await session.flush()

    # Record Audit Entry with verified authenticated user identity
    audit = AuditEntry(
        id=uuid.uuid4(),
        organization_id=org.id,
        submission_id=submission.id,
        previous_status=previous_status,
        new_status=SubmissionStatus.SUBMITTED.value,
        action_type="submit_content",
        actor_id=str(current_user.id),
        actor_type="human",
        actor_name=current_user.full_name,
        notes=f"Submitted content for compliance evaluation by {current_user.full_name}",
        details={"submitted_by_email": current_user.email},
    )
    session.add(audit)
    await session.flush()

    return submission


@router.post(
    "/{submission_id}/analyze",
    response_model=SubmissionResponse,
    summary="Trigger Compliance Analysis",
    description="Runs the automated brand compliance inspection engine on the submission, updating status to violations_found or passed_checks.",
)
async def analyze_submission(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> ContentSubmission:
    stmt = select(ContentSubmission).where(
        ContentSubmission.id == submission_id,
        ContentSubmission.organization_id == org.id,
    )
    result = await session.execute(stmt)
    submission = result.scalar_one_or_none()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content submission with id '{submission_id}' not found.",
        )

    unacceptable_statuses = {
        SubmissionStatus.APPROVED.value,
        SubmissionStatus.REJECTED.value,
    }
    if submission.status in unacceptable_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot trigger analysis for submission in '{submission.status}' status. "
                "Human review decision has already been finalized."
            ),
        )

    from app.engine.evaluator import compliance_engine

    await compliance_engine.run_inspection(
        session=session,
        submission=submission,
        actor=current_user,
    )
    return submission


@router.post(
    "/{submission_id}/advance-to-review",
    response_model=SubmissionResponse,
    summary="Advance Analyzed Submission to Human Review",
    description="Transitions a submission that has completed analysis (violations_found, passed_checks, or analyzing) to under_human_review.",
)
async def advance_to_human_review(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> ContentSubmission:
    stmt = select(ContentSubmission).where(
        ContentSubmission.id == submission_id,
        ContentSubmission.organization_id == org.id,
    )
    result = await session.execute(stmt)
    submission = result.scalar_one_or_none()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content submission with id '{submission_id}' not found.",
        )

    allowed_precedents = {
        SubmissionStatus.VIOLATIONS_FOUND.value,
        SubmissionStatus.PASSED_CHECKS.value,
        SubmissionStatus.ANALYZING.value,
    }
    if submission.status not in allowed_precedents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot advance to human review: Current status is '{submission.status}'. "
                "Submissions must complete compliance analysis (status 'violations_found' or 'passed_checks') "
                "before entering 'under_human_review'. Direct transition from 'draft' or 'submitted' is strictly forbidden."
            ),
        )

    previous_status = submission.status
    submission.status = SubmissionStatus.UNDER_HUMAN_REVIEW.value
    await session.flush()

    audit = AuditEntry(
        id=uuid.uuid4(),
        organization_id=org.id,
        submission_id=submission.id,
        previous_status=previous_status,
        new_status=SubmissionStatus.UNDER_HUMAN_REVIEW.value,
        action_type="advance_to_review",
        actor_id=str(current_user.id),
        actor_type="human",
        actor_name=current_user.full_name,
        notes=f"Analysis completed; routed to human review queue by {current_user.full_name}",
        details={"routed_by_email": current_user.email},
    )
    session.add(audit)
    await session.flush()

    return submission


@router.get(
    "/{submission_id}/status",
    summary="Retrieve Submission Status",
    description="Returns lightweight workflow status and version for polling and status checks.",
)
async def get_submission_status(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    stmt = select(ContentSubmission).where(
        ContentSubmission.id == submission_id,
        ContentSubmission.organization_id == org.id,
    )
    result = await session.execute(stmt)
    submission = result.scalar_one_or_none()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content submission with id '{submission_id}' not found.",
        )

    return {
        "id": str(submission.id),
        "status": submission.status,
        "version": submission.version,
        "latest_review_id": str(submission.latest_review_id) if submission.latest_review_id else None,
        "updated_at": submission.updated_at.isoformat(),
    }


@router.get(
    "/{submission_id}/audit-trail",
    response_model=List[Dict[str, Any]],
    summary="Retrieve Submission Audit Trail",
    description="Fetches the complete immutable audit ledger history for a submission, strictly scoped to the tenant organization.",
)
async def get_submission_audit_trail(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    # Verify submission belongs to tenant organization
    sub_stmt = select(ContentSubmission).where(
        ContentSubmission.id == submission_id,
        ContentSubmission.organization_id == org.id,
    )
    submission = (await session.execute(sub_stmt)).scalar_one_or_none()
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content submission with id '{submission_id}' not found.",
        )

    stmt = (
        select(AuditEntry)
        .where(
            AuditEntry.submission_id == submission_id,
            AuditEntry.organization_id == org.id,
        )
        .order_by(AuditEntry.timestamp.asc())
    )
    entries = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": str(entry.id),
            "organization_id": str(entry.organization_id),
            "submission_id": str(entry.submission_id),
            "previous_status": entry.previous_status,
            "new_status": entry.new_status,
            "action_type": entry.action_type,
            "actor_id": entry.actor_id,
            "actor_type": entry.actor_type,
            "actor_name": entry.actor_name,
            "notes": entry.notes,
            "details": entry.details,
            "timestamp": entry.timestamp.isoformat(),
        }
        for entry in entries
    ]


@router.post(
    "/{submission_id}/archive",
    response_model=SubmissionResponse,
    summary="Safely Archive Content Submission",
    description="Archives a submission without destroying its revision, report, or audit ledger history.",
)
async def archive_submission(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> ContentSubmission:
    # 1. Fetch submission strictly scoped to tenant organization
    stmt = select(ContentSubmission).where(
        ContentSubmission.id == submission_id,
        ContentSubmission.organization_id == org.id,
    )
    result = await session.execute(stmt)
    submission = result.scalar_one_or_none()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content submission with id '{submission_id}' not found.",
        )

    # 2. Authorization check: ADMIN or original author
    is_admin = current_user.role == "ADMIN"
    is_author = submission.author_id == current_user.id
    if not (is_admin or is_author):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Only organization administrators or the original author can archive this submission.",
        )

    if submission.is_archived:
        return submission

    now = datetime.now(timezone.utc)
    submission.is_archived = True
    submission.archived_at = now
    await session.flush()

    # 3. Record immutable AuditEntry recording the authenticated user
    audit = AuditEntry(
        id=uuid.uuid4(),
        organization_id=org.id,
        submission_id=submission.id,
        previous_status=submission.status,
        new_status=submission.status,
        action_type="archive_submission",
        actor_id=str(current_user.id),
        actor_type="human",
        actor_name=current_user.full_name,
        notes=f"Submission archived by {current_user.full_name} ({current_user.role})",
        details={
            "archived_by_id": str(current_user.id),
            "archived_by_email": current_user.email,
            "archived_by_role": current_user.role,
            "submission_title": submission.title,
            "submission_version": submission.version,
        },
    )
    session.add(audit)
    await session.commit()
    await session.refresh(submission)

    return submission

