from datetime import timedelta
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.main import app
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.submission import ContentSubmission
from app.models.user import User


@pytest_asyncio.fixture
async def multi_tenant_session():
    """Isolated async SQLite engine and session for multi-tenant isolation tests."""
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
        # Seed Baseline Demo Organization & Personas
        demo_org = Organization(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            name="BrandShield Primary Organization",
            slug="brandshield-primary",
            is_active=True,
        )
        session.add(demo_org)
        await session.flush()

        sarah = User(
            id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            organization_id=demo_org.id,
            email="sarah.jenkins@brandshield.ai",
            hashed_password=get_password_hash("ValidReviewerPass123!"),
            full_name="Sarah Jenkins (Senior Compliance Officer)",
            role="REVIEWER",
            is_active=True,
        )
        mark = User(
            id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            organization_id=demo_org.id,
            email="mark.creator@brandshield.ai",
            hashed_password=get_password_hash("ValidCreatorPass123!"),
            full_name="Mark Creator (Content Author)",
            role="CREATOR",
            is_active=True,
        )
        session.add_all([sarah, mark])
        await session.flush()
        demo_org.owner_id = sarah.id

        # Baseline guideline for demo org
        demo_gl = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=demo_org.id,
            name="BrandShield Capitalization",
            rule_type="trademark_usage",
            severity="critical",
            description="Enforces BrandShield capitalization",
            directive="Capitalize BrandShield AI properly",
            examples_approved=["BrandShield AI"],
            examples_prohibited=["brandshield"],
            tags=["trademark"],
            is_active=True,
        )
        session.add(demo_gl)
        await session.commit()

        yield session

    await test_engine.dispose()


@pytest_asyncio.fixture
async def multi_tenant_client(multi_tenant_session: AsyncSession):
    """Async HTTP client overriding get_db dependency with test session."""
    async def override_get_db():
        yield multi_tenant_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


# ==============================================================================
# Phase 1: Multi-Tenant Onboarding & Data Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_onboarding_creates_isolated_tenant_and_admin(
    multi_tenant_client: AsyncClient,
    multi_tenant_session: AsyncSession,
):
    """Verify that onboarding provisions a new organization, admin user, owner link, and starter guidelines."""
    onboard_res = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Acme Health Technologies",
            "full_name": "Dr. Aris Thorne",
            "email": "aris.thorne@acmehealth.com",
            "password": "SecurePassword123!",
        },
    )
    assert onboard_res.status_code == 201
    data = onboard_res.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"
    user_info = data["user"]
    assert user_info["email"] == "aris.thorne@acmehealth.com"
    assert user_info["full_name"] == "Dr. Aris Thorne"
    assert user_info["role"] == "ADMIN"
    assert user_info["organization_name"] == "Acme Health Technologies"

    # Verify database organization record
    org_id = uuid.UUID(user_info["organization_id"])
    user_id = uuid.UUID(user_info["id"])

    org_stmt = select(Organization).where(Organization.id == org_id)
    org = (await multi_tenant_session.execute(org_stmt)).scalar_one()
    assert org.name == "Acme Health Technologies"
    assert org.slug == "acme-health-technologies"
    assert org.owner_id == user_id

    # Verify starter brand guidelines seeded for this isolated tenant
    gl_stmt = select(BrandGuideline).where(BrandGuideline.organization_id == org_id)
    guidelines = (await multi_tenant_session.execute(gl_stmt)).scalars().all()
    assert len(guidelines) >= 3
    gl_names = [g.name for g in guidelines]
    assert any("Acme Health Technologies" in n for n in gl_names)


@pytest.mark.asyncio
async def test_onboarding_generates_unique_slug_on_collision(
    multi_tenant_client: AsyncClient,
):
    """Verify slug collision handling when two organizations register with identical names."""
    res1 = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Cyber Shield",
            "full_name": "User One",
            "email": "user1@cybershield.com",
            "password": "SecurePassword123!",
        },
    )
    assert res1.status_code == 201

    res2 = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Cyber Shield",
            "full_name": "User Two",
            "email": "user2@cybershield.com",
            "password": "SecurePassword123!",
        },
    )
    assert res2.status_code == 201
    assert res1.json()["user"]["organization_id"] != res2.json()["user"]["organization_id"]


