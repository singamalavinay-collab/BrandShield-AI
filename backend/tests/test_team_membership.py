import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.guideline import BrandGuideline
from app.models.invitation import TeamInvitation
from app.models.organization import Organization
from app.models.review import AuditEntry
from app.models.submission import ContentSubmission
from app.models.user import User


@pytest_asyncio.fixture
async def team_session():
    """Isolated async SQLite engine and session for team membership and audit tests."""
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
        # Organization A
        org_a = Organization(
            id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            name="Alpha Corp",
            slug="alpha-corp",
            is_active=True,
        )
        # Organization B
        org_b = Organization(
            id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            name="Beta Industries",
            slug="beta-industries",
            is_active=True,
        )
        session.add_all([org_a, org_b])
        await session.flush()

        # Users in Organization A
        admin_a = User(
            id=uuid.UUID("a1111111-1111-1111-1111-111111111111"),
            organization_id=org_a.id,
            email="admin@alphacorp.com",
            hashed_password=get_password_hash("AdminPass123!"),
            full_name="Alice Admin",
            role="ADMIN",
            is_active=True,
        )
        creator_a = User(
            id=uuid.UUID("a2222222-2222-2222-2222-222222222222"),
            organization_id=org_a.id,
            email="creator@alphacorp.com",
            hashed_password=get_password_hash("CreatorPass123!"),
            full_name="Charlie Creator",
            role="CREATOR",
            is_active=True,
        )
        reviewer_a = User(
            id=uuid.UUID("a3333333-3333-3333-3333-333333333333"),
            organization_id=org_a.id,
            email="reviewer@alphacorp.com",
            hashed_password=get_password_hash("ReviewerPass123!"),
            full_name="Rachel Reviewer",
            role="REVIEWER",
            is_active=True,
        )

        # Users in Organization B
        admin_b = User(
            id=uuid.UUID("b1111111-1111-1111-1111-111111111111"),
            organization_id=org_b.id,
            email="admin@betaindustries.com",
            hashed_password=get_password_hash("BetaAdminPass123!"),
            full_name="Bob Beta Admin",
            role="ADMIN",
            is_active=True,
        )
        session.add_all([admin_a, creator_a, reviewer_a, admin_b])
        await session.flush()

        org_a.owner_id = admin_a.id
        org_b.owner_id = admin_b.id

        # Seed test guideline for Org A
        gl_a = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            name="Alpha Corp Trademark",
            rule_type="trademark_usage",
            severity="critical",
            description="Alpha Corp capitalization standard",
            directive="Always spell Alpha Corp properly",
            examples_approved=["Alpha Corp standard"],
            examples_prohibited=["alphacorp"],
            tags=["trademark"],
            is_active=True,
        )
        session.add(gl_a)
        await session.commit()

        yield session

    await test_engine.dispose()


@pytest_asyncio.fixture
async def team_client(team_session: AsyncSession):
    """Async HTTP client overriding get_db dependency with test session."""
    async def override_get_db():
        yield team_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def make_token(user: User) -> str:
    """Helper to generate JWT bearer tokens for specified user."""
    return create_access_token(
        subject=str(user.id),
        org_id=str(user.organization_id),
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )


def get_err_msg(res) -> str:
    """Extract error detail or structured message from response."""
    body = res.json()
    return body.get("message") or body.get("detail") or ""


# ==============================================================================
# Phase 2: Team Invitations & Security Invariants
# ==============================================================================

