"""Candidate Brand Guideline staging, tenant isolation, and Admin review service.

Architectural Invariants:
1. Newly extracted candidate rules are NEVER active by default (review_status = PENDING_APPROVAL).
2. Only authorized Admin users can approve or reject candidate rules.
3. Rejected candidates are never added to active brand_guidelines.
4. Tenant isolation is strictly enforced via organization_id on all operations.
5. Review decisions are recorded with reviewer identity, timestamps, and notes.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_guideline import CandidateGuideline
from app.models.candidate_guideline_audit import CandidateGuidelineAuditEntry
from app.models.guideline import BrandGuideline
from app.models.user import User
from app.schemas.candidate_guidelines import (
    CandidateGuidelineCreate,
    CandidateGuidelineReviewAction,
    CandidateReviewStatus,
)

logger = logging.getLogger("brandshield.services.candidate_guidelines")


class CandidateGuidelineGovernanceError(Exception):
    """Raised when candidate guideline governance rules or permissions are violated."""

    def __init__(self, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def stage_candidate_guideline(
    session: AsyncSession,
    organization_id: UUID,
    payload: CandidateGuidelineCreate,
) -> CandidateGuideline:
    """Stage an AI-extracted candidate guideline for administrative review.
    
    Guarantees:
    - Candidate is strictly created under the target tenant organization.
    - Status is unconditionally PENDING_APPROVAL.
    - No active brand_guidelines record is created.
    """
    candidate = CandidateGuideline(
        organization_id=organization_id,
        name=payload.name,
        rule_type=payload.rule_type.value if hasattr(payload.rule_type, "value") else str(payload.rule_type),
        severity=payload.severity.value if hasattr(payload.severity, "value") else str(payload.severity),
        description=payload.description,
        directive=payload.directive,
        examples_approved=list(payload.examples_approved),
        examples_prohibited=list(payload.examples_prohibited),
        tags=list(payload.tags),
        source_reference=payload.source_reference,
        source_metadata=dict(payload.source_metadata),
        source_submission_id=payload.source_submission_id,
        extraction_status="EXTRACTED",
        review_status=CandidateReviewStatus.PENDING_APPROVAL.value,
        reviewed_by=None,
        reviewed_at=None,
        review_notes=None,
        approved_guideline_id=None,
    )
    session.add(candidate)
    await session.flush()
    logger.info(
        "Staged candidate guideline %s ('%s') for organization %s",
        candidate.id,
        candidate.name,
        organization_id,
    )
    return candidate


async def list_candidate_guidelines(
    session: AsyncSession,
    organization_id: UUID,
    review_status: Optional[str] = None,
) -> List[CandidateGuideline]:
    """Retrieve candidate guidelines strictly isolated to the specified tenant organization."""
    query = (
        select(CandidateGuideline)
        .where(CandidateGuideline.organization_id == organization_id)
        .order_by(CandidateGuideline.created_at.desc())
    )
    if review_status:
        query = query.where(CandidateGuideline.review_status == review_status.upper())

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_candidate_guideline(
    session: AsyncSession,
    organization_id: UUID,
    candidate_id: UUID,
) -> Optional[CandidateGuideline]:
    """Retrieve a single candidate guideline verifying tenant boundary."""
    query = select(CandidateGuideline).where(
        CandidateGuideline.id == candidate_id,
        CandidateGuideline.organization_id == organization_id,
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def review_candidate_guideline(
    session: AsyncSession,
    organization_id: UUID,
    candidate_id: UUID,
    actor: User,
    review_payload: CandidateGuidelineReviewAction,
) -> Tuple[CandidateGuideline, Optional[BrandGuideline]]:
    """Execute Admin governance review (APPROVE or REJECT) on a staged candidate guideline.

    Invariants:
    1. Actor must be an authorized ADMIN of the tenant organization.
    2. Only PENDING_APPROVAL candidates can be reviewed.
    3. APPROVE creates an active BrandGuideline and links approved_guideline_id.
    4. REJECT updates review_status and notes without creating any BrandGuideline.
    """
    # 1. Authority Check: Admin role required
    if actor.role != "ADMIN":
        raise CandidateGuidelineGovernanceError(
            f"Governance permission denied: Only Admin users can approve or reject candidate guidelines. "
            f"Current user role '{actor.role}' is unauthorized.",
            status_code=403,
        )

    # 2. Tenant Boundary Check
    if actor.organization_id != organization_id:
        raise CandidateGuidelineGovernanceError(
            "Tenant boundary violation: Reviewer organization does not match candidate organization.",
            status_code=403,
        )

    # 3. Retrieve Candidate with exclusive row lock against concurrent review races
    query = (
        select(CandidateGuideline)
        .where(
            CandidateGuideline.id == candidate_id,
            CandidateGuideline.organization_id == organization_id,
        )
        .with_for_update()
    )
    result = await session.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise CandidateGuidelineGovernanceError(
            f"Candidate guideline {candidate_id} not found in this organization.",
            status_code=404,
        )

    if candidate.review_status != CandidateReviewStatus.PENDING_APPROVAL.value:
        raise CandidateGuidelineGovernanceError(
            f"Candidate guideline has already been reviewed (status: {candidate.review_status}).",
            status_code=400,
        )

    action = review_payload.action.upper()
    now = datetime.now(timezone.utc)

    if action == "APPROVE":
        # Promote candidate to active BrandGuideline
        activated_name = review_payload.modified_name or candidate.name
        activated_directive = review_payload.modified_directive or candidate.directive

        promoted_rule = BrandGuideline(
            organization_id=organization_id,
            name=activated_name,
            rule_type=candidate.rule_type,
            severity=candidate.severity,
            description=candidate.description,
            directive=activated_directive,
            examples_approved=list(candidate.examples_approved),
            examples_prohibited=list(candidate.examples_prohibited),
            tags=list(candidate.tags),
            is_active=True,
            created_by=actor.id,
        )
        session.add(promoted_rule)
        await session.flush()

        # Update candidate state
        candidate.review_status = CandidateReviewStatus.APPROVED.value
        candidate.reviewed_by = actor.id
        candidate.reviewed_at = now
        candidate.review_notes = review_payload.review_notes
        candidate.approved_guideline_id = promoted_rule.id

        # Record immutable audit entry in the same transaction
        audit_entry = CandidateGuidelineAuditEntry(
            organization_id=organization_id,
            candidate_guideline_id=candidate.id,
            action="APPROVE",
            actor_id=str(actor.id),
            actor_type="human",
            actor_name=actor.full_name,
            notes=review_payload.review_notes,
            details={
                "candidate_name": candidate.name,
                "promoted_guideline_id": str(promoted_rule.id),
                "modified_name": review_payload.modified_name,
                "modified_directive": review_payload.modified_directive,
                "rule_type": candidate.rule_type,
                "severity": candidate.severity,
            },
            timestamp=now,
        )
        session.add(audit_entry)
        await session.flush()

        logger.info(
            "Admin %s approved candidate %s -> promoted to active BrandGuideline %s (audit: %s)",
            actor.id,
            candidate.id,
            promoted_rule.id,
            audit_entry.id,
        )
        return candidate, promoted_rule

    elif action == "REJECT":
        # Reject candidate without promoting
        candidate.review_status = CandidateReviewStatus.REJECTED.value
        candidate.reviewed_by = actor.id
        candidate.reviewed_at = now
        candidate.review_notes = review_payload.review_notes

        # Record immutable audit entry in the same transaction
        audit_entry = CandidateGuidelineAuditEntry(
            organization_id=organization_id,
            candidate_guideline_id=candidate.id,
            action="REJECT",
            actor_id=str(actor.id),
            actor_type="human",
            actor_name=actor.full_name,
            notes=review_payload.review_notes,
            details={
                "candidate_name": candidate.name,
                "rule_type": candidate.rule_type,
                "severity": candidate.severity,
            },
            timestamp=now,
        )
        session.add(audit_entry)
        await session.flush()

        logger.info(
            "Admin %s rejected candidate guideline %s: %s (audit: %s)",
            actor.id,
            candidate.id,
            review_payload.review_notes,
            audit_entry.id,
        )
        return candidate, None

    else:
        raise CandidateGuidelineGovernanceError(
            f"Invalid review action '{review_payload.action}'. Allowed: APPROVE, REJECT.",
            status_code=400,
        )


async def list_candidate_guideline_audit_entries(
    session: AsyncSession,
    organization_id: UUID,
    candidate_id: Optional[UUID] = None,
) -> List[CandidateGuidelineAuditEntry]:
    """Retrieve immutable candidate guideline audit records strictly isolated to tenant."""
    query = (
        select(CandidateGuidelineAuditEntry)
        .where(CandidateGuidelineAuditEntry.organization_id == organization_id)
        .order_by(CandidateGuidelineAuditEntry.timestamp.desc())
    )
    if candidate_id:
        query = query.where(CandidateGuidelineAuditEntry.candidate_guideline_id == candidate_id)

    result = await session.execute(query)
    return list(result.scalars().all())
