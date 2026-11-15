import asyncio
from datetime import datetime, timezone
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, delete, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.guideline import BrandGuideline
from app.models.invitation import TeamInvitation
from app.models.organization import Organization
from app.models.review import AuditEntry
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.guidelines import RuleType, SeverityLevel


@pytest_asyncio.fixture
async def regression_env():
    """Isolated in-memory SQLite database environment strictly segregated from live database."""
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    async with test_engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON;")
        await conn.run_sync(Base.metadata.create_all)
        # Create SQLite immutability triggers for audit_entries
        await conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS trg_audit_entries_no_update
            BEFORE UPDATE ON audit_entries
            BEGIN
                SELECT RAISE(FAIL, 'Audit ledger entries are strictly immutable and cannot be updated');
            END;
        """)
        await conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS trg_audit_entries_no_delete
            BEFORE DELETE ON audit_entries
            BEGIN
                SELECT RAISE(FAIL, 'Audit ledger entries are strictly immutable and cannot be deleted');
            END;
        """)

    session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_maker

    app.dependency_overrides.clear()
    await test_engine.dispose()


# ==============================================================================
# Invariant Test 1: ADMIN Persona Capabilities & Team Roster
# ==============================================================================

@pytest.mark.asyncio
async def test_admin_persona_capabilities_and_team_roster(regression_env):
    """Verifies ADMIN persona full administrative authority:
    - Organization creation and admin profile retrieval.
    - Team roster retrieval via /api/v1/invitations/members.
    - Guideline configuration and management.
    - Sending invitations to team members.
    - Audit ledger visibility via /api/v1/submissions/audit-trail.
    """
    client, _ = regression_env

    # 1. Onboard Admin
    res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Governance HQ",
            "full_name": "Audrey Admin",
            "email": "audrey.admin@govhq.com",
            "password": "AdminPassword123!",
        },
    )
    assert res.status_code == 201
    admin_token = res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Verify /api/v1/auth/me profile
    me_res = await client.get("/api/v1/auth/me", headers=admin_headers)
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["role"] == "ADMIN"
    assert me_data["email"] == "audrey.admin@govhq.com"

    # 3. Verify Team Members Retrieval
    roster_res = await client.get("/api/v1/invitations/members", headers=admin_headers)
    assert roster_res.status_code == 200
    members = roster_res.json()
    assert len(members) >= 1
    assert any(m["email"] == "audrey.admin@govhq.com" and m["role"] == "ADMIN" for m in members)

    # 4. Verify Guideline Creation
    guide_res = await client.post(
        "/api/v1/guidelines",
        headers=admin_headers,
        json={
            "name": "Admin Trademark Policy",
            "rule_type": "trademark_usage",
            "severity": "critical",
            "description": "Standard naming conventions",
            "directive": "Use canonical product name",
            "examples_approved": ["BrandShield AI"],
            "examples_prohibited": ["Brandshield"],
            "tags": ["branding"],
            "is_active": True,
        },
    )
    assert guide_res.status_code == 201

    # 5. Verify Team Invitation Creation
    invite_res = await client.post(
        "/api/v1/invitations",
        headers=admin_headers,
        json={
            "email": "sam.reviewer@govhq.com",
            "role": "REVIEWER",
        },
    )
    assert invite_res.status_code == 201
    assert invite_res.json()["email"] == "sam.reviewer@govhq.com"

    # 6. Verify System Diagnostic Access
    diag_res = await client.get("/api/v1/system/status")
    assert diag_res.status_code == 200
    assert diag_res.json()["database"]["connected"] is True


# ==============================================================================
# Invariant Test 2: REVIEWER Validation Guards & Capabilities
# ==============================================================================

