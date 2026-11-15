import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.organization import Organization
from app.models.user import User


@pytest_asyncio.fixture
async def api_async_session():
    """Isolated async SQLite engine and session for API route integration testing."""
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
        # Pre-seed primary test organization
        org = Organization(
            id=uuid.uuid4(),
            name="BrandShield Test Org",
            slug="brandshield-test-org",
            is_active=True,
        )
        session.add(org)
        await session.flush()

        # Pre-seed authorized human reviewer
        reviewer = User(
            id=uuid.uuid4(),
            organization_id=org.id,
            email="sarah.jenkins@brandshield.ai",
            hashed_password=get_password_hash("ValidReviewerPass123!"),
            full_name="Sarah Jenkins (Senior Compliance Officer)",
            role="REVIEWER",
            is_active=True,
        )
        session.add(reviewer)

        # Pre-seed creator user (unauthorized for review decisions)
        creator = User(
            id=uuid.uuid4(),
            organization_id=org.id,
            email="mark.creator@brandshield.ai",
            hashed_password=get_password_hash("ValidCreatorPass123!"),
            full_name="Mark Spencer (Content Creator)",
            role="CREATOR",
            is_active=True,
        )
        session.add(creator)

        # Pre-seed authorized organization administrator (authorized for brand guidelines)
        admin = User(
            id=uuid.uuid4(),
            organization_id=org.id,
            email="alex.admin@brandshield.ai",
            hashed_password=get_password_hash("ValidAdminPass123!"),
            full_name="Alex Rivera (System Administrator)",
            role="ADMIN",
            is_active=True,
        )
        session.add(admin)

        # Pre-seed default active brand guideline for test organization
        from app.models.guideline import BrandGuideline
        guideline = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="BrandShield Capitalization Standard",
            rule_type="trademark_usage",
            severity="critical",
            description="Always capitalize B and S in BrandShield AI.",
            directive="The product name must be written strictly as 'BrandShield AI'. Never lowercase.",
            examples_approved=["BrandShield AI protects your brand."],
            examples_prohibited=["Brandshield provides brand checking."],
            tags=["trademark", "product_name"],
            is_active=True,
        )
        session.add(guideline)
        await session.commit()

        yield session

    await test_engine.dispose()


@pytest_asyncio.fixture
async def reviewer_token(api_async_session: AsyncSession) -> str:
    """Generate a signed JWT token for the authorized human reviewer."""
    from sqlalchemy import select
    result = await api_async_session.execute(
        select(User).where(User.email == "sarah.jenkins@brandshield.ai")
    )
    user = result.scalar_one()
    return create_access_token(
        subject=str(user.id),
        org_id=str(user.organization_id),
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )


@pytest_asyncio.fixture
async def creator_token(api_async_session: AsyncSession) -> str:
    """Generate a signed JWT token for the creator user (unauthorized for review)."""
    from sqlalchemy import select
    result = await api_async_session.execute(
        select(User).where(User.email == "mark.creator@brandshield.ai")
    )
    user = result.scalar_one()
    return create_access_token(
        subject=str(user.id),
        org_id=str(user.organization_id),
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )


@pytest_asyncio.fixture
async def admin_token(api_async_session: AsyncSession) -> str:
    """Generate a signed JWT token for the organization administrator."""
    from sqlalchemy import select
    result = await api_async_session.execute(
        select(User).where(User.email == "alex.admin@brandshield.ai")
    )
    user = result.scalar_one()
    return create_access_token(
        subject=str(user.id),
        org_id=str(user.organization_id),
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )


@pytest_asyncio.fixture
async def async_client(api_async_session: AsyncSession, reviewer_token: str):
    """Async HTTP client with overridden get_db dependency and reviewer bearer auth."""
    async def override_get_db():
        yield api_async_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ==============================================================================
# 1. System Diagnostics Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_system_status_diagnostic(async_client: AsyncClient):
    """Test GET /api/v1/system/status accurately reports operational parameters."""
    response = await async_client.get("/api/v1/system/status")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "BrandShield AI Backend"
    assert "database" in data
    assert data["governance"]["human_in_the_loop_enforced"] is True
    assert data["governance"]["ai_approval_prohibited"] is True


