from datetime import datetime, timezone
from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_organization, get_current_reviewer
from app.core.database import get_db
from app.models.compliance import ComplianceReport
from app.models.organization import Organization
from app.models.review import AuditEntry, ReviewDecision
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.common import ReviewAction, SubmissionStatus
from app.schemas.reviews import ReviewDecisionCreate
from app.schemas.submissions import SubmissionResponse

router = APIRouter()


@router.get(
    "/reviews/pending",
    response_model=List[SubmissionResponse],
    summary="Retrieve Submissions Awaiting Human Review",
    description="Lists all submissions currently in under_human_review status awaiting authorized human sign-off.",
)
async def list_pending_reviews(
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> List[ContentSubmission]:
    stmt = (
        select(ContentSubmission)
        .where(
            ContentSubmission.organization_id == org.id,
            ContentSubmission.status == SubmissionStatus.UNDER_HUMAN_REVIEW.value,
        )
        .order_by(ContentSubmission.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/submissions/{submission_id}/review",
    summary="Record Human Review Decision",
    description=(
        "Records an authoritative human governance decision for a content submission. "
        "Enforces server-verified human reviewer identity, mandatory feedback rules, "
        "unresolved violation checks, and immutable audit ledger generation."
    ),
)
async def record_human_review(
    submission_id: uuid.UUID,
    payload: ReviewDecisionCreate,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_reviewer: User = Depends(get_current_reviewer),
) -> Dict[str, Any]:
    # 1. Fetch submission within active tenant organization
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

    # Enforce workflow state machine: review can only be conducted on under_human_review submissions
    if submission.status != SubmissionStatus.UNDER_HUMAN_REVIEW.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot record review: Submission is currently in '{submission.status}' status. "
                "Submissions must complete automated analysis and enter 'under_human_review' status "
                "before human governance decisions can be recorded."
            ),
        )

    # Enforce rule: Cannot Approve As-Is if unresolved mandatory violations exist without override
    if payload.action == ReviewAction.APPROVE:
        rep_stmt = (
            select(ComplianceReport)
            .where(ComplianceReport.submission_id == submission.id)
            .order_by(ComplianceReport.analyzed_at.desc())
            .limit(1)
        )
        rep_res = await session.execute(rep_stmt)
        latest_report = rep_res.scalar_one_or_none()

        if latest_report and latest_report.total_violations > 0:
            if not payload.override_reason or not payload.override_reason.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot approve content as-is: Active unresolved rule violations exist "
                        f"({latest_report.total_violations} violations flagged). "
                        "Reviewer must resolve violations using 'edit_and_approve', request revisions, "
                        "or supply an explicit, authorized 'override_reason'."
                    ),
                )

    previous_status = submission.status

    # 2. Persist the formal ReviewDecision record
    review_id = uuid.uuid4()
    decision_feedback = payload.feedback
    if payload.override_reason:
        override_note = f"[Approved via Authorized Exception: {payload.override_reason.strip()}]"
        decision_feedback = f"{override_note} {decision_feedback}" if decision_feedback else override_note

    decision = ReviewDecision(
        id=review_id,
        submission_id=submission.id,
        submission_version=submission.version,
        reviewer_id=current_reviewer.id,
        action=payload.action.value,
        feedback=decision_feedback,
        edited_content=payload.edited_content,
        decided_at=datetime.now(timezone.utc),
    )
    session.add(decision)
    await session.flush()

    # 3. Apply state transition based on the human action
    if payload.action in {ReviewAction.APPROVE, ReviewAction.EDIT_AND_APPROVE}:
        submission.status = SubmissionStatus.APPROVED.value
        submission.latest_review_id = decision.id
        if payload.action == ReviewAction.EDIT_AND_APPROVE and payload.edited_content:
            submission.content = payload.edited_content
            submission.version += 1

    elif payload.action == ReviewAction.REJECT:
        submission.status = SubmissionStatus.REJECTED.value
        submission.latest_review_id = decision.id

    elif payload.action == ReviewAction.REQUEST_REVISION:
        submission.status = SubmissionStatus.REVISION_REQUESTED.value
        submission.latest_review_id = decision.id

    await session.flush()

    # 4. Create immutable AuditEntry
    # Invariant: chk_audit_human_approval_only strictly enforced
    audit_id = uuid.uuid4()
    audit = AuditEntry(
        id=audit_id,
        organization_id=org.id,
        submission_id=submission.id,
        previous_status=previous_status,
        new_status=submission.status,
        action_type=f"human_review_{payload.action.value}",
        actor_id=str(current_reviewer.id),
        actor_type="human",
        actor_name=current_reviewer.full_name,
        notes=decision_feedback or f"Human decision: {payload.action.value}",
        details={
            "action": payload.action.value,
            "review_id": str(decision.id),
            "reviewer_email": current_reviewer.email,
            "submission_version": submission.version,
            "override_reason": payload.override_reason,
        },
    )
    session.add(audit)
    await session.flush()

    return {
        "success": True,
        "message": f"Review action '{payload.action.value}' successfully authorized and committed.",
        "decision": {
            "id": str(decision.id),
            "submission_id": str(submission.id),
            "submission_version": submission.version,
            "action": decision.action,
            "reviewer_id": str(current_reviewer.id),
            "reviewer_name": current_reviewer.full_name,
            "feedback": decision.feedback,
            "decided_at": decision.decided_at.isoformat(),
        },
        "submission": {
            "id": str(submission.id),
            "status": submission.status,
            "version": submission.version,
            "content": submission.content,
            "latest_review_id": str(submission.latest_review_id),
        },
        "audit_entry_id": str(audit.id),
    }