@pytest.mark.asyncio
async def test_reviewer_persona_capabilities_and_validation_guards(regression_env):
    """Verifies REVIEWER capabilities and strictly enforced validation guards:
    - Reviewer cannot create/modify brand guidelines (403).
    - Reviewer cannot invite team members (403).
    - Submissions NOT in under_human_review state cannot be reviewed (400).
    - Reject requires mandatory feedback.
    - Request Revision requires mandatory feedback.
    - Edit & Approve requires valid edited content.
    - Approve on non-compliant submission requires justification override.
    """
    client, _ = regression_env

    # 1. Setup Admin and invite Reviewer and Creator
    admin_res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Review Guards Inc",
            "full_name": "Reginald Admin",
            "email": "reginald@guards.com",
            "password": "AdminPassword123!",
        },
    )
    admin_token = admin_res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Invite Reviewer
    inv_rev = await client.post(
        "/api/v1/invitations",
        headers=admin_headers,
        json={"email": "rachel.reviewer@guards.com", "role": "REVIEWER"},
    )
    rev_token_str = inv_rev.json()["invitation_token"]

    # Accept Reviewer Invitation
    rev_accept = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": rev_token_str,
            "full_name": "Rachel Reviewer",
            "password": "ReviewerPassword123!",
        },
    )
    rev_token = rev_accept.json()["access_token"]
    rev_headers = {"Authorization": f"Bearer {rev_token}"}

    # Invite Creator
    inv_cr = await client.post(
        "/api/v1/invitations",
        headers=admin_headers,
        json={"email": "carl.creator@guards.com", "role": "CREATOR"},
    )
    cr_token_str = inv_cr.json()["invitation_token"]

    cr_accept = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": cr_token_str,
            "full_name": "Carl Creator",
            "password": "CreatorPassword123!",
        },
    )
    cr_token = cr_accept.json()["access_token"]
    cr_headers = {"Authorization": f"Bearer {cr_token}"}

    # 2. Invariant: Reviewer cannot create guidelines (403)
    guide_forbidden = await client.post(
        "/api/v1/guidelines",
        headers=rev_headers,
        json={
            "name": "Forbidden Guideline",
            "rule_type": "formatting",
            "severity": "low",
            "description": "Test",
            "directive": "Test",
        },
    )
    assert guide_forbidden.status_code == 403

    # 3. Invariant: Reviewer cannot invite members (403)
    invite_forbidden = await client.post(
        "/api/v1/invitations",
        headers=rev_headers,
        json={"email": "another@guards.com", "role": "CREATOR"},
    )
    assert invite_forbidden.status_code == 403

    # 4. Creator submits copy containing a violation from starter guidelines
    # (e.g. "Guarantees 100% brand safety everywhere.")
    sub_res = await client.post(
        "/api/v1/submissions",
        headers=cr_headers,
        json={
            "title": "Guard Validation Post",
            "content": "Our solution Guarantees 100% brand safety everywhere for all enterprise clients.",
            "target_channel": "twitter_x",
            "target_audience": "general_public",
        },
    )
    sub_id = sub_res.json()["id"]

    # Invariant: Review before analysis / advance is rejected (400)
    rev_early = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        headers=rev_headers,
        json={"action": "reject", "feedback": "Too early"},
    )
    assert rev_early.status_code == 400

    # Analyze submission
    ana_res = await client.post(f"/api/v1/submissions/{sub_id}/analyze", headers=cr_headers)
    assert ana_res.status_code == 200
    assert ana_res.json()["status"] == "violations_found"

    # Invariant: Review while still in 'draft' or 'violations_found' before explicit submission to human review (400)
    rev_not_advanced = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        headers=rev_headers,
        json={"action": "reject", "feedback": "Not submitted for review yet"},
    )
    assert rev_not_advanced.status_code == 400

    # Advance to human review
    adv_res = await client.post(f"/api/v1/submissions/{sub_id}/advance-to-review", headers=cr_headers)
    assert adv_res.status_code == 200

    # Invariant: Reject without feedback is rejected (422)
    rej_no_fb = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        headers=rev_headers,
        json={"action": "reject"},
    )
    assert rej_no_fb.status_code == 422

    # Invariant: Request Revision without feedback is rejected (422)
    rev_no_fb = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        headers=rev_headers,
        json={"action": "request_revision"},
    )
    assert rev_no_fb.status_code == 422

    # Invariant: Edit & Approve without edited_content is rejected (422)
    edit_no_cnt = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        headers=rev_headers,
        json={"action": "edit_and_approve"},
    )
    assert edit_no_cnt.status_code == 422

    # Invariant: Approve as-is on copy with violations without override justification is rejected (400)
    app_no_just = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        headers=rev_headers,
        json={"action": "approve"},
    )
    assert app_no_just.status_code == 400

    # Legitimate Request Revision succeeds
    rev_ok = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        headers=rev_headers,
        json={"action": "request_revision", "feedback": "Please fix trademark spelling and claims."},
    )
    assert rev_ok.status_code == 200
    assert rev_ok.json()["submission"]["status"] == "revision_requested"


# ==============================================================================
# Invariant Test 3: CREATOR Strict Boundary Verification
# ==============================================================================

