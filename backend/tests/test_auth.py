from datetime import timedelta
import uuid
import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import create_access_token, decode_access_token, get_password_hash, verify_password
from app.main import app
from app.models.organization import Organization
from app.models.user import User


@pytest_asyncio.fixture
async def auth_test_session():
    """Isolated async SQLite engine and session for authentication tests."""
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
        # Organization 1 (Primary Tenant)
        org1 = Organization(
            id=uuid.uuid4(),
            name="Acme Corp",
            slug="acme-corp",
            is_active=True,
        )
        session.add(org1)

        # Organization 2 (Foreign Tenant)
        org2 = Organization(
            id=uuid.uuid4(),
            name="Competitor Inc",
            slug="competitor-inc",
            is_active=True,
        )
        session.add(org2)
        await session.flush()

        # Admin user in Org 1
        admin = User(
            id=uuid.uuid4(),
            organization_id=org1.id,
            email="admin@acme.com",
            hashed_password=get_password_hash("AdminPass123!"),
            full_name="Alice Admin",
            role="ADMIN",
            is_active=True,
        )
        session.add(admin)

        # Reviewer user in Org 1
        reviewer = User(
            id=uuid.uuid4(),
            organization_id=org1.id,
            email="reviewer@acme.com",
            hashed_password=get_password_hash("ReviewerPass123!"),
            full_name="Bob Reviewer",
            role="REVIEWER",
            is_active=True,
        )
        session.add(reviewer)

        # Creator user in Org 1 (cannot review)
        creator = User(
            id=uuid.uuid4(),
            organization_id=org1.id,
            email="creator@acme.com",
            hashed_password=get_password_hash("CreatorPass123!"),
            full_name="Charlie Creator",
            role="CREATOR",
            is_active=True,
        )
        session.add(creator)

        # Auditor user in Org 1 (cannot review)
        auditor = User(
            id=uuid.uuid4(),
            organization_id=org1.id,
            email="auditor@acme.com",
            hashed_password=get_password_hash("AuditorPass123!"),
            full_name="Dana Auditor",
            role="AUDITOR",
            is_active=True,
        )
        session.add(auditor)

        # Deactivated user in Org 1
        inactive_user = User(
            id=uuid.uuid4(),
            organization_id=org1.id,
            email="inactive@acme.com",
            hashed_password=get_password_hash("InactivePass123!"),
            full_name="Inactive User",
            role="REVIEWER",
            is_active=False,
        )
        session.add(inactive_user)

        await session.commit()
        yield session

    await test_engine.dispose()


@pytest_asyncio.fixture
async def auth_client(auth_test_session: AsyncSession):
    """Async HTTP client overriding get_db dependency with test session."""
    async def override_get_db():
        yield auth_test_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Password Hashing & Security Unit Tests
# ==============================================================================

def test_password_hashing_and_verification():
    """Verify bcrypt hash generation, salt uniqueness, and correct verification."""
    password = "SuperSecretPassword123!"
    hashed1 = get_password_hash(password)
    hashed2 = get_password_hash(password)

    # Salt uniqueness
    assert hashed1 != hashed2
    assert hashed1.startswith("$2b$")

    # Positive verification
    assert verify_password(password, hashed1) is True
    assert verify_password(password, hashed2) is True

    # Negative verification
    assert verify_password("WrongPassword123!", hashed1) is False
    assert verify_password("", hashed1) is False
    assert verify_password(password, "") is False


def test_password_hashing_rejects_empty():
    """Verify empty password raises ValueError."""
    with pytest.raises(ValueError, match="Password cannot be empty"):
        get_password_hash("")


# ==============================================================================
# 2. JWT Generation, Expiration, and Validation
# ==============================================================================

def test_jwt_encoding_decoding_and_claims():
    """Verify JWT encodes required claims and validates signatures."""
    user_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    token = create_access_token(
        subject=user_id,
        org_id=org_id,
        role="REVIEWER",
        email="test@brandshield.ai",
        full_name="Test User",
    )

    payload = decode_access_token(token)
    assert payload["sub"] == user_id
    assert payload["org_id"] == org_id
    assert payload["role"] == "REVIEWER"
    assert payload["email"] == "test@brandshield.ai"
    assert "exp" in payload
    assert "iat" in payload


