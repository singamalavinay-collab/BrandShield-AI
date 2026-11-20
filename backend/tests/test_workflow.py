from datetime import datetime, timezone
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.compliance import ComplianceReport, RuleViolation
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.review import AuditEntry, ReviewDecision
from app.models.submission import ContentSubmission
from app.models.user import User


@pytest_asyncio.fixture
async def workflow_session():
    """Isolated async SQLite engine and session for submission workflow tests."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with test_engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON;")
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_maker() as session:
        # Organization
        org = Organization(
            id=uuid.uuid4(),
            name="Workflow Test Org",
            slug="workflow-test-org",
            is_active=True,
        )
        session.add(org)
        await session.flush()

        # Reviewer
        reviewer = User(
            id=uuid.uuid4(),
            organization_id=org.id,
            email="lead.reviewer@brandshield.ai",
            hashed_password=get_password_hash("LeadPass123!"),
            full_name="Lead Compliance Officer",
            role="REVIEWER",
            is_active=True,
        )
        session.add(reviewer)

        # Creator
        creator = User(
            id=uuid.uuid4(),
            organization_id=org.id,
            email="copywriter@brandshield.ai",
            hashed_password=get_password_hash("WriterPass123!"),
            full_name="Staff Copywriter",
            role="CREATOR",
            is_active=True,
        )
        session.add(creator)

        # Brand Rule
        rule = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="No Unsubstantiated Absolute Claims",
            rule_type="prohibited_claims",
            severity="medium",
            directive="Do not use words like '100% infallible' without legal sign-off.",
            description="Protect against regulatory false advertising claims.",
            is_active=True,
        )
        session.add(rule)
        await session.commit()

        yield session

    await test_engine.dispose()


@pytest_asyncio.fixture
async def reviewer_client(workflow_session: AsyncSession):
    """Client authenticated as Reviewer."""
    from sqlalchemy import select
    res = await workflow_session.execute(select(User).where(User.email == "lead.reviewer@brandshield.ai"))
    user = res.scalar_one()
    token = create_access_token(
        subject=str(user.id),
        org_id=str(user.organization_id),
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )

    async def override_get_db():
        yield workflow_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Submission Lifecycle Transition Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_full_governance_lifecycle_progression(reviewer_client: AsyncClient):
    """Test full sequential lifecycle: draft -> submitted -> analyzing -> violations_found -> under_human_review -> approved."""
    # 1. Create draft
    draft_res = await reviewer_client.post(
        "/api/v1/submissions",
        json={
            "title": "Enterprise Security Newsletter",
            "content": "BrandShield AI provides state of the art brand governance for enterprise clients.",
            "target_channel": "email_newsletter",
        },
    )
    assert draft_res.status_code == 201
    sub_data = draft_res.json()
    assert sub_data["status"] == "draft"
    sub_id = sub_data["id"]

    # 2. Submit draft
    submit_res = await reviewer_client.post(f"/api/v1/submissions/{sub_id}/submit")
    assert submit_res.status_code == 200
    assert submit_res.json()["status"] == "submitted"

    # 3. Trigger analysis -> evaluated by compliance engine -> transitions to passed_checks (0 violations)
    analyze_res = await reviewer_client.post(f"/api/v1/submissions/{sub_id}/analyze")
    assert analyze_res.status_code == 200
    assert analyze_res.json()["status"] == "passed_checks"

    # 4. Advance to human review
    advance_res = await reviewer_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review")
    assert advance_res.status_code == 200
    assert advance_res.json()["status"] == "under_human_review"

    # 5. Human reviewer approves as-is (0 violations)
    review_res = await reviewer_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve", "feedback": "Content perfectly meets brand tone."},
    )
    assert review_res.status_code == 200
    assert review_res.json()["submission"]["status"] == "approved"
    assert review_res.json()["submission"]["version"] == 1


@pytest.mark.asyncio
async def test_cannot_skip_analysis_to_human_review(reviewer_client: AsyncClient):
    """Architectural Invariant: Submissions must not skip compliance analysis directly to human review."""
    # 1. Create draft
    draft_res = await reviewer_client.post(
        "/api/v1/submissions",
        json={"title": "Draft", "content": "Sample", "target_channel": "twitter_x"},
    )
    sub_id = draft_res.json()["id"]

    # 2. Attempt advance-to-review directly from draft -> Must fail with 400
    skip_res = await reviewer_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review")
    assert skip_res.status_code == 400
    assert "Submissions must complete compliance analysis" in skip_res.json()["message"]

    # 3. Submit draft to 'submitted'
    await reviewer_client.post(f"/api/v1/submissions/{sub_id}/submit")

    # 4. Attempt advance-to-review directly from submitted -> Must fail with 400
    skip_sub_res = await reviewer_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review")
    assert skip_sub_res.status_code == 400
    assert "Direct transition from 'draft' or 'submitted' is strictly forbidden" in skip_sub_res.json()["message"]


@pytest.mark.asyncio
async def test_cannot_review_uninspected_content(reviewer_client: AsyncClient):
    """Architectural Invariant: Submissions in draft or submitted status cannot undergo human review."""
    draft_res = await reviewer_client.post(
        "/api/v1/submissions",
        json={"title": "Draft Review Test", "content": "Sample copy.", "target_channel": "blog_post"},
    )
    sub_id = draft_res.json()["id"]

    # Attempt to review draft
    review_res = await reviewer_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve"},
    )
    assert review_res.status_code == 400
    assert "under_human_review" in review_res.json()["message"]


# ==============================================================================
# 2. Unresolved Violations & Override Controls
# ==============================================================================

@pytest.mark.asyncio
async def test_approve_as_is_blocked_with_unresolved_violations_without_override(
    reviewer_client: AsyncClient,
    workflow_session: AsyncSession,
):
    """Enforce rule: Cannot Approve As-Is if active unresolved violations exist unless explicit override provided."""
    # Create submission and advance to review
    sub_res = await reviewer_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json={"title": "Violating Post", "content": "Our product is 100% infallible.", "target_channel": "twitter_x"},
    )
    sub_id = uuid.UUID(sub_res.json()["id"])

    # Seed a compliance report with an active violation
    report_id = uuid.uuid4()
    report = ComplianceReport(
        id=report_id,
        submission_id=sub_id,
        submission_version=1,
        is_compliant=False,
        total_violations=1,
        summary="Automated analysis detected 1 prohibited claim violation.",
        analyzed_at=datetime.now(timezone.utc),
    )
    workflow_session.add(report)
    await workflow_session.flush()

    # Get guideline rule
    rule_res = await workflow_session.execute(select(BrandGuideline).limit(1))
    rule = rule_res.scalar_one()

    violation = RuleViolation(
        id=uuid.uuid4(),
        report_id=report.id,
        rule_id=rule.id,
        rule_name=rule.name,
        rule_type="prohibited_claims",
        severity="critical",
        flagged_text="100% infallible",
        char_start=15,
        char_end=29,
        explanation="Absolute claim without legal qualification.",
    )
    workflow_session.add(violation)
    await workflow_session.commit()

    # Advance submission through analysis and into review queue
    await reviewer_client.post(f"/api/v1/submissions/{sub_id}/analyze")
    await reviewer_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review")

    # 1. Attempt Approve As-Is without override_reason -> Must be rejected with 400
    fail_res = await reviewer_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve", "feedback": "Trying to bypass violations"},
    )
    assert fail_res.status_code == 400
    assert "Active unresolved rule violations exist" in fail_res.json()["message"]
    assert "override_reason" in fail_res.json()["message"]

    # 2. Supply authorized override_reason -> Approval succeeds
    override_res = await reviewer_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={
            "action": "approve",
            "feedback": "Approved under legal executive waiver #LEG-2026-088.",
            "override_reason": "Executive legal authorization granted for specific campaign trial.",
        },
    )
    assert override_res.status_code == 200
    assert override_res.json()["submission"]["status"] == "approved"
    assert "Approved under legal executive waiver" in override_res.json()["decision"]["feedback"]


@pytest.mark.asyncio
async def test_edit_and_approve_resolves_content_and_increments_version(
    reviewer_client: AsyncClient,
):
    """Test that edit_and_approve replaces copy and increments content version."""
    sub_res = await reviewer_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json={"title": "Copy with Typo", "content": "Brandshield is great.", "target_channel": "linkedin"},
    )
    sub_id = sub_res.json()["id"]
    await reviewer_client.post(f"/api/v1/submissions/{sub_id}/analyze")
    await reviewer_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review")

    # Edit & Approve
    edit_res = await reviewer_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={
            "action": "edit_and_approve",
            "feedback": "Corrected BrandShield AI casing.",
            "edited_content": "BrandShield AI is great.",
        },
    )
    assert edit_res.status_code == 200
    data = edit_res.json()
    assert data["submission"]["status"] == "approved"
    assert data["submission"]["content"] == "BrandShield AI is great."
    assert data["submission"]["version"] == 2


@pytest.mark.asyncio
async def test_request_revision_and_resubmission_lifecycle(
    reviewer_client: AsyncClient,
):
    """Test request_revision transitions status, allowing author to resubmit."""
    sub_res = await reviewer_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json={"title": "Draft for Revision", "content": "Needs more detail.", "target_channel": "blog_post"},
    )
    sub_id = sub_res.json()["id"]
    await reviewer_client.post(f"/api/v1/submissions/{sub_id}/analyze")
    await reviewer_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review")

    # Request Revision
    rev_res = await reviewer_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={
            "action": "request_revision",
            "feedback": "Please elaborate on enterprise compliance architecture.",
        },
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["submission"]["status"] == "revision_requested"

    # Resubmit content from revision_requested
    resubmit_res = await reviewer_client.post(f"/api/v1/submissions/{sub_id}/submit")
    assert resubmit_res.status_code == 200
    assert resubmit_res.json()["status"] == "submitted"
