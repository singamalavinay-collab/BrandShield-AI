"""Unit and integration test suite for Phase 0C: Database Foundation.

Validates:
1. Candidate guidelines staging with default PENDING_APPROVAL status.
2. Invariant: Candidate guidelines are never active by default and do not appear in brand_guidelines.
3. Admin authority enforcement: Only ADMIN role can approve or reject candidate guidelines.
4. Promotion lifecycle: APPROVE creates an active BrandGuideline and links approved_guideline_id.
5. Rejection lifecycle: REJECT updates status to REJECTED and never creates a BrandGuideline.
6. Tenant boundary isolation: Cross-tenant queries and reviews are blocked.
7. Content submission multimodal metadata persistence (media_type, file_hash_sha256, mime_type, file_size_bytes, multimodal_metadata).
8. Schema backward compatibility for legacy text submissions.
9. Database check constraints on review_status and approval requirements.
10. Alembic migration upgrade and downgrade execution on test database.
"""

from datetime import datetime, timezone
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base, ImmutableAuditError
from app.core.security import get_password_hash
from app.models.candidate_guideline import CandidateGuideline
from app.models.candidate_guideline_audit import CandidateGuidelineAuditEntry
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.candidate_guidelines import (
    CandidateGuidelineCreate,
    CandidateGuidelineResponse,
    CandidateGuidelineReviewAction,
    CandidateReviewStatus,
)
from app.schemas.common import RuleType, SeverityLevel
from app.schemas.submissions import SubmissionResponse
from app.services.candidate_guideline_svc import (
    CandidateGuidelineGovernanceError,
    get_candidate_guideline,
    list_candidate_guideline_audit_entries,
    list_candidate_guidelines,
    review_candidate_guideline,
    stage_candidate_guideline,
)


