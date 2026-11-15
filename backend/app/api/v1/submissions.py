from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_organization, get_current_user
from app.core.database import get_db
from app.models.compliance import ComplianceReport
from app.models.organization import Organization
from app.models.review import AuditEntry
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.common import SubmissionStatus
from app.schemas.submissions import (
    SubmissionCreate,
    SubmissionResponse,
)

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