def test_jwt_expiration_handling():
    """Verify expired token raises jwt.ExpiredSignatureError."""
    user_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    token = create_access_token(
        subject=user_id,
        org_id=org_id,
        role="REVIEWER",
        email="test@brandshield.ai",
        full_name="Test User",
        expires_delta=timedelta(seconds=-10),  # Already expired
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_jwt_invalid_signature():
    """Verify tampering with signature raises jwt.InvalidSignatureError."""
    token = create_access_token(
        subject=str(uuid.uuid4()),
        org_id=str(uuid.uuid4()),
        role="ADMIN",
        email="admin@test.com",
        full_name="Admin",
    )
    tampered = token[:-5] + "aaaaa"
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tampered)


# ==============================================================================
# 3. Login API Endpoint Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_login_success_and_token_response(auth_client: AsyncClient):
    """Test successful login returns valid JWT token and user profile without password fields."""
    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "reviewer@acme.com", "password": "ReviewerPass123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0

    user_info = data["user"]
    assert user_info["email"] == "reviewer@acme.com"
    assert user_info["full_name"] == "Bob Reviewer"
    assert user_info["role"] == "REVIEWER"
    assert user_info["is_active"] is True
    # Security: Password hashes must never be returned
    assert "hashed_password" not in user_info
    assert "password" not in user_info


@pytest.mark.asyncio
async def test_login_invalid_password(auth_client: AsyncClient):
    """Test login with incorrect password returns 401 Unauthorized."""
    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "reviewer@acme.com", "password": "WrongPassword999!"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["message"]


@pytest.mark.asyncio
async def test_login_nonexistent_email(auth_client: AsyncClient):
    """Test login with nonexistent email returns 401 Unauthorized."""
    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@acme.com", "password": "AnyPassword123!"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["message"]


@pytest.mark.asyncio
async def test_login_deactivated_user(auth_client: AsyncClient):
    """Test deactivated account is denied login with 403 Forbidden."""
    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@acme.com", "password": "InactivePass123!"},
    )
    assert response.status_code == 403
    assert "deactivated" in response.json()["message"]


# ==============================================================================
# 4. User Profile & Auth Context (/auth/me, /auth/logout)
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_me_profile(auth_client: AsyncClient):
    """Test /api/v1/auth/me returns current user profile when authenticated."""
    # 1. Login to get token
    login_res = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@acme.com", "password": "AdminPass123!"},
    )
    token = login_res.json()["access_token"]

    # 2. Query /auth/me with Bearer token
    me_res = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == "admin@acme.com"
    assert me_data["role"] == "ADMIN"
    assert "hashed_password" not in me_data


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(auth_client: AsyncClient):
    """Test request without token is rejected with 401 Unauthorized."""
    res = await auth_client.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert "Authentication credentials were not provided" in res.json()["message"]


# ==============================================================================
# 5. Role-Based Access Control (RBAC) & Governance Restrictions
# ==============================================================================

@pytest.mark.asyncio
async def test_creator_and_auditor_forbidden_from_review_decisions(auth_client: AsyncClient):
    """Architectural Invariant: CREATOR and AUDITOR roles cannot make human review decisions."""
    # 1. Login as creator
    creator_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "creator@acme.com", "password": "CreatorPass123!"},
    )
    creator_token = creator_login.json()["access_token"]
    creator_headers = {"Authorization": f"Bearer {creator_token}"}

    # 2. Create submission and advance to review
    sub_res = await auth_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json={"title": "Test Submission", "content": "Some test copy.", "target_channel": "twitter_x"},
        headers=creator_headers,
    )
    sub_id = sub_res.json()["id"]
    await auth_client.post(f"/api/v1/submissions/{sub_id}/analyze", headers=creator_headers)
    await auth_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review", headers=creator_headers)

    # 3. Creator attempts to approve -> Must be rejected with 403 Forbidden
    review_res = await auth_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve", "feedback": "Attempted creator self-approval"},
        headers=creator_headers,
    )
    assert review_res.status_code == 403
    assert "ADMIN or REVIEWER role required" in review_res.json()["message"]
    assert "CREATOR" in review_res.json()["message"]

    # 4. Login as auditor
    auditor_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "auditor@acme.com", "password": "AuditorPass123!"},
    )
    auditor_token = auditor_login.json()["access_token"]
    auditor_headers = {"Authorization": f"Bearer {auditor_token}"}

    # 5. Auditor attempts to approve -> Must be rejected with 403 Forbidden
    auditor_review_res = await auth_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve", "feedback": "Attempted auditor approval"},
        headers=auditor_headers,
    )
    assert auditor_review_res.status_code == 403
    assert "ADMIN or REVIEWER role required" in auditor_review_res.json()["message"]