@pytest.mark.asyncio
async def test_onboard_duplicate_email_rejected(multi_tenant_client: AsyncClient):
    """Verify that onboarding with an already registered email is rejected with 400 Bad Request."""
    await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "First Org",
            "full_name": "First User",
            "email": "duplicate@example.com",
            "password": "SecurePassword123!",
        },
    )
    dup_res = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Second Org",
            "full_name": "Second User",
            "email": "DUPLICATE@example.com",
            "password": "AnotherPassword123!",
        },
    )
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["message"]


@pytest.mark.asyncio
async def test_customer_a_cannot_retrieve_customer_b_guidelines(
    multi_tenant_client: AsyncClient,
):
    """Verify Customer A cannot view or fetch Customer B's private brand guidelines."""
    # 1. Onboard Tenant A (Alpha Corp)
    res_a = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Alpha Corp",
            "full_name": "Alice Alpha",
            "email": "alice@alphacorp.com",
            "password": "Password123!",
        },
    )
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 2. Onboard Tenant B (Beta Corp)
    res_b = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Beta Corp",
            "full_name": "Bob Beta",
            "email": "bob@betacorp.com",
            "password": "Password123!",
        },
    )
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 3. Tenant A creates custom guideline
    create_gl_res = await multi_tenant_client.post(
        "/api/v1/guidelines",
        json={
            "name": "Alpha Confidential Directive",
            "rule_type": "trademark_usage",
            "severity": "critical",
            "description": "Proprietary Alpha rule",
            "directive": "Spell Alpha properly",
            "examples_approved": ["Alpha"],
            "examples_prohibited": ["alpha"],
            "tags": ["alpha"],
            "is_active": True,
        },
        headers=headers_a,
    )
    assert create_gl_res.status_code == 201
    alpha_gl_id = create_gl_res.json()["id"]

    # 4. Tenant B lists guidelines -> Must NOT see Alpha's guideline
    b_list_res = await multi_tenant_client.get("/api/v1/guidelines", headers=headers_b)
    assert b_list_res.status_code == 200
    b_guidelines = b_list_res.json()
    assert not any(g["id"] == alpha_gl_id for g in b_guidelines)
    assert not any("Alpha Confidential" in g["name"] for g in b_guidelines)

    # 5. Tenant B attempts direct retrieval by ID -> 404 Not Found
    b_get_res = await multi_tenant_client.get(f"/api/v1/guidelines/{alpha_gl_id}", headers=headers_b)
    assert b_get_res.status_code == 404


@pytest.mark.asyncio
async def test_customer_a_cannot_retrieve_customer_b_submissions(
    multi_tenant_client: AsyncClient,
):
    """Verify Customer A cannot view, retrieve, or list Customer B's content submissions."""
    # 1. Onboard Tenant A
    res_a = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Tenant A Inc",
            "full_name": "User A",
            "email": "usera@tenanta.com",
            "password": "Password123!",
        },
    )
    headers_a = {"Authorization": f"Bearer {res_a.json()['access_token']}"}

    # 2. Onboard Tenant B
    res_b = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Tenant B Inc",
            "full_name": "User B",
            "email": "userb@tenantb.com",
            "password": "Password123!",
        },
    )
    headers_b = {"Authorization": f"Bearer {res_b.json()['access_token']}"}

    # 3. Tenant A creates content submission
    sub_res = await multi_tenant_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json={
            "title": "Confidential Product Launch A",
            "content": "Secret announcement for Tenant A.",
            "target_channel": "linkedin",
        },
        headers=headers_a,
    )
    assert sub_res.status_code == 201
    sub_a_id = sub_res.json()["id"]

    # 4. Tenant B lists submissions -> Must be completely isolated
    b_list_res = await multi_tenant_client.get("/api/v1/submissions", headers=headers_b)
    assert b_list_res.status_code == 200
    b_submissions = b_list_res.json()
    assert not any(s["id"] == sub_a_id for s in b_submissions)
    assert not any("Confidential Product Launch A" in s["title"] for s in b_submissions)

    # 5. Tenant B attempts direct get -> 404 Not Found
    b_get_res = await multi_tenant_client.get(f"/api/v1/submissions/{sub_a_id}", headers=headers_b)
    assert b_get_res.status_code == 404