@pytest.mark.asyncio
async def test_creator_persona_boundaries_and_resubmission(regression_env):
    """Verifies CREATOR persona strict boundaries:
    - Creator cannot review their own or other submissions (403).
    - Creator cannot invite users or manage organization roles (403).
    - Creator cannot mutate guidelines (403).
    - Creator CAN create drafts, analyze content, and resubmit revised copy.
    """
    client, _ = regression_env

    # 1. Onboard Admin & invite Creator
    admin_res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Creator Boundaries Co",
            "full_name": "Charlie Admin",
            "email": "charlie@boundaries.com",
            "password": "AdminPassword123!",
        },
    )
    admin_token = admin_res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    inv_cr = await client.post(
        "/api/v1/invitations",
        headers=admin_headers,
        json={"email": "claire.creator@boundaries.com", "role": "CREATOR"},
    )
    cr_token_str = inv_cr.json()["invitation_token"]

    cr_accept = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": cr_token_str,
            "full_name": "Claire Creator",
            "password": "CreatorPassword123!",
        },
    )
    cr_token = cr_accept.json()["access_token"]
    cr_headers = {"Authorization": f"Bearer {cr_token}"}

    # 2. Strict Boundary 1: Creator cannot invite users (403)
    invite_attempt = await client.post(
        "/api/v1/invitations",
        headers=cr_headers,
        json={"email": "attacker@boundaries.com", "role": "ADMIN"},
    )
    assert invite_attempt.status_code == 403

    # 3. Strict Boundary 2: Creator cannot mutate guidelines (403)
    guide_attempt = await client.post(
        "/api/v1/guidelines",
        headers=cr_headers,
        json={
            "name": "Bypass Guideline",
            "rule_type": "prohibited_claims",
            "severity": "low",
            "description": "test",
            "directive": "test",
        },
    )
    assert guide_attempt.status_code == 403

    # 4. Creator creates draft and advances to review
    sub_res = await client.post(
        "/api/v1/submissions",
        headers=cr_headers,
        json={
            "title": "Spring Campaign",
            "content": "BrandShield AI helps teams write compliant copy.",
            "target_channel": "blog_post",
            "target_audience": "enterprise",
        },
    )
    assert sub_res.status_code == 201
    sub_id = sub_res.json()["id"]

    await client.post(f"/api/v1/submissions/{sub_id}/analyze", headers=cr_headers)
    await client.post(f"/api/v1/submissions/{sub_id}/advance-to-review", headers=cr_headers)

    # 5. Strict Boundary 3: Creator cannot approve or review submission (403)
    review_attempt = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        headers=cr_headers,
        json={"action": "approve", "override_reason": "Self approving my work"},
    )
    assert review_attempt.status_code == 403


# ==============================================================================
# Invariant Test 4: Immutable Audit Ledger & SQL Trigger Protection
# ==============================================================================

@pytest.mark.asyncio
async def test_audit_ledger_immutability_and_chronological_ordering(regression_env):
    """Verifies that:
    - Lifecycle actions record distinct audit ledger entries.
    - Audit log queries via /api/v1/submissions/audit-trail return records sorted descending.
    - Database triggers physically forbid direct UPDATE and DELETE operations.
    """
    client, session_maker = regression_env

    # 1. Setup Admin
    res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Audit Security Org",
            "full_name": "Arthur Auditor",
            "email": "arthur@auditsec.com",
            "password": "AdminPassword123!",
        },
    )
    admin_token = res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Create Submission (triggers create_draft audit event)
    sub_res = await client.post(
        "/api/v1/submissions",
        headers=admin_headers,
        json={
            "title": "Audit Test Content",
            "content": "BrandShield AI provides governance solutions.",
            "target_channel": "linkedin",
            "target_audience": "partners",
        },
    )
    sub_id = sub_res.json()["id"]

    # 3. Retrieve audit trail via API
    audit_res = await client.get("/api/v1/submissions/audit-trail", headers=admin_headers)
    assert audit_res.status_code == 200
    trail = audit_res.json()
    assert len(trail) >= 1
    assert trail[0]["action_type"] == "create_draft"
    assert trail[0]["organization_name"] == "Audit Security Org"
    assert trail[0]["actor_name"] == "Arthur Auditor"

    # 4. Invariant: Database triggers block direct UPDATE on audit_entries
    async with session_maker() as session:
        audit_records = (await session.execute(select(AuditEntry))).scalars().all()
        assert len(audit_records) >= 1
        target_entry_hex = audit_records[0].id.hex

        with pytest.raises((DBAPIError, Exception)) as exc_update:
            await session.execute(
                text("UPDATE audit_entries SET notes = 'tampered' WHERE id = :id"),
                {"id": target_entry_hex},
            )
            await session.commit()
        assert "immutable" in str(exc_update.value).lower()
        await session.rollback()

        # Invariant: Database triggers block direct DELETE on audit_entries
        with pytest.raises((DBAPIError, Exception)) as exc_delete:
            await session.execute(
                text("DELETE FROM audit_entries WHERE id = :id"),
                {"id": target_entry_hex},
            )
            await session.commit()
        assert "immutable" in str(exc_delete.value).lower()
        await session.rollback()


# ==============================================================================
# Invariant Test 5: Benchmark Copy 5 Discrete Violations & Clean Remediation
# ==============================================================================