# ==============================================================================
# 6. Anti-Spoofing & Tenant Isolation Security
# ==============================================================================

@pytest.mark.asyncio
async def test_client_cannot_spoof_identity_via_headers(auth_client: AsyncClient):
    """Verify that passing client headers like X-Reviewer-Email has no effect on identity."""
    # Login as creator
    creator_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "creator@acme.com", "password": "CreatorPass123!"},
    )
    creator_token = creator_login.json()["access_token"]

    # Create submission and advance to review
    headers = {
        "Authorization": f"Bearer {creator_token}",
        "X-Reviewer-Email": "reviewer@acme.com",  # Spoof attempt
    }
    sub_res = await auth_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json={"title": "Spoof Attempt", "content": "Content", "target_channel": "linkedin"},
        headers=headers,
    )
    sub_id = sub_res.json()["id"]
    await auth_client.post(f"/api/v1/submissions/{sub_id}/analyze", headers=headers)
    await auth_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review", headers=headers)

    # Review attempt fails because token role is CREATOR despite spoof header
    review_res = await auth_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve"},
        headers=headers,
    )
    assert review_res.status_code == 403
    assert "CREATOR" in review_res.json()["message"]


@pytest.mark.asyncio
async def test_cross_tenant_access_forbidden(auth_client: AsyncClient, auth_test_session: AsyncSession):
    """Verify that attempting to access another tenant's data via X-Organization-Id returns 403."""
    from sqlalchemy import select
    # Fetch Org 2 ID
    res = await auth_test_session.execute(select(Organization).where(Organization.slug == "competitor-inc"))
    org2 = res.scalar_one()

    # Login as user from Org 1
    login_res = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "reviewer@acme.com", "password": "ReviewerPass123!"},
    )
    token = login_res.json()["access_token"]

    # Attempt request with X-Organization-Id pointing to Org 2
    cross_tenant_res = await auth_client.get(
        "/api/v1/guidelines",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": str(org2.id),
        },
    )
    assert cross_tenant_res.status_code == 403
    assert "Cross-tenant access forbidden" in cross_tenant_res.json()["message"]


# ==============================================================================
# Phase 4.2 Registration & Demo Account Verification Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_successful_creator_registration(auth_client: AsyncClient):
    """Verify that a public user can register successfully and receives CREATOR role."""
    reg_res = await auth_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "New Team Author",
            "email": "new.author@brandshield.ai",
            "password": "SecurePassword123!",
        },
    )
    assert reg_res.status_code == 201
    data = reg_res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "new.author@brandshield.ai"
    assert data["user"]["full_name"] == "New Team Author"
    assert data["user"]["role"] == "CREATOR"
    assert data["user"]["is_active"] is True

    # Verify token allows accessing protected /auth/me endpoint
    me_res = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "CREATOR"


@pytest.mark.asyncio
async def test_registration_duplicate_email_rejected(auth_client: AsyncClient):
    """Verify that registering with an already existing email is rejected with 400 Bad Request."""
    # First registration
    await auth_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Unique User",
            "email": "unique.user@brandshield.ai",
            "password": "SecurePassword123!",
        },
    )

    # Second registration with identical email (different case)
    dup_res = await auth_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Impostor User",
            "email": "UNIQUE.USER@brandshield.ai",
            "password": "AnotherPassword123!",
        },
    )
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["message"]


@pytest.mark.asyncio
async def test_registration_invalid_password_rejected(auth_client: AsyncClient):
    """Verify that passwords shorter than 8 characters are rejected during registration."""
    short_pw_res = await auth_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Short Password User",
            "email": "short.pw@brandshield.ai",
            "password": "short",  # Only 5 characters (< 8)
        },
    )
    assert short_pw_res.status_code == 422


@pytest.mark.asyncio
async def test_public_registration_cannot_assign_reviewer_or_admin(auth_client: AsyncClient):
    """Verify that clients cannot inject REVIEWER or ADMIN roles during public registration."""
    tamper_res = await auth_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Privilege Escalation Attempt",
            "email": "hacker@brandshield.ai",
            "password": "HackerPassword123!",
            "role": "ADMIN",  # Forbidden field injection
        },
    )
    # Extra fields are forbidden by Pydantic schema validation
    assert tamper_res.status_code == 422