@pytest.mark.asyncio
async def test_customer_a_cannot_access_customer_b_reports_or_reviews(
    multi_tenant_client: AsyncClient,
):
    """Verify Customer B cannot access Customer A's compliance reports or conduct reviews on A's submissions."""
    # 1. Onboard Tenant A and Tenant B
    res_a = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Org Alpha",
            "full_name": "Admin Alpha",
            "email": "admin@alpha.com",
            "password": "Password123!",
        },
    )
    headers_a = {"Authorization": f"Bearer {res_a.json()['access_token']}"}

    res_b = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Org Beta",
            "full_name": "Admin Beta",
            "email": "admin@beta.com",
            "password": "Password123!",
        },
    )
    headers_b = {"Authorization": f"Bearer {res_b.json()['access_token']}"}

    # 2. Tenant A creates and analyzes submission
    sub_a_res = await multi_tenant_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json={
            "title": "Alpha Social Media Copy",
            "content": "Org Alpha provides enterprise services.",
            "target_channel": "twitter_x",
        },
        headers=headers_a,
    )
    sub_a_id = sub_a_res.json()["id"]
    await multi_tenant_client.post(f"/api/v1/submissions/{sub_a_id}/analyze", headers=headers_a)

    # 3. Tenant B attempts to fetch Tenant A's report -> 404 Not Found
    rep_res = await multi_tenant_client.get(f"/api/v1/submissions/{sub_a_id}/report", headers=headers_b)
    assert rep_res.status_code == 404

    # 4. Tenant B attempts to record a review decision on Tenant A's submission -> 404 Not Found
    review_res = await multi_tenant_client.post(
        f"/api/v1/submissions/{sub_a_id}/review",
        json={"action": "approve", "feedback": "Attempted unauthorized cross-tenant approval"},
        headers=headers_b,
    )
    assert review_res.status_code == 404


@pytest.mark.asyncio
async def test_organization_identity_cannot_be_spoofed_via_headers(
    multi_tenant_client: AsyncClient,
):
    """Verify that clients cannot forge X-Organization-Id headers to access other organizations."""
    res_a = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Spoof Target A",
            "full_name": "Target User",
            "email": "target@example.com",
            "password": "Password123!",
        },
    )
    org_a_id = res_a.json()["user"]["organization_id"]

    res_b = await multi_tenant_client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Attacker B",
            "full_name": "Attacker User",
            "email": "attacker@example.com",
            "password": "Password123!",
        },
    )
    token_b = res_b.json()["access_token"]

    # Attacker uses token B with X-Organization-Id pointing to Org A
    spoof_res = await multi_tenant_client.get(
        "/api/v1/guidelines",
        headers={
            "Authorization": f"Bearer {token_b}",
            "X-Organization-Id": org_a_id,
        },
    )
    assert spoof_res.status_code == 403
    assert "Cross-tenant access forbidden" in spoof_res.json()["message"]


@pytest.mark.asyncio
async def test_existing_demo_organization_and_accounts_continue_working(
    multi_tenant_client: AsyncClient,
):
    """Verify that existing demo organization and demo accounts continue functioning with zero regression."""
    # 1. Sarah Jenkins (REVIEWER in BrandShield Primary Org)
    sarah_res = await multi_tenant_client.post(
        "/api/v1/auth/login",
        json={"email": "sarah.jenkins@brandshield.ai", "password": "ValidReviewerPass123!"},
    )
    assert sarah_res.status_code == 200
    sarah_data = sarah_res.json()
    assert sarah_data["user"]["role"] == "REVIEWER"
    assert sarah_data["user"]["organization_id"] == "11111111-1111-1111-1111-111111111111"

    # 2. Mark Creator (CREATOR in BrandShield Primary Org)
    mark_res = await multi_tenant_client.post(
        "/api/v1/auth/login",
        json={"email": "mark.creator@brandshield.ai", "password": "ValidCreatorPass123!"},
    )
    assert mark_res.status_code == 200
    mark_data = mark_res.json()
    assert mark_data["user"]["role"] == "CREATOR"
    assert mark_data["user"]["organization_id"] == "11111111-1111-1111-1111-111111111111"