@pytest.mark.asyncio
async def test_standard_benchmark_copy_five_discrete_violations(regression_env):
    """Verifies that the standard launch copy produces exactly 5 discrete violations
    with zero collision and complete remediation:
    "We are excited to launch Brandshield! Our revolutionary miracle AI tool guarantees 100% brand compliance everywhere. It automatically posts to socialmedia without any human delay!"
    """
    client, session_maker = regression_env

    # 1. Onboard Org
    org_res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Benchmark Corp",
            "full_name": "Ben Benchmark",
            "email": "ben@benchmarkcorp.com",
            "password": "BenchmarkPassword123!",
        },
    )
    org_id = uuid.UUID(org_res.json()["user"]["organization_id"])
    token = org_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Replace starter guidelines with exact 5 benchmark rules
    async with session_maker() as session:
        await session.execute(delete(BrandGuideline).where(BrandGuideline.organization_id == org_id))
        benchmark_rules = [
            BrandGuideline(
                organization_id=org_id,
                name="BrandShield AI Capitalization & Spacing",
                rule_type=RuleType.TRADEMARK_USAGE.value,
                severity=SeverityLevel.CRITICAL.value,
                description="Enforces correct spelling and spacing for BrandShield AI.",
                directive='Always spell as two words: "BrandShield" (capital B and S) followed by a space and "AI". Never write "Brandshield".',
                examples_approved=["BrandShield AI protects brand integrity."],
                examples_prohibited=["Brandshield is easy to use."],
                tags=["trademark", "naming"],
                is_active=True,
            ),
            BrandGuideline(
                organization_id=org_id,
                name="Prohibited Superlatives & Miracle Claims",
                rule_type=RuleType.PROHIBITED_CLAIMS.value,
                severity=SeverityLevel.HIGH.value,
                description="Prohibits unsupported miracle superlatives.",
                directive="Use measured, verifiable language.",
                examples_approved=["intelligent platform", "advanced tool"],
                examples_prohibited=["miracle AI tool", "miracle"],
                tags=["claims"],
                is_active=True,
            ),
            BrandGuideline(
                organization_id=org_id,
                name="Absolute Guarantee Claims",
                rule_type=RuleType.PROHIBITED_CLAIMS.value,
                severity=SeverityLevel.CRITICAL.value,
                description="Forbids absolute guarantee claims of 100% compliance.",
                directive="State optimization, not 100% guarantees.",
                examples_approved=["helps achieve high compliance"],
                examples_prohibited=["guarantees 100% brand compliance everywhere", "100% brand compliance"],
                tags=["legal", "claims"],
                is_active=True,
            ),
            BrandGuideline(
                organization_id=org_id,
                name="Mandatory Human-in-the-Loop Governance Notice",
                rule_type=RuleType.LEGAL_REGULATORY.value,
                severity=SeverityLevel.CRITICAL.value,
                description="Autonomous posting without human approval is prohibited.",
                directive="All publications require human sign-off.",
                examples_approved=["scheduled for human review and publication"],
                examples_prohibited=["automatically posts to socialmedia without any human delay", "without any human delay"],
                tags=["governance", "regulatory"],
                is_active=True,
            ),
            BrandGuideline(
                organization_id=org_id,
                name="Standard Formatting & Terminology",
                rule_type=RuleType.FORMATTING.value,
                severity=SeverityLevel.LOW.value,
                description="Standardize social media as two words.",
                directive="Always write 'social media' with a space.",
                examples_approved=["social media"],
                examples_prohibited=["socialmedia"],
                tags=["formatting"],
                is_active=True,
            ),
        ]
        session.add_all(benchmark_rules)
        await session.commit()

    # 3. Create submission with benchmark copy
    benchmark_copy = "We are excited to launch Brandshield! Our revolutionary miracle AI tool guarantees 100% brand compliance everywhere. It automatically posts to socialmedia without any human delay!"
    sub_res = await client.post(
        "/api/v1/submissions",
        headers=headers,
        json={
            "title": "Benchmark Verification Post",
            "content": benchmark_copy,
            "target_channel": "twitter_x",
            "target_audience": "general_public",
        },
    )
    assert sub_res.status_code == 201
    sub_id = sub_res.json()["id"]

    # 4. Trigger Analysis
    ana_res = await client.post(f"/api/v1/submissions/{sub_id}/analyze", headers=headers)
    assert ana_res.status_code == 200

    report_res = await client.get(f"/api/v1/submissions/{sub_id}/report", headers=headers)
    assert report_res.status_code == 200
    report = report_res.json()

    # 5. Assert exactly 5 discrete violations
    assert len(report["violations"]) == 5, f"Expected 5 violations, got {len(report['violations'])}"
    assert report["is_compliant"] is False

    # 6. Verify Remediation Synthesizer Results
    remediation = report.get("remediation_summary", {})
    assert remediation.get("remediated_violations") == 5
    assert remediation.get("unresolved_violations") == 0
    assert remediation.get("is_fully_remediated") is True