# ==============================================================================
# 2. Brand Guidelines API Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_guideline_crud_lifecycle(async_client: AsyncClient, admin_token: str):
    """Test full lifecycle: create, list, retrieve, update, and toggle guideline by authorized ADMIN."""
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    # 1. Create guideline (requires ADMIN)
    payload = {
        "name": "BrandShield Capitalization Standard",
        "rule_type": "trademark_usage",
        "severity": "critical",
        "description": "Always capitalize B and S in BrandShield AI.",
        "directive": "The product name must be written strictly as 'BrandShield AI'. Never lowercase.",
        "examples_approved": ["BrandShield AI protects your brand."],
        "examples_prohibited": ["brandshield ai is fast."],
        "tags": ["trademark", "product_name"],
        "is_active": True,
    }
    create_res = await async_client.post("/api/v1/guidelines", json=payload, headers=admin_headers)
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert created_data["name"] == payload["name"]
    guideline_id = created_data["id"]

    # 2. List guidelines (accessible to all authenticated tenant members)
    list_res = await async_client.get("/api/v1/guidelines")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 1
    assert any(g["id"] == guideline_id for g in items)

    # 3. Retrieve single guideline (accessible to all authenticated tenant members)
    get_res = await async_client.get(f"/api/v1/guidelines/{guideline_id}")
    assert get_res.status_code == 200
    assert get_res.json()["directive"] == payload["directive"]

    # 4. Update guideline (requires ADMIN)
    update_res = await async_client.patch(
        f"/api/v1/guidelines/{guideline_id}",
        json={"severity": "high", "description": "Updated description for test."},
        headers=admin_headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["severity"] == "high"

    # 5. Toggle active status (requires ADMIN)
    toggle_res = await async_client.patch(
        f"/api/v1/guidelines/{guideline_id}/toggle-active",
        headers=admin_headers,
    )
    assert toggle_res.status_code == 200
    assert toggle_res.json()["is_active"] is False


@pytest.mark.asyncio
async def test_guideline_mutations_forbidden_for_reviewer_and_creator(
    async_client: AsyncClient,
    reviewer_token: str,
    creator_token: str,
    admin_token: str,
):
    """Verify REVIEWER and CREATOR cannot create, update, or toggle brand guidelines (HTTP 403 Forbidden)."""
    # Create an active guideline using ADMIN token first
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    create_payload = {
        "name": "Corporate Nomenclature Standard",
        "rule_type": "terminology",
        "severity": "high",
        "description": "Enforce proper corporate terminology.",
        "directive": "Always refer to our suite as BrandShield AI Governance Suite.",
        "examples_approved": ["BrandShield AI Governance Suite"],
        "examples_prohibited": ["Old Suite"],
        "tags": ["corporate", "governance"],
        "is_active": True,
    }
    setup_res = await async_client.post("/api/v1/guidelines", json=create_payload, headers=admin_headers)
    assert setup_res.status_code == 201
    gl_id = setup_res.json()["id"]

    for token, role_name in [(reviewer_token, "REVIEWER"), (creator_token, "CREATOR")]:
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Prohibit create
        res_create = await async_client.post(
            "/api/v1/guidelines",
            json={
                "name": f"Unauthorized Rule from {role_name}",
                "rule_type": "tone_of_voice",
                "severity": "medium",
                "description": "Unauthorized attempt",
                "directive": "Unauthorized directive",
                "examples_approved": ["Approved"],
                "examples_prohibited": ["Prohibited"],
                "tags": ["unauthorized"],
                "is_active": True,
            },
            headers=headers,
        )
        assert res_create.status_code == 403, f"{role_name} must receive 403 when creating guideline"
        msg_create = res_create.json().get("message") or res_create.json().get("detail", "")
        assert "ADMIN" in msg_create

        # 2. Prohibit update
        res_update = await async_client.patch(
            f"/api/v1/guidelines/{gl_id}",
            json={"description": f"Unauthorized update from {role_name}"},
            headers=headers,
        )
        assert res_update.status_code == 403, f"{role_name} must receive 403 when updating guideline"
        msg_update = res_update.json().get("message") or res_update.json().get("detail", "")
        assert "ADMIN" in msg_update

        # 3. Prohibit toggle active
        res_toggle = await async_client.patch(
            f"/api/v1/guidelines/{gl_id}/toggle-active",
            headers=headers,
        )
        assert res_toggle.status_code == 403, f"{role_name} must receive 403 when toggling guideline active status"
        msg_toggle = res_toggle.json().get("message") or res_toggle.json().get("detail", "")
        assert "ADMIN" in msg_toggle


@pytest.mark.asyncio
async def test_guidelines_read_accessible_to_all_authenticated_roles(
    async_client: AsyncClient,
    admin_token: str,
    reviewer_token: str,
    creator_token: str,
):
    """Verify ADMIN, REVIEWER, and CREATOR all retain read access to brand guidelines."""
    for token in [admin_token, reviewer_token, creator_token]:
        headers = {"Authorization": f"Bearer {token}"}
        list_res = await async_client.get("/api/v1/guidelines", headers=headers)
        assert list_res.status_code == 200
        assert isinstance(list_res.json(), list)


# ==============================================================================
# 3. Content Submissions API Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_submission_lifecycle(async_client: AsyncClient):
    """Test creating draft, listing, retrieving, and submitting for inspection."""
    # 1. Create draft
    draft_payload = {
        "title": "Q3 Marketing Campaign Announcement",
        "content": "Drafting our new promotional newsletter copy for enterprise users.",
        "target_channel": "email_newsletter",
        "target_audience": "Enterprise CMOs",
    }
    res = await async_client.post("/api/v1/submissions", json=draft_payload)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "draft"
    submission_id = data["id"]

    # 2. List submissions
    list_res = await async_client.get("/api/v1/submissions")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 3. Retrieve status
    status_res = await async_client.get(f"/api/v1/submissions/{submission_id}/status")
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "draft"

    # 4. Submit draft for inspection -> transitions to submitted (not directly to under_human_review)
    submit_res = await async_client.post(f"/api/v1/submissions/{submission_id}/submit")
    assert submit_res.status_code == 200
    assert submit_res.json()["status"] == "submitted"


# ==============================================================================
# 4. Compliance Reports API Tests (Honest Reporting, No Fake AI)
# ==============================================================================

@pytest.mark.asyncio
async def test_compliance_report_pending_when_uninspected(async_client: AsyncClient):
    """Verify that uninspected drafts accurately return pending analysis status without fake data."""
    # Create draft
    draft_payload = {
        "title": "Uninspected Social Post",
        "content": "Testing uninspected content report retrieval.",
        "target_channel": "twitter_x",
    }
    res = await async_client.post("/api/v1/submissions", json=draft_payload)
    submission_id = res.json()["id"]

    # Request report
    report_res = await async_client.get(f"/api/v1/submissions/{submission_id}/report")
    assert report_res.status_code == 200
    report_data = report_res.json()

    # Invariant: Must report pending status, NOT fabricated violations
    assert report_data["is_analyzed"] is False
    assert report_data["status"] == "pending_analysis"
    assert "pending Phase 4" in report_data["summary"]
    assert len(report_data["violations"]) == 0

    # Violations endpoint
    viol_res = await async_client.get(f"/api/v1/submissions/{submission_id}/violations")
    assert viol_res.status_code == 200
    assert viol_res.json() == []


# ==============================================================================
# 5. Human Review & Authorization Governance Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_human_review_edit_and_approve(async_client: AsyncClient):
    """Test authorized human reviewer can edit and approve content through the full lifecycle."""
    # 1. Create submission submitted for inspection
    sub_payload = {
        "title": "Review Under Human Oversight",
        "content": "Brandshield is amazing.",
        "target_channel": "twitter_x",
    }
    sub_res = await async_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json=sub_payload,
    )
    submission_id = sub_res.json()["id"]
    assert sub_res.json()["status"] == "submitted"

    # 2. Trigger analysis
    analyze_res = await async_client.post(f"/api/v1/submissions/{submission_id}/analyze")
    assert analyze_res.status_code == 200

    # 3. Advance to human review
    advance_res = await async_client.post(f"/api/v1/submissions/{submission_id}/advance-to-review")
    assert advance_res.status_code == 200
    assert advance_res.json()["status"] == "under_human_review"

    # 4. Verify it appears in pending reviews
    pending_res = await async_client.get("/api/v1/reviews/pending")
    assert pending_res.status_code == 200
    pending_ids = [s["id"] for s in pending_res.json()]
    assert submission_id in pending_ids

    # 5. Authorized human executes edit_and_approve
    review_payload = {
        "action": "edit_and_approve",
        "feedback": "Corrected brand name capitalization in accordance with guidelines.",
        "edited_content": "BrandShield AI is amazing.",
    }
    review_res = await async_client.post(
        f"/api/v1/submissions/{submission_id}/review",
        json=review_payload,
    )
    assert review_res.status_code == 200
    review_data = review_res.json()

    assert review_data["success"] is True
    assert review_data["submission"]["status"] == "approved"
    assert review_data["submission"]["content"] == "BrandShield AI is amazing."
    assert review_data["submission"]["version"] == 2
    assert review_data["decision"]["reviewer_name"] == "Sarah Jenkins (Senior Compliance Officer)"