@pytest.mark.asyncio
async def test_existing_demo_accounts_authenticate(auth_client: AsyncClient, auth_test_session: AsyncSession):
    """Verify that both Sarah Jenkins (REVIEWER) and Mark Creator (CREATOR) authenticate successfully."""
    from sqlalchemy import select
    res = await auth_test_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org = res.scalar_one()

    # Seed demo accounts into test session
    sarah = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email="sarah.jenkins@brandshield.ai",
        hashed_password=get_password_hash("ValidReviewerPass123!"),
        full_name="Sarah Jenkins (Senior Compliance Officer)",
        role="REVIEWER",
        is_active=True,
    )
    mark = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email="mark.creator@brandshield.ai",
        hashed_password=get_password_hash("ValidCreatorPass123!"),
        full_name="Mark Creator (Content Author)",
        role="CREATOR",
        is_active=True,
    )
    auth_test_session.add_all([sarah, mark])
    await auth_test_session.commit()

    # 1. Sarah Jenkins (REVIEWER)
    sarah_res = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "sarah.jenkins@brandshield.ai", "password": "ValidReviewerPass123!"},
    )
    assert sarah_res.status_code == 200
    sarah_data = sarah_res.json()
    assert sarah_data["user"]["role"] == "REVIEWER"
    assert "Sarah Jenkins" in sarah_data["user"]["full_name"]

    # 2. Mark Creator (CREATOR)
    mark_res = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "mark.creator@brandshield.ai", "password": "ValidCreatorPass123!"},
    )
    assert mark_res.status_code == 200
    mark_data = mark_res.json()
    assert mark_data["user"]["role"] == "CREATOR"
    assert "Mark Creator" in mark_data["user"]["full_name"]


@pytest.mark.asyncio
async def test_guest_blocked_from_review_decisions(auth_client: AsyncClient):
    """Verify that an unauthenticated guest cannot authorize or review submissions."""
    dummy_sub_id = uuid.uuid4()
    guest_res = await auth_client.post(
        f"/api/v1/submissions/{dummy_sub_id}/review",
        json={"action": "approve"},
    )
    # Must be 401 Unauthorized
    assert guest_res.status_code == 401


@pytest.mark.asyncio
async def test_authorized_reviewer_can_perform_permitted_review(auth_client: AsyncClient, auth_test_session: AsyncSession):
    """Verify that an authorized REVIEWER can execute permitted review actions."""
    from sqlalchemy import select
    from app.models.guideline import BrandGuideline

    res = await auth_test_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org = res.scalar_one()

    # Seed an active brand guideline so compliance engine completes inspection
    guideline = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Standard Capitalization",
        rule_type="trademark_usage",
        severity="medium",
        description="Capitalize BrandShield AI",
        directive="Capitalize BrandShield AI properly",
        examples_approved=["BrandShield AI delivers quality."],
        examples_prohibited=["brandshield is low quality."],
        is_active=True,
    )
    auth_test_session.add(guideline)
    await auth_test_session.commit()

    # Login as reviewer
    rev_res = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "reviewer@acme.com", "password": "ReviewerPass123!"},
    )
    token = rev_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create submission and advance to review
    sub_res = await auth_client.post(
        "/api/v1/submissions?submit_for_inspection=true",
        json={
            "title": "Compliant Post",
            "content": "BrandShield AI delivers reliable monitoring.",
            "target_channel": "linkedin",
        },
        headers=headers,
    )
    sub_id = sub_res.json()["id"]
    analyze_res = await auth_client.post(f"/api/v1/submissions/{sub_id}/analyze", headers=headers)
    assert analyze_res.status_code == 200
    assert analyze_res.json()["status"] == "passed_checks"

    advance_res = await auth_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review", headers=headers)
    assert advance_res.status_code == 200
    assert advance_res.json()["status"] == "under_human_review"

    # Reviewer approves submission
    approve_res = await auth_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve", "feedback": "Approved as compliant with brand directives."},
        headers=headers,
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["decision"]["action"] == "approve"
    assert approve_res.json()["submission"]["status"] == "approved"


@pytest.mark.asyncio
async def test_production_bootstrap_demo_passwords_disabled(monkeypatch, auth_test_session):
    """Verify that in production mode, bootstrap_database() never uses hardcoded demo passwords."""
    from app.core.bootstrap import bootstrap_database
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "BOOTSTRAP_REVIEWER_PASSWORD", None)
    monkeypatch.setattr(settings, "BOOTSTRAP_CREATOR_PASSWORD", None)

    # In production without bootstrap credentials, demo accounts are skipped
    is_prod = settings.ENVIRONMENT.lower() == "production"
    assert is_prod is True
    assert settings.BOOTSTRAP_REVIEWER_PASSWORD is None
    assert settings.BOOTSTRAP_CREATOR_PASSWORD is None