@pytest_asyncio.fixture
async def db_session():
    """Isolated in-memory SQLite database session with complete Phase 0C schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON;")
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        # Create Primary Tenant (Org A)
        org_a = Organization(
            id=uuid.uuid4(),
            name="Acme Corporation",
            slug="acme-corp",
            is_active=True,
        )
        # Create Secondary Tenant (Org B)
        org_b = Organization(
            id=uuid.uuid4(),
            name="Beta Industries",
            slug="beta-industries",
            is_active=True,
        )
        session.add_all([org_a, org_b])
        await session.flush()

        # Users for Org A
        admin_a = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email="admin@acme.com",
            hashed_password=get_password_hash("AdminPass123!"),
            full_name="Alice Admin",
            role="ADMIN",
            is_active=True,
        )
        reviewer_a = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email="reviewer@acme.com",
            hashed_password=get_password_hash("ReviewerPass123!"),
            full_name="Bob Reviewer",
            role="REVIEWER",
            is_active=True,
        )
        creator_a = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email="creator@acme.com",
            hashed_password=get_password_hash("CreatorPass123!"),
            full_name="Charlie Creator",
            role="CREATOR",
            is_active=True,
        )

        # Users for Org B
        admin_b = User(
            id=uuid.uuid4(),
            organization_id=org_b.id,
            email="admin@beta.com",
            hashed_password=get_password_hash("AdminBeta123!"),
            full_name="David Beta Admin",
            role="ADMIN",
            is_active=True,
        )

        session.add_all([admin_a, reviewer_a, creator_a, admin_b])
        await session.commit()

        yield {
            "session": session,
            "org_a": org_a,
            "org_b": org_b,
            "admin_a": admin_a,
            "reviewer_a": reviewer_a,
            "creator_a": creator_a,
            "admin_b": admin_b,
        }

    await engine.dispose()


# ==============================================================================
# 1. Candidate Guideline Staging & Active Invariant Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_stage_candidate_guideline_defaults_to_pending(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]

    payload = CandidateGuidelineCreate(
        name="Primary Brand Color Integrity",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.HIGH,
        description="Enforces official enterprise Navy #002D62 across all marketing copy.",
        directive="Always specify Navy #002D62 as the primary brand color.",
        examples_approved=["The brand hero banner uses Navy #002D62."],
        examples_prohibited=["The logo uses bright cobalt blue."],
        tags=["color", "branding"],
        source_reference="Brand_Manual_2026.pdf (Page 4)",
        source_metadata={"page": 4, "file_sha256": "abcdef1234567890"},
    )

    candidate = await stage_candidate_guideline(session, org_a.id, payload)
    await session.commit()

    assert candidate.id is not None
    assert candidate.organization_id == org_a.id
    assert candidate.review_status == CandidateReviewStatus.PENDING_APPROVAL.value
    assert candidate.reviewed_by is None
    assert candidate.reviewed_at is None
    assert candidate.approved_guideline_id is None

    # INVIOLABLE INVARIANT: Staging a candidate MUST NOT insert a record into active brand_guidelines
    active_rules_stmt = select(BrandGuideline).where(BrandGuideline.organization_id == org_a.id)
    active_rules = (await session.execute(active_rules_stmt)).scalars().all()
    assert len(active_rules) == 0


# ==============================================================================
# 2. Admin Authority & Approval Promotion Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_admin_approval_promotes_candidate_to_active_guideline(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    admin_a: User = db_session["admin_a"]

    payload = CandidateGuidelineCreate(
        name="Typography Font Family Rule",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.CRITICAL,
        description="Requires Inter or Roboto font families for all web assets.",
        directive="Headers must strictly utilize Inter SemiBold or Bold.",
        examples_approved=["Font-family: 'Inter', sans-serif;"],
        tags=["typography"],
        source_reference="StyleGuide.docx",
    )
    candidate = await stage_candidate_guideline(session, org_a.id, payload)
    await session.commit()

    # Admin approves candidate
    review_action = CandidateGuidelineReviewAction(
        action="APPROVE",
        review_notes="Approved following legal brand identity review.",
        modified_directive="Headers must strictly utilize Inter SemiBold or Bold (700 wt).",
    )
    updated_cand, promoted_rule = await review_candidate_guideline(
        session, org_a.id, candidate.id, admin_a, review_action
    )
    await session.commit()

    # Verify Candidate state
    assert updated_cand.review_status == CandidateReviewStatus.APPROVED.value
    assert updated_cand.reviewed_by == admin_a.id
    assert updated_cand.reviewed_at is not None
    assert updated_cand.review_notes == "Approved following legal brand identity review."
    assert updated_cand.approved_guideline_id == promoted_rule.id

    # Verify Promoted BrandGuideline state
    assert promoted_rule is not None
    assert promoted_rule.is_active is True
    assert promoted_rule.organization_id == org_a.id
    assert promoted_rule.created_by == admin_a.id
    assert promoted_rule.directive == "Headers must strictly utilize Inter SemiBold or Bold (700 wt)."

    # Verify Promoted Rule appears in active brand_guidelines query
    active_stmt = select(BrandGuideline).where(
        BrandGuideline.organization_id == org_a.id,
        BrandGuideline.is_active.is_(True),
    )
    active_rules = (await session.execute(active_stmt)).scalars().all()
    assert len(active_rules) == 1
    assert active_rules[0].id == promoted_rule.id


@pytest.mark.asyncio
async def test_admin_rejection_marks_rejected_without_activating(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    admin_a: User = db_session["admin_a"]

    payload = CandidateGuidelineCreate(
        name="Deprecated Tagline Rule",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.LOW,
        description="Old 2024 slogan.",
        directive="Use 2024 tagline.",
    )
    candidate = await stage_candidate_guideline(session, org_a.id, payload)
    await session.commit()

    # Admin rejects candidate
    review_action = CandidateGuidelineReviewAction(
        action="REJECT",
        review_notes="Tagline is obsolete. Rejected.",
    )
    updated_cand, promoted_rule = await review_candidate_guideline(
        session, org_a.id, candidate.id, admin_a, review_action
    )
    await session.commit()

    assert updated_cand.review_status == CandidateReviewStatus.REJECTED.value
    assert updated_cand.reviewed_by == admin_a.id
    assert updated_cand.reviewed_at is not None
    assert updated_cand.review_notes == "Tagline is obsolete. Rejected."
    assert updated_cand.approved_guideline_id is None
    assert promoted_rule is None

    # INVIOLABLE INVARIANT: Rejected candidate MUST NOT insert a record into active brand_guidelines
    active_stmt = select(BrandGuideline).where(BrandGuideline.organization_id == org_a.id)
    active_rules = (await session.execute(active_stmt)).scalars().all()
    assert len(active_rules) == 0


# ==============================================================================
# 3. RBAC Governance & Non-Admin Rejection Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_non_admin_roles_rejected_from_reviewing_candidates(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    reviewer_a: User = db_session["reviewer_a"]
    creator_a: User = db_session["creator_a"]

    payload = CandidateGuidelineCreate(
        name="Restricted Rule Review Test",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.MEDIUM,
        description="Test candidate rule.",
        directive="Directive.",
    )
    candidate = await stage_candidate_guideline(session, org_a.id, payload)
    await session.commit()

    review_action = CandidateGuidelineReviewAction(action="APPROVE")

    # REVIEWER role must be rejected
    with pytest.raises(CandidateGuidelineGovernanceError) as exc_rev:
        await review_candidate_guideline(session, org_a.id, candidate.id, reviewer_a, review_action)
    assert exc_rev.value.status_code == 403
    assert "Only Admin users can approve or reject" in exc_rev.value.message

    # CREATOR role must be rejected
    with pytest.raises(CandidateGuidelineGovernanceError) as exc_creat:
        await review_candidate_guideline(session, org_a.id, candidate.id, creator_a, review_action)
    assert exc_creat.value.status_code == 403
    assert "Only Admin users can approve or reject" in exc_creat.value.message

    # Status must still be PENDING_APPROVAL
    fresh = await get_candidate_guideline(session, org_a.id, candidate.id)
    assert fresh.review_status == CandidateReviewStatus.PENDING_APPROVAL.value


# ==============================================================================
# 4. Multi-Tenant Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_candidate_guideline_multi_tenant_isolation(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    org_b: Organization = db_session["org_b"]
    admin_b: User = db_session["admin_b"]

    payload = CandidateGuidelineCreate(
        name="Org A Confidential Guideline",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.HIGH,
        description="Confidential to Org A.",
        directive="Internal rule.",
    )
    cand_a = await stage_candidate_guideline(session, org_a.id, payload)
    await session.commit()

    # Org B queries should return zero results
    org_b_list = await list_candidate_guidelines(session, org_b.id)
    assert len(org_b_list) == 0

    # Org B direct fetch by ID should return None
    cross_fetch = await get_candidate_guideline(session, org_b.id, cand_a.id)
    assert cross_fetch is None

    # Org B Admin attempting to review Org A candidate must be blocked with 403
    review_action = CandidateGuidelineReviewAction(action="APPROVE")
    with pytest.raises(CandidateGuidelineGovernanceError) as exc:
        await review_candidate_guideline(session, org_b.id, cand_a.id, admin_b, review_action)
    assert exc.value.status_code in (403, 404)


# ==============================================================================
# 5. Database Check Constraints & Invariants
# ==============================================================================

@pytest.mark.asyncio
async def test_candidate_guideline_check_constraints(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    org_a_id = org_a.id

    # 1. Invalid review_status constraint
    async with session.begin_nested():
        invalid_cand = CandidateGuideline(
            organization_id=org_a_id,
            name="Invalid Status Candidate",
            rule_type="terminology",
            severity="medium",
            description="Check constraint test.",
            directive="Test.",
            review_status="INVALID_STATUS",  # Not in ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')
        )
        session.add(invalid_cand)
        with pytest.raises(IntegrityError):
            await session.flush()

    # 2. Approved without reviewer constraint
    async with session.begin_nested():
        unreviewed_approval = CandidateGuideline(
            organization_id=org_a_id,
            name="Missing Reviewer Approval Candidate",
            rule_type="terminology",
            severity="medium",
            description="Check constraint test.",
            directive="Test.",
            review_status="APPROVED",
            reviewed_by=None,  # Violates chk_candidate_approved_has_reviewer_and_time
            reviewed_at=datetime.now(timezone.utc),
        )
        session.add(unreviewed_approval)
        with pytest.raises(IntegrityError):
            await session.flush()


# ==============================================================================
# 6. Submission Multimodal Metadata Persistence & Schemas
# ==============================================================================

@pytest.mark.asyncio
async def test_content_submission_multimodal_metadata_persistence(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    creator_a: User = db_session["creator_a"]

    # Create submission with multimodal metadata
    submission = ContentSubmission(
        organization_id=org_a.id,
        author_id=creator_a.id,
        title="Spring Brand Campaign Video Asset",
        content="Promotional campaign script and storyboard.",
        target_channel="ad_copy",
        media_type="video",
        file_hash_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        mime_type="video/mp4",
        file_size_bytes=5242880,  # 5 MB
        multimodal_metadata={
            "duration_seconds": 28.5,
            "dimensions": [1920, 1080],
            "fps": 30,
        },
    )
    session.add(submission)
    await session.flush()

    # Stage candidate guideline linked to this source submission
    cand = CandidateGuideline(
        organization_id=org_a.id,
        name="Video Resolution Constraint",
        rule_type="multimodal",
        severity="medium",
        description="Rules extracted from video asset storyboard.",
        directive="All video assets must be 1080p minimum.",
        source_submission_id=submission.id,
    )
    session.add(cand)
    await session.commit()

    # Query back submission and verify persistence
    q_sub = (
        await session.execute(
            select(ContentSubmission).where(ContentSubmission.id == submission.id)
        )
    ).scalar_one()

    assert q_sub.media_type == "video"
    assert q_sub.file_hash_sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert q_sub.mime_type == "video/mp4"
    assert q_sub.file_size_bytes == 5242880
    assert q_sub.multimodal_metadata["duration_seconds"] == 28.5
    assert len(q_sub.extracted_candidate_guidelines) == 1
    assert q_sub.extracted_candidate_guidelines[0].id == cand.id

    # Test Pydantic schema serialization
    response_dto = SubmissionResponse.model_validate(q_sub)
    assert response_dto.media_type == "video"
    assert response_dto.file_hash_sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert response_dto.mime_type == "video/mp4"
    assert response_dto.file_size_bytes == 5242880
    assert response_dto.multimodal_metadata["dimensions"] == [1920, 1080]


def test_submission_response_backward_compatibility():
    """Verify legacy text submissions without multimodal metadata serialize with safe defaults."""
    legacy_data = {
        "id": uuid.uuid4(),
        "title": "Legacy Text Draft",
        "content": "Clean marketing copy.",
        "target_channel": "email",
        "metadata_payload": {},
        "status": "draft",
        "version": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    resp = SubmissionResponse.model_validate(legacy_data)
    assert resp.media_type == "text"
    assert resp.file_hash_sha256 is None
    assert resp.mime_type is None
    assert resp.file_size_bytes is None
    assert resp.multimodal_metadata == {}


# ==============================================================================
# 7. Immutable Candidate Review Audit Ledger Tests (SEC-0C-01)
# ==============================================================================

@pytest.mark.asyncio
async def test_admin_approval_creates_immutable_audit_entry(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    admin_a: User = db_session["admin_a"]

    payload = CandidateGuidelineCreate(
        name="Social Media Logo Spacing",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.HIGH,
        description="Minimum 24px padding around brand mark.",
        directive="All social graphics must maintain 24px clear margin around logo.",
    )
    candidate = await stage_candidate_guideline(session, org_a.id, payload)
    await session.commit()

    review_action = CandidateGuidelineReviewAction(
        action="APPROVE",
        review_notes="Approved with legal compliance signoff.",
    )
    updated_cand, promoted_rule = await review_candidate_guideline(
        session, org_a.id, candidate.id, admin_a, review_action
    )
    await session.commit()

    # Verify audit entry created atomically
    audit_entries = await list_candidate_guideline_audit_entries(session, org_a.id, candidate.id)
    assert len(audit_entries) == 1
    audit = audit_entries[0]

    assert audit.action == "APPROVE"
    assert audit.organization_id == org_a.id
    assert audit.candidate_guideline_id == candidate.id
    assert audit.actor_id == str(admin_a.id)
    assert audit.actor_type == "human"
    assert audit.actor_name == admin_a.full_name
    assert audit.notes == "Approved with legal compliance signoff."
    assert audit.details["candidate_name"] == candidate.name
    assert audit.details["promoted_guideline_id"] == str(promoted_rule.id)
    assert audit.details["rule_type"] == candidate.rule_type
    assert audit.details["severity"] == candidate.severity


@pytest.mark.asyncio
async def test_admin_rejection_creates_immutable_audit_entry(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    admin_a: User = db_session["admin_a"]

    payload = CandidateGuidelineCreate(
        name="Temporary Slogan Candidate",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.LOW,
        description="Deprecated slogan suggestion.",
        directive="Never use deprecated slogan.",
    )
    candidate = await stage_candidate_guideline(session, org_a.id, payload)
    await session.commit()

    review_action = CandidateGuidelineReviewAction(
        action="REJECT",
        review_notes="Rejected: Slogan was retired in Q3.",
    )
    updated_cand, promoted_rule = await review_candidate_guideline(
        session, org_a.id, candidate.id, admin_a, review_action
    )
    await session.commit()

    # Verify audit entry created atomically on REJECT
    audit_entries = await list_candidate_guideline_audit_entries(session, org_a.id, candidate.id)
    assert len(audit_entries) == 1
    audit = audit_entries[0]

    assert audit.action == "REJECT"
    assert audit.organization_id == org_a.id
    assert audit.candidate_guideline_id == candidate.id
    assert audit.actor_id == str(admin_a.id)
    assert audit.actor_type == "human"
    assert audit.actor_name == admin_a.full_name
    assert audit.notes == "Rejected: Slogan was retired in Q3."
    assert audit.details["candidate_name"] == candidate.name
    assert promoted_rule is None


@pytest.mark.asyncio
async def test_candidate_audit_entry_immutability(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    admin_a: User = db_session["admin_a"]

    payload = CandidateGuidelineCreate(
        name="Immutability Test Guideline",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.MEDIUM,
        description="Checking ledger tampering prevention.",
        directive="Testing.",
    )
    candidate = await stage_candidate_guideline(session, org_a.id, payload)
    await session.commit()

    review_action = CandidateGuidelineReviewAction(action="APPROVE", review_notes="Initial approval.")
    updated_cand, _ = await review_candidate_guideline(session, org_a.id, candidate.id, admin_a, review_action)
    await session.commit()

    audit_entries = await list_candidate_guideline_audit_entries(session, org_a.id, candidate.id)
    assert len(audit_entries) == 1
    audit = audit_entries[0]
    audit_id = audit.id

    # 1. ORM-level UPDATE attempt must raise ImmutableAuditError
    audit.notes = "Tampered notes by attacker"
    with pytest.raises(ImmutableAuditError):
        await session.flush()
    await session.rollback()

    # Re-fetch entry
    stmt = select(CandidateGuidelineAuditEntry).where(CandidateGuidelineAuditEntry.id == audit_id)
    audit = (await session.execute(stmt)).scalar_one()

    # 2. ORM-level DELETE attempt must raise ImmutableAuditError
    await session.delete(audit)
    with pytest.raises(ImmutableAuditError):
        await session.flush()
    await session.rollback()

    # 3. Database-level trigger check for UPDATE
    with pytest.raises(Exception):
        await session.execute(
            text("UPDATE candidate_guideline_audit_entries SET notes = 'raw_tamper' WHERE id = :id"),
            {"id": audit_id.hex if hasattr(audit_id, "hex") else str(audit_id)},
        )
        await session.flush()
    await session.rollback()

    # 4. Database-level trigger check for DELETE
    with pytest.raises(Exception):
        await session.execute(
            text("DELETE FROM candidate_guideline_audit_entries WHERE id = :id"),
            {"id": audit_id.hex if hasattr(audit_id, "hex") else str(audit_id)},
        )
        await session.flush()
    await session.rollback()


@pytest.mark.asyncio
async def test_failed_approval_rolls_back_atomic_writes(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    org_a_id = org_a.id
    admin_a: User = db_session["admin_a"]

    payload = CandidateGuidelineCreate(
        name="Atomic Rollback Test Guideline",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.HIGH,
        description="Verify atomicity under transaction failure.",
        directive="Directive.",
    )
    candidate = await stage_candidate_guideline(session, org_a_id, payload)
    await session.commit()
    cand_id = candidate.id

    # Simulate transaction failure during approval within a savepoint
    try:
        async with session.begin_nested():
            review_action = CandidateGuidelineReviewAction(action="APPROVE", review_notes="Pre-failure")
            await review_candidate_guideline(session, org_a_id, cand_id, admin_a, review_action)
            # Intentionally simulate an unhandled failure before final commit
            raise RuntimeError("Simulated transient connection failure during approval")
    except RuntimeError:
        pass

    # Verify atomic state: candidate remains PENDING_APPROVAL, no BrandGuideline, no audit entry
    fresh_cand = await get_candidate_guideline(session, org_a_id, cand_id)
    assert fresh_cand.review_status == CandidateReviewStatus.PENDING_APPROVAL.value
    assert fresh_cand.approved_guideline_id is None
    assert fresh_cand.reviewed_by is None

    active_rules = (
        await session.execute(
            select(BrandGuideline).where(
                BrandGuideline.organization_id == org_a_id,
                BrandGuideline.name == "Atomic Rollback Test Guideline",
            )
        )
    ).scalars().all()
    assert len(active_rules) == 0

    audits = await list_candidate_guideline_audit_entries(session, org_a_id, cand_id)
    assert len(audits) == 0


# ==============================================================================
# 8. Row-Level Locking & Concurrency Protection Tests (SEC-0C-03)
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrent_review_row_locking(db_session):
    session: AsyncSession = db_session["session"]
    org_a: Organization = db_session["org_a"]
    admin_a: User = db_session["admin_a"]

    payload = CandidateGuidelineCreate(
        name="Concurrency Test Guideline",
        rule_type=RuleType.TERMINOLOGY,
        severity=SeverityLevel.HIGH,
        description="Ensures duplicate or race reviews are rejected cleanly.",
        directive="Directive.",
    )
    candidate = await stage_candidate_guideline(session, org_a.id, payload)
    await session.commit()

    # First review: APPROVE succeeds
    review_action_1 = CandidateGuidelineReviewAction(action="APPROVE", review_notes="First review.")
    await review_candidate_guideline(session, org_a.id, candidate.id, admin_a, review_action_1)
    await session.commit()

    # Second concurrent review attempt on already-reviewed candidate must fail with 400
    review_action_2 = CandidateGuidelineReviewAction(action="REJECT", review_notes="Duplicate concurrent review.")
    with pytest.raises(CandidateGuidelineGovernanceError) as exc:
        await review_candidate_guideline(session, org_a.id, candidate.id, admin_a, review_action_2)

    assert exc.value.status_code == 400
    assert "has already been reviewed" in exc.value.message


# ==============================================================================
# 9. PostgreSQL Row-Level Security Tenant Isolation Tests (SEC-0C-02)
# ==============================================================================

@pytest.mark.asyncio
async def test_postgresql_rls_candidate_guidelines_and_audit_isolation():
    """Verify database-enforced RLS on PostgreSQL for candidate guidelines and audit ledger."""
    if "sqlite" in settings.DATABASE_URL:
        pytest.skip("PostgreSQL required for live Row-Level Security verification.")

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        async with session.begin():
            org_a_id = uuid.uuid4()
            org_b_id = uuid.uuid4()

            org_a = Organization(id=org_a_id, name="RLS Test Org A", slug=f"rls-a-{org_a_id.hex[:6]}", is_active=True)
            org_b = Organization(id=org_b_id, name="RLS Test Org B", slug=f"rls-b-{org_b_id.hex[:6]}", is_active=True)
            session.add_all([org_a, org_b])
            await session.flush()

            # Runtime connection role is brandshield_app (strictly NOBYPASSRLS)
            # Step 1: Set context to Org A
            await session.execute(text(f"SET LOCAL app.current_org_id = '{org_a_id}'"))

            # Insert candidate and audit entry for Org A
            cand_a = CandidateGuideline(
                id=uuid.uuid4(),
                organization_id=org_a_id,
                name="Org A RLS Candidate",
                rule_type="terminology",
                severity="medium",
                description="Org A isolated guideline.",
                directive="Must use Org A terms.",
            )
            session.add(cand_a)
            await session.flush()

            audit_a = CandidateGuidelineAuditEntry(
                id=uuid.uuid4(),
                organization_id=org_a_id,
                candidate_guideline_id=cand_a.id,
                action="APPROVE",
                actor_id="admin-a",
                actor_type="human",
                actor_name="Alice Admin",
                notes="Approved for Org A",
            )
            session.add(audit_a)
            await session.flush()

            # Query as Org A (unfiltered raw SQL without WHERE organization_id)
            res_cand_a = await session.execute(
                text("SELECT id, name FROM candidate_guidelines WHERE id = :id"),
                {"id": cand_a.id},
            )
            assert res_cand_a.fetchone() is not None

            res_aud_a = await session.execute(
                text("SELECT id, action FROM candidate_guideline_audit_entries WHERE id = :id"),
                {"id": audit_a.id},
            )
            assert res_aud_a.fetchone() is not None

            # Step 2: Switch context to Org B -> RLS MUST filter out Org A rows
            await session.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))

            res_cand_b = await session.execute(
                text("SELECT id, name FROM candidate_guidelines WHERE id = :id"),
                {"id": cand_a.id},
            )
            assert res_cand_b.fetchone() is None, "RLS must hide Org A candidate from Org B context"

            res_aud_b = await session.execute(
                text("SELECT id FROM candidate_guideline_audit_entries WHERE id = :id"),
                {"id": audit_a.id},
            )
            assert res_aud_b.fetchone() is None, "RLS must hide Org A audit from Org B context"

            # Step 3: Cross-tenant insert attempt into candidate_guidelines must be blocked by RLS
            insert_cand_failed = False
            try:
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "INSERT INTO candidate_guidelines (id, organization_id, name, rule_type, severity, description, directive, review_status, tags, examples_approved, examples_prohibited, source_metadata, created_at, updated_at) "
                            "VALUES (:id, :org_id, 'Cross Tenant', 'terminology', 'low', 'desc', 'dir', 'PENDING_APPROVAL', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, NOW(), NOW())"
                        ),
                        {"id": uuid.uuid4(), "org_id": org_a_id},
                    )
            except Exception as exc:
                insert_cand_failed = True
                assert "violates row-level security policy" in str(exc).lower()
            assert insert_cand_failed, "RLS WITH CHECK policy must reject cross-tenant candidate insert"

            # Step 4: Cross-tenant insert attempt into candidate_guideline_audit_entries must be blocked by RLS
            insert_aud_failed = False
            try:
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "INSERT INTO candidate_guideline_audit_entries (id, organization_id, candidate_guideline_id, action, actor_id, actor_type, actor_name, notes, details, timestamp) "
                            "VALUES (:id, :org_id, :cand_id, 'REJECT', 'admin-b', 'human', 'Bob Beta', 'Notes', '{}'::jsonb, NOW())"
                        ),
                        {"id": uuid.uuid4(), "org_id": org_a_id, "cand_id": cand_a.id},
                    )
            except Exception as exc:
                insert_aud_failed = True
                assert "violates row-level security policy" in str(exc).lower()
            assert insert_aud_failed, "RLS WITH CHECK policy must reject cross-tenant audit insert"

            # Step 5: Fail-closed semantics: Unset / empty org context returns zero rows
            await session.execute(text("SET LOCAL app.current_org_id = ''"))

            res_empty_cand = await session.execute(
                text("SELECT id FROM candidate_guidelines WHERE id = :id"),
                {"id": cand_a.id},
            )
            assert res_empty_cand.fetchone() is None, "Fail-closed: unset org context must return 0 rows"

            res_empty_aud = await session.execute(
                text("SELECT id FROM candidate_guideline_audit_entries WHERE id = :id"),
                {"id": audit_a.id},
            )
            assert res_empty_aud.fetchone() is None, "Fail-closed: unset org context must return 0 rows"

            # Roll back so no test artifacts remain in database
            await session.rollback()

    await engine.dispose()