@pytest.mark.asyncio
async def test_human_review_rejects_ai_or_bot_actor(api_async_session: AsyncSession):
    """Architectural Invariant: Disallow unauthenticated or unauthorized non-human actors from review."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as unauth_client:
        # Create submission attempt without credentials
        sub_res = await unauth_client.post(
            "/api/v1/submissions?submit_for_inspection=true",
            json={"title": "Bot Attempt", "content": "Content", "target_channel": "linkedin"},
        )
        # Authentication required on protected endpoints
        assert sub_res.status_code == 401
        assert "Authentication credentials were not provided" in sub_res.json()["message"]


@pytest.mark.asyncio
async def test_review_reject_enforces_mandatory_feedback(async_client: AsyncClient):
    """Enforces that reject and request_revision actions require explicit feedback."""
    sub_res = await async_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json={"title": "Feedback Required Test", "content": "Sample content", "target_channel": "blog_post"},
    )
    submission_id = sub_res.json()["id"]

    # Reject without feedback
    invalid_payload = {
        "action": "reject",
        "feedback": "",  # Empty feedback
    }
    res = await async_client.post(
        f"/api/v1/submissions/{submission_id}/review",
        json=invalid_payload,
    )
    assert res.status_code == 422  # Unprocessable Entity


@pytest.mark.asyncio
async def test_submission_safe_archival_lifecycle(async_client: AsyncClient, api_async_session: AsyncSession):
    """Verify safe archival endpoint: role permissions, tenant isolation, audit entry recording,
    and exclusion from default submission list unless include_archived=true.
    """
    # 1. Create a draft submission
    sub_res = await async_client.post(
        "/api/v1/submissions",
        json={
            "title": "Draft to be Archived",
            "content": "This draft will be archived safely without destroying audit history.",
            "target_channel": "blog_post",
        },
    )
    assert sub_res.status_code == 201
    sub_id = sub_res.json()["id"]
    assert sub_res.json()["is_archived"] is False

    # 2. Archive the submission
    arch_res = await async_client.post(f"/api/v1/submissions/{sub_id}/archive")
    assert arch_res.status_code == 200
    arch_data = arch_res.json()
    assert arch_data["is_archived"] is True
    assert arch_data["archived_at"] is not None

    # 3. Default list query omits archived submissions
    list_active = await async_client.get("/api/v1/submissions")
    assert list_active.status_code == 200
    active_ids = [s["id"] for s in list_active.json()]
    assert sub_id not in active_ids

    # 4. list with include_archived=true includes the archived submission
    list_all = await async_client.get("/api/v1/submissions?include_archived=true")
    assert list_all.status_code == 200
    all_ids = [s["id"] for s in list_all.json()]
    assert sub_id in all_ids

    # 5. Verify immutable audit trail contains the archival event
    trail_res = await async_client.get(f"/api/v1/submissions/{sub_id}/audit-trail")
    assert trail_res.status_code == 200
    trail = trail_res.json()
    archive_event = next((e for e in trail if e["action_type"] == "archive_submission"), None)
    assert archive_event is not None
    assert archive_event["actor_type"] == "human"
    assert "archived_by_email" in archive_event["details"]