@pytest.mark.asyncio
async def test_admin_can_invite_creator_and_reviewer(team_client: AsyncClient, team_session: AsyncSession):
    """Verify ADMIN can create invitations for CREATOR and REVIEWER roles with secure tokens."""
    admin_stmt = select(User).where(User.email == "admin@alphacorp.com")
    admin = (await team_session.execute(admin_stmt)).scalar_one()
    token = make_token(admin)

    # 1. Invite CREATOR
    res_creator = await team_client.post(
        "/api/v1/invitations",
        json={"email": "new.writer@alphacorp.com", "role": "CREATOR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_creator.status_code == 201
    data_c = res_creator.json()
    assert data_c["email"] == "new.writer@alphacorp.com"
    assert data_c["role"] == "CREATOR"
    assert data_c["status"] == "PENDING"
    assert "invitation_token" in data_c
    raw_token_c = data_c["invitation_token"]
    assert len(raw_token_c) >= 32
    assert "email_delivery_status" in data_c

    # Verify token is stored hashed in DB
    inv_stmt = select(TeamInvitation).where(TeamInvitation.id == uuid.UUID(data_c["id"]))
    inv_c = (await team_session.execute(inv_stmt)).scalar_one()
    assert inv_c.token_hash == hashlib.sha256(raw_token_c.encode("utf-8")).hexdigest()
    assert inv_c.token_hash != raw_token_c

    # 2. Invite REVIEWER
    res_reviewer = await team_client.post(
        "/api/v1/invitations",
        json={"email": "new.reviewer@alphacorp.com", "role": "REVIEWER"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_reviewer.status_code == 201
    data_r = res_reviewer.json()
    assert data_r["email"] == "new.reviewer@alphacorp.com"
    assert data_r["role"] == "REVIEWER"


@pytest.mark.asyncio
async def test_creator_cannot_invite_users(team_client: AsyncClient, team_session: AsyncSession):
    """Verify CREATOR role is forbidden from inviting team members (HTTP 403)."""
    creator_stmt = select(User).where(User.email == "creator@alphacorp.com")
    creator = (await team_session.execute(creator_stmt)).scalar_one()
    token = make_token(creator)

    res = await team_client.post(
        "/api/v1/invitations",
        json={"email": "unauthorized@alphacorp.com", "role": "CREATOR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    assert "Access denied" in get_err_msg(res)


@pytest.mark.asyncio
async def test_reviewer_cannot_invite_users(team_client: AsyncClient, team_session: AsyncSession):
    """Verify REVIEWER role is forbidden from inviting team members (HTTP 403)."""
    reviewer_stmt = select(User).where(User.email == "reviewer@alphacorp.com")
    reviewer = (await team_session.execute(reviewer_stmt)).scalar_one()
    token = make_token(reviewer)

    res = await team_client.post(
        "/api/v1/invitations",
        json={"email": "unauthorized@alphacorp.com", "role": "CREATOR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    assert "Access denied" in get_err_msg(res)


@pytest.mark.asyncio
async def test_invitation_cannot_grant_admin_privileges(team_client: AsyncClient, team_session: AsyncSession):
    """Verify invitations cannot grant ADMIN role (rejected by Pydantic and API guard)."""
    admin_stmt = select(User).where(User.email == "admin@alphacorp.com")
    admin = (await team_session.execute(admin_stmt)).scalar_one()
    token = make_token(admin)

    res = await team_client.post(
        "/api/v1/invitations",
        json={"email": "escalate@alphacorp.com", "role": "ADMIN"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code in {400, 422}


@pytest.mark.asyncio
async def test_invitation_acceptance_lifecycle(team_client: AsyncClient, team_session: AsyncSession):
    """Verify successful acceptance of an invitation and creation of new user."""
    admin_stmt = select(User).where(User.email == "admin@alphacorp.com")
    admin = (await team_session.execute(admin_stmt)).scalar_one()
    token = make_token(admin)

    # 1. Admin creates invitation
    invite_res = await team_client.post(
        "/api/v1/invitations",
        json={"email": "dave.editor@alphacorp.com", "role": "CREATOR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert invite_res.status_code == 201
    raw_token = invite_res.json()["invitation_token"]

    # 2. Validate token publicly
    val_res = await team_client.get(f"/api/v1/invitations/validate?token={raw_token}")
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["valid"] is True
    assert val_data["email"] == "dave.editor@alphacorp.com"
    assert val_data["organization_name"] == "Alpha Corp"
    assert val_data["role"] == "CREATOR"

    # 3. Accept invitation
    accept_res = await team_client.post(
        "/api/v1/invitations/accept",
        json={
            "token": raw_token,
            "full_name": "Dave Editor",
            "password": "SecurePassword123!",
        },
    )
    assert accept_res.status_code == 201
    auth_data = accept_res.json()
    assert "access_token" in auth_data
    assert auth_data["user"]["email"] == "dave.editor@alphacorp.com"
    assert auth_data["user"]["role"] == "CREATOR"
    assert auth_data["user"]["organization_name"] == "Alpha Corp"

    # 4. Verify user in database
    user_stmt = select(User).where(User.email == "dave.editor@alphacorp.com")
    new_user = (await team_session.execute(user_stmt)).scalar_one()
    assert new_user.full_name == "Dave Editor"
    assert new_user.organization_id == admin.organization_id
    assert new_user.role == "CREATOR"


@pytest.mark.asyncio
async def test_invitation_cannot_be_accepted_twice(team_client: AsyncClient, team_session: AsyncSession):
    """Verify an invitation token cannot be reused after acceptance."""
    admin_stmt = select(User).where(User.email == "admin@alphacorp.com")
    admin = (await team_session.execute(admin_stmt)).scalar_one()
    token = make_token(admin)

    invite_res = await team_client.post(
        "/api/v1/invitations",
        json={"email": "single.use@alphacorp.com", "role": "CREATOR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    raw_token = invite_res.json()["invitation_token"]

    # First acceptance
    acc1 = await team_client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token, "full_name": "First Name", "password": "Password123!"},
    )
    assert acc1.status_code == 201

    # Second acceptance attempt with same token
    acc2 = await team_client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token, "full_name": "Second Name", "password": "Password123!"},
    )
    assert acc2.status_code == 400
    assert "already been accepted" in get_err_msg(acc2)


@pytest.mark.asyncio
async def test_revoked_invitation_cannot_be_accepted(team_client: AsyncClient, team_session: AsyncSession):
    """Verify an administrator can revoke an invitation, blocking subsequent acceptance."""
    admin_stmt = select(User).where(User.email == "admin@alphacorp.com")
    admin = (await team_session.execute(admin_stmt)).scalar_one()
    token = make_token(admin)

    # 1. Create invitation
    invite_res = await team_client.post(
        "/api/v1/invitations",
        json={"email": "to.revoke@alphacorp.com", "role": "REVIEWER"},
        headers={"Authorization": f"Bearer {token}"},
    )
    inv_id = invite_res.json()["id"]
    raw_token = invite_res.json()["invitation_token"]

    # 2. Revoke invitation
    rev_res = await team_client.delete(
        f"/api/v1/invitations/{inv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["status"] == "REVOKED"

    # 3. Attempt validation
    val_res = await team_client.get(f"/api/v1/invitations/validate?token={raw_token}")
    assert val_res.status_code == 400
    assert "revoked" in get_err_msg(val_res)

    # 4. Attempt acceptance
    acc_res = await team_client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token, "full_name": "Revoked User", "password": "Password123!"},
    )
    assert acc_res.status_code == 400
    assert "revoked" in get_err_msg(acc_res)


@pytest.mark.asyncio
async def test_expired_invitation_cannot_be_accepted(team_client: AsyncClient, team_session: AsyncSession):
    """Verify expired invitations are rejected on validation and acceptance."""
    admin_stmt = select(User).where(User.email == "admin@alphacorp.com")
    admin = (await team_session.execute(admin_stmt)).scalar_one()

    # Manually seed an expired invitation
    raw_token = "expired_raw_test_token_string_12345678"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expired_inv = TeamInvitation(
        id=uuid.uuid4(),
        organization_id=admin.organization_id,
        inviter_id=admin.id,
        email="expired.user@alphacorp.com",
        role="CREATOR",
        token_hash=token_hash,
        status="PENDING",
        expires_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    team_session.add(expired_inv)
    await team_session.commit()

    # 1. Attempt validation
    val_res = await team_client.get(f"/api/v1/invitations/validate?token={raw_token}")
    assert val_res.status_code == 400
    assert "expired" in get_err_msg(val_res)

    # 2. Attempt acceptance
    acc_res = await team_client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token, "full_name": "Expired User", "password": "Password123!"},
    )
    assert acc_res.status_code == 400
    assert "expired" in get_err_msg(acc_res)


@pytest.mark.asyncio
async def test_cross_organization_invitation_isolation(team_client: AsyncClient, team_session: AsyncSession):
    """Verify Organization A cannot see or mutate Organization B's invitations."""
    admin_a_stmt = select(User).where(User.email == "admin@alphacorp.com")
    admin_a = (await team_session.execute(admin_a_stmt)).scalar_one()
    token_a = make_token(admin_a)

    admin_b_stmt = select(User).where(User.email == "admin@betaindustries.com")
    admin_b = (await team_session.execute(admin_b_stmt)).scalar_one()
    token_b = make_token(admin_b)

    # 1. Admin A creates invitation in Org A
    inv_a_res = await team_client.post(
        "/api/v1/invitations",
        json={"email": "member.a@alphacorp.com", "role": "CREATOR"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert inv_a_res.status_code == 201
    inv_a_id = inv_a_res.json()["id"]

    # 2. Admin B lists invitations: must NOT contain Org A's invitation
    list_b = await team_client.get(
        "/api/v1/invitations",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert list_b.status_code == 200
    items_b = list_b.json()
    assert not any(item["id"] == inv_a_id for item in items_b)

    # 3. Admin B attempts to revoke Org A's invitation: must return 404
    revoke_b = await team_client.delete(
        f"/api/v1/invitations/{inv_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert revoke_b.status_code == 404
    assert "not found in your organization" in get_err_msg(revoke_b)


# ==============================================================================
# Phase 2: Audit Identity Hardening Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_audit_records_bind_authenticated_user_identity(team_client: AsyncClient, team_session: AsyncSession):
    """Verify that submission, inspection, and review audit entries record the verified user."""
    creator_stmt = select(User).where(User.email == "creator@alphacorp.com")
    creator = (await team_session.execute(creator_stmt)).scalar_one()
    creator_token = make_token(creator)

    reviewer_stmt = select(User).where(User.email == "reviewer@alphacorp.com")
    reviewer = (await team_session.execute(reviewer_stmt)).scalar_one()
    reviewer_token = make_token(reviewer)

    # 1. Creator creates a draft submission
    sub_res = await team_client.post(
        "/api/v1/submissions",
        json={
            "title": "Alpha Product Launch Press Release",
            "content": "Alpha Corp has officially unveiled its new autonomous governance platform.",
            "target_channel": "press_release",
            "target_audience": "Enterprise Partners",
        },
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert sub_res.status_code == 201
    sub_id = sub_res.json()["id"]

    # Verify audit entry for creation
    audit_stmt = (
        select(AuditEntry)
        .where(AuditEntry.submission_id == uuid.UUID(sub_id), AuditEntry.action_type == "create_draft")
    )
    audit_create = (await team_session.execute(audit_stmt)).scalar_one()
    assert audit_create.actor_id == str(creator.id)
    assert audit_create.actor_name == creator.full_name
    assert audit_create.actor_type == "human"
    assert audit_create.organization_id == creator.organization_id

    # 2. Creator submits draft for inspection
    submit_res = await team_client.post(
        f"/api/v1/submissions/{sub_id}/submit",
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert submit_res.status_code == 200

    audit_sub_stmt = (
        select(AuditEntry)
        .where(AuditEntry.submission_id == uuid.UUID(sub_id), AuditEntry.action_type == "submit_content")
    )
    audit_submit = (await team_session.execute(audit_sub_stmt)).scalar_one()
    assert audit_submit.actor_id == str(creator.id)
    assert audit_submit.actor_name == creator.full_name
    assert audit_submit.actor_type == "human"

    # 3. Run compliance analysis
    analyze_res = await team_client.post(
        f"/api/v1/submissions/{sub_id}/analyze",
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert analyze_res.status_code == 200

    audit_an_stmt = (
        select(AuditEntry)
        .where(AuditEntry.submission_id == uuid.UUID(sub_id), AuditEntry.action_type == "automated_compliance_inspection")
    )
    audit_an = (await team_session.execute(audit_an_stmt)).scalar_one()
    assert audit_an.actor_id == str(creator.id)
    assert audit_an.actor_name == creator.full_name
    assert audit_an.actor_type == "human"

    # 4. Advance to human review
    advance_res = await team_client.post(
        f"/api/v1/submissions/{sub_id}/advance-to-review",
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert advance_res.status_code == 200

    # 5. Reviewer approves submission
    review_res = await team_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve", "feedback": "Approved as strictly compliant."},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert review_res.status_code == 200

    # 6. Retrieve full audit trail via new API endpoint
    trail_res = await team_client.get(
        f"/api/v1/submissions/{sub_id}/audit-trail",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert trail_res.status_code == 200
    trail = trail_res.json()
    assert len(trail) >= 4

    # Verify review audit entry in the trail
    review_entry = next(e for e in trail if e["action_type"] == "human_review_approve")
    assert review_entry["actor_id"] == str(reviewer.id)
    assert review_entry["actor_name"] == reviewer.full_name
    assert review_entry["actor_type"] == "human"
    assert review_entry["organization_id"] == str(reviewer.organization_id)


@pytest.mark.asyncio
async def test_concurrent_invitation_acceptance_race_condition(tmp_path):
    """Verify that multiple concurrent requests attempting to accept the exact same invitation
    result in exactly ONE successful account creation, while all competing requests receive clean HTTP 400.
    """
    db_file = tmp_path / "concurrent_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode = WAL;")
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON;")
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    async with session_factory() as s:
        org = Organization(id=org_id, name="Concurrent Org", slug="concurrent-org", is_active=True)
        admin = User(
            id=admin_id,
            organization_id=org.id,
            email="admin@concurrent.com",
            hashed_password=get_password_hash("AdminPass123!"),
            full_name="Alice Admin",
            role="ADMIN",
            is_active=True,
        )
        s.add_all([org, admin])
        await s.commit()

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = create_access_token(
            subject=str(admin_id),
            org_id=str(org_id),
            role="ADMIN",
            email="admin@concurrent.com",
            full_name="Alice Admin",
        )

        # 1. Admin creates invitation
        invite_res = await client.post(
            "/api/v1/invitations",
            json={"email": "parallel.invitee@concurrent.com", "role": "CREATOR"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert invite_res.status_code == 201
        raw_token = invite_res.json()["invitation_token"]

        # 2. Fire 5 simultaneous requests attempting to accept the same token
        async def accept_attempt(index: int):
            return await client.post(
                "/api/v1/invitations/accept",
                json={
                    "token": raw_token,
                    "full_name": f"Concurrent User {index}",
                    "password": "SecurePassword123!",
                },
            )

        responses = await asyncio.gather(*(accept_attempt(i) for i in range(5)))
        status_codes = [r.status_code for r in responses]

        # 3. Exactly one succeeds with 201 Created; all others receive 400 Bad Request
        success_count = sum(1 for c in status_codes if c == 201)
        rejected_count = sum(1 for c in status_codes if c == 400)
        assert success_count == 1
        assert rejected_count == 4

        # 4. Confirm in the database that exactly one user was created
        async with session_factory() as verify_session:
            users_stmt = select(User).where(User.email == "parallel.invitee@concurrent.com")
            created_users = (await verify_session.execute(users_stmt)).scalars().all()
            assert len(created_users) == 1
            assert created_users[0].organization_id == org_id
            assert created_users[0].role == "CREATOR"

            # Verify invitation is marked ACCEPTED
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            inv_stmt = select(TeamInvitation).where(TeamInvitation.token_hash == token_hash)
            inv = (await verify_session.execute(inv_stmt)).scalar_one()
            assert inv.status == "ACCEPTED"
            assert inv.accepted_at is not None

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_cross_tenant_guideline_isolation(team_client: AsyncClient, team_session: AsyncSession):
    """Verify Organization B users cannot read or modify Organization A guidelines, and forged headers fail."""
    admin_a_stmt = select(User).where(User.email == "admin@alphacorp.com")
    admin_a = (await team_session.execute(admin_a_stmt)).scalar_one()
    token_a = make_token(admin_a)

    admin_b_stmt = select(User).where(User.email == "admin@betaindustries.com")
    admin_b = (await team_session.execute(admin_b_stmt)).scalar_one()
    token_b = make_token(admin_b)

    # Fetch guideline gl_a belonging to Org A
    gl_stmt = select(BrandGuideline).where(BrandGuideline.name == "Alpha Corp Trademark")
    gl_a = (await team_session.execute(gl_stmt)).scalar_one()
    gl_a_id = str(gl_a.id)

    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Admin B cannot retrieve Guideline A (404 Not Found in Org B's tenant)
    res_get = await team_client.get(f"/api/v1/guidelines/{gl_a_id}", headers=headers_b)
    assert res_get.status_code == 404

    # 2. Admin B cannot update Guideline A (404 Not Found)
    res_patch = await team_client.patch(
        f"/api/v1/guidelines/{gl_a_id}",
        json={"description": "Cross-tenant unauthorized alteration attempt"},
        headers=headers_b,
    )
    assert res_patch.status_code == 404

    # 3. Admin B cannot toggle active status of Guideline A (404 Not Found)
    res_toggle = await team_client.patch(
        f"/api/v1/guidelines/{gl_a_id}/toggle-active",
        headers=headers_b,
    )
    assert res_toggle.status_code == 404

    # 4. Admin B listing guidelines must not see Guideline A
    res_list = await team_client.get("/api/v1/guidelines", headers=headers_b)
    assert res_list.status_code == 200
    b_guidelines = res_list.json()
    assert not any(g["id"] == gl_a_id for g in b_guidelines)
    assert not any("Alpha Corp" in g["name"] for g in b_guidelines)

    # 5. Admin B attempting to supply X-Organization-Id for Org A is rejected with 403 Forbidden
    forged_headers = {
        "Authorization": f"Bearer {token_b}",
        "X-Organization-Id": str(admin_a.organization_id),
    }
    res_forged = await team_client.get(f"/api/v1/guidelines/{gl_a_id}", headers=forged_headers)
    assert res_forged.status_code == 403
    assert "Cross-tenant access forbidden" in get_err_msg(res_forged)

    # 6. Admin A can legitimately read and mutate Guideline A
    headers_a = {"Authorization": f"Bearer {token_a}"}
    res_legit_get = await team_client.get(f"/api/v1/guidelines/{gl_a_id}", headers=headers_a)
    assert res_legit_get.status_code == 200
    assert res_legit_get.json()["name"] == "Alpha Corp Trademark"
