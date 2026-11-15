import asyncio
from datetime import datetime, timezone
import hashlib
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.compliance import ComplianceReport, RuleViolation
from app.models.guideline import BrandGuideline
from app.models.invitation import TeamInvitation
from app.models.organization import Organization
from app.models.review import AuditEntry, ReviewDecision
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.guidelines import RuleType, SeverityLevel


@pytest_asyncio.fixture
async def lifecycle_env():
    """Isolated in-memory SQLite database environment strictly segregated from production database."""
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    async with test_engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON;")
        await conn.run_sync(Base.metadata.create_all)

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


def get_err_msg(res) -> str:
    """Helper to extract structured error message from FastAPI response."""
    body = res.json()
    return body.get("message") or body.get("detail") or ""


# ==============================================================================
# Phase 3.5 Full Governance Multi-Persona Lifecycle Test
# ==============================================================================

@pytest.mark.asyncio
async def test_complete_multi_persona_governance_lifecycle(lifecycle_env):
    """Executes the complete multi-persona governance lifecycle:
    1. ADMIN onboarding & organization creation.
    2. Active brand guideline configuration.
    3. Team invitations for CREATOR and REVIEWER roles.
    4. Safe invitation acceptance & user account provisioning.
    5. CREATOR creates draft and verifies human-readable author attribution.
    6. Content submission & real compliance engine inspection (violations_found).
    7. Invariant: CREATOR is forbidden from performing human review (HTTP 403).
    8. Invariant: Submission cannot bypass required compliance analysis.
    9. REVIEWER advances draft to human review and records authoritative decision.
    10. Immutable audit ledger verification confirming true human actors.
    11. Cross-tenant isolation verification.
    """
    client, session_maker = lifecycle_env

    # --------------------------------------------------------------------------
    # Step 1: ADMIN Onboarding & Organization Creation
    # --------------------------------------------------------------------------
    admin_register_res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Acme Global Governance",
            "full_name": "Alice Administrator",
            "email": "alice.admin@acmecorp.com",
            "password": "AdminSecurePassword123!",
        },
    )
    assert admin_register_res.status_code == 201, admin_register_res.text
    admin_data = admin_register_res.json()
    admin_token = admin_data["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    admin_user = admin_data["user"]
    assert admin_user["role"] == "ADMIN"
    assert admin_user["full_name"] == "Alice Administrator"

    # --------------------------------------------------------------------------
    # Step 2: ADMIN creates an active Brand Guideline
    # --------------------------------------------------------------------------
    guideline_res = await client.post(
        "/api/v1/guidelines",
        json={
            "name": "Absolute Infallibility Claims Prohibition",
            "rule_type": "prohibited_claims",
            "severity": "critical",
            "directive": "Never claim 100% infallible or guaranteed zero risk without legal sign-off.",
            "description": "Regulatory compliance protection against false advertising claims.",
            "examples_approved": ["High confidence brand audit", "Substantial risk reduction"],
            "examples_prohibited": ["100% infallible", "guaranteed zero risk"],
            "tags": ["claims", "legal", "critical"],
            "is_active": True,
        },
        headers=admin_headers,
    )
    assert guideline_res.status_code == 201, guideline_res.text
    guideline_data = guideline_res.json()
    assert guideline_data["is_active"] is True

    # --------------------------------------------------------------------------
    # Step 3: ADMIN invites CREATOR and REVIEWER
    # --------------------------------------------------------------------------
    invite_creator_res = await client.post(
        "/api/v1/invitations",
        json={"email": "charlie.creator@acmecorp.com", "role": "CREATOR"},
        headers=admin_headers,
    )
    assert invite_creator_res.status_code == 201, invite_creator_res.text
    creator_invite_data = invite_creator_res.json()
    creator_token = creator_invite_data["invitation_token"]

    invite_reviewer_res = await client.post(
        "/api/v1/invitations",
        json={"email": "rachel.reviewer@acmecorp.com", "role": "REVIEWER"},
        headers=admin_headers,
    )
    assert invite_reviewer_res.status_code == 201, invite_reviewer_res.text
    reviewer_invite_data = invite_reviewer_res.json()
    reviewer_token = reviewer_invite_data["invitation_token"]

    # --------------------------------------------------------------------------
    # Step 4: Acceptance of CREATOR and REVIEWER invitations
    # --------------------------------------------------------------------------
    accept_creator_res = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": creator_token,
            "full_name": "Charlie Creator",
            "password": "CreatorPassword123!",
        },
    )
    assert accept_creator_res.status_code == 201, accept_creator_res.text
    creator_user_info = accept_creator_res.json()["user"]
    assert creator_user_info["role"] == "CREATOR"
    assert creator_user_info["full_name"] == "Charlie Creator"

    accept_reviewer_res = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": reviewer_token,
            "full_name": "Rachel Reviewer",
            "password": "ReviewerPassword123!",
        },
    )
    assert accept_reviewer_res.status_code == 201, accept_reviewer_res.text
    reviewer_user_info = accept_reviewer_res.json()["user"]
    assert reviewer_user_info["role"] == "REVIEWER"
    assert reviewer_user_info["full_name"] == "Rachel Reviewer"

    # --------------------------------------------------------------------------
    # Step 5: Authenticate CREATOR & REVIEWER sessions
    # --------------------------------------------------------------------------
    creator_login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "charlie.creator@acmecorp.com", "password": "CreatorPassword123!"},
    )
    assert creator_login_res.status_code == 200
    creator_bearer = {"Authorization": f"Bearer {creator_login_res.json()['access_token']}"}

    reviewer_login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "rachel.reviewer@acmecorp.com", "password": "ReviewerPassword123!"},
    )
    assert reviewer_login_res.status_code == 200
    reviewer_bearer = {"Authorization": f"Bearer {reviewer_login_res.json()['access_token']}"}

    # --------------------------------------------------------------------------
    # Step 6: CREATOR creates Content Draft with Brand Rule Violation
    # --------------------------------------------------------------------------
    create_sub_res = await client.post(
        "/api/v1/submissions",
        json={
            "title": "Q4 Enterprise Security Launch Announcement",
            "content": "BrandShield AI delivers 100% infallible brand protection with guaranteed zero risk for enterprise clients.",
            "target_channel": "linkedin",
            "target_audience": "Enterprise Compliance Officers",
            "metadata": {"campaign": "Q4_Launch"},
        },
        headers=creator_bearer,
    )
    assert create_sub_res.status_code == 201, create_sub_res.text
    sub_data = create_sub_res.json()
    sub_id = sub_data["id"]
    assert sub_data["status"] == "draft"

    # Explicit author attribution assertions
    assert sub_data["author_name"] == "Charlie Creator", "Submission must expose author_name as human-readable display name"
    assert sub_data["author_id"] == creator_user_info["id"], "Submission author_id must match authenticated Creator UUID"
    assert sub_data["author_name"] != creator_user_info["id"], "author_name must NEVER be equal to raw UUID string"

    # --------------------------------------------------------------------------
    # Step 7: CREATOR submits draft for compliance inspection
    # --------------------------------------------------------------------------
    submit_res = await client.post(
        f"/api/v1/submissions/{sub_id}/submit",
        headers=creator_bearer,
    )
    assert submit_res.status_code == 200
    assert submit_res.json()["status"] == "submitted"
    assert submit_res.json()["author_name"] == "Charlie Creator"

    # --------------------------------------------------------------------------
    # Step 8: Trigger Real Compliance Engine Inspection (No Mocks)
    # --------------------------------------------------------------------------
    analyze_res = await client.post(
        f"/api/v1/submissions/{sub_id}/analyze",
        headers=creator_bearer,
    )
    assert analyze_res.status_code == 200, analyze_res.text
    analyzed_data = analyze_res.json()
    assert analyzed_data["status"] == "violations_found"
    assert analyzed_data["author_name"] == "Charlie Creator"

    # Verify inspection results persisted in isolated SQLite
    report_res = await client.get(
        f"/api/v1/submissions/{sub_id}/report",
        headers=creator_bearer,
    )
    assert report_res.status_code == 200
    report_data = report_res.json()
    assert report_data["total_violations"] >= 1
    assert report_data["is_compliant"] is False

    # --------------------------------------------------------------------------
    # Step 9: Invariant Check: CREATOR cannot perform Reviewer-only actions
    # --------------------------------------------------------------------------
    creator_review_res = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve", "feedback": "Self-approval attempt"},
        headers=creator_bearer,
    )
    assert creator_review_res.status_code == 403
    assert "ADMIN or REVIEWER role required" in get_err_msg(creator_review_res)

    # --------------------------------------------------------------------------
    # Step 10: Invariant Check: Submissions cannot skip 'under_human_review'
    # --------------------------------------------------------------------------
    skip_review_res = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve", "feedback": "Direct approval without advance"},
        headers=reviewer_bearer,
    )
    assert skip_review_res.status_code == 400
    assert "under_human_review" in get_err_msg(skip_review_res)

    # --------------------------------------------------------------------------
    # Step 11: REVIEWER advances submission to 'under_human_review'
    # --------------------------------------------------------------------------
    advance_res = await client.post(
        f"/api/v1/submissions/{sub_id}/advance-to-review",
        headers=reviewer_bearer,
    )
    assert advance_res.status_code == 200
    assert advance_res.json()["status"] == "under_human_review"
    assert advance_res.json()["author_name"] == "Charlie Creator"

    # --------------------------------------------------------------------------
    # Step 12: REVIEWER records authoritative governance decision
    # --------------------------------------------------------------------------
    review_decision_res = await client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={
            "action": "request_revision",
            "feedback": "Please remove '100% infallible' and 'guaranteed zero risk' claims to satisfy legal guidelines.",
        },
        headers=reviewer_bearer,
    )
    assert review_decision_res.status_code == 200, review_decision_res.text
    review_data = review_decision_res.json()
    assert review_data["success"] is True
    assert review_data["submission"]["status"] == "revision_requested"
    assert review_data["decision"]["action"] == "request_revision"
    assert review_data["decision"]["reviewer_name"] == "Rachel Reviewer"

    # --------------------------------------------------------------------------
    # Step 13: Verify Immutable Audit Ledger Integrity
    # --------------------------------------------------------------------------
    audit_res = await client.get(
        f"/api/v1/submissions/{sub_id}/audit-trail",
        headers=reviewer_bearer,
    )
    assert audit_res.status_code == 200
    audit_entries = audit_res.json()
    assert len(audit_entries) >= 4

    # Verify action actors in ledger
    create_entry = next((e for e in audit_entries if e["action_type"] == "create_draft"), None)
    assert create_entry is not None
    assert create_entry["actor_name"] == "Charlie Creator"
    assert create_entry["actor_id"] == creator_user_info["id"]

    review_entry = next((e for e in audit_entries if e["action_type"] == "human_review_request_revision"), None)
    assert review_entry is not None
    assert review_entry["actor_name"] == "Rachel Reviewer"
    assert review_entry["actor_id"] == reviewer_user_info["id"]
    assert review_entry["new_status"] == "revision_requested"

    # --------------------------------------------------------------------------
    # Step 14: Verify List & Get Author Attribution Across Roles
    # --------------------------------------------------------------------------
    # ADMIN views submissions list
    admin_list_res = await client.get("/api/v1/submissions", headers=admin_headers)
    assert admin_list_res.status_code == 200
    admin_sub = next((s for s in admin_list_res.json() if s["id"] == sub_id), None)
    assert admin_sub is not None
    assert admin_sub["author_name"] == "Charlie Creator"

    # REVIEWER views pending reviews list
    reviewer_pending_res = await client.get("/api/v1/submissions", headers=reviewer_bearer)
    assert reviewer_pending_res.status_code == 200
    rev_sub = next((s for s in reviewer_pending_res.json() if s["id"] == sub_id), None)
    assert rev_sub is not None
    assert rev_sub["author_name"] == "Charlie Creator"

    # --------------------------------------------------------------------------
    # Step 15: Cross-Tenant Isolation Invariant
    # --------------------------------------------------------------------------
    # Onboard Organization B
    org_b_register_res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Beta Industries",
            "full_name": "Bob Beta",
            "email": "bob.admin@betaindustries.com",
            "password": "BetaPassword123!",
        },
    )
    assert org_b_register_res.status_code == 201
    bob_bearer = {"Authorization": f"Bearer {org_b_register_res.json()['access_token']}"}

    # Bob attempts to access Acme Corp submission
    cross_access_res = await client.get(
        f"/api/v1/submissions/{sub_id}",
        headers=bob_bearer,
    )
    assert cross_access_res.status_code == 404, "Cross-tenant access must return 404 Not Found"


# ==============================================================================
# Phase 4 Targeted Regression Tests: Roster, Audit Trail & Deduplication
# ==============================================================================

@pytest.mark.asyncio
async def test_organization_members_endpoint_and_security(lifecycle_env):
    """Verifies GET /api/v1/invitations/members:
    1. ADMIN can retrieve all active organization members.
    2. Owner flag is accurately attributed.
    3. Non-ADMIN roles (CREATOR, REVIEWER) are strictly blocked with 403.
    4. Cross-tenant isolation ensures members of other orgs are never exposed.
    """
    client, _ = lifecycle_env

    # 1. Onboard Organization A
    org_a_res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Roster Tech",
            "full_name": "Alice Admin",
            "email": "alice.admin@rostertech.com",
            "password": "SecurePassword123!",
        },
    )
    assert org_a_res.status_code == 201
    alice_bearer = {"Authorization": f"Bearer {org_a_res.json()['access_token']}"}

    # 2. Alice invites Bob (CREATOR)
    invite_res = await client.post(
        "/api/v1/invitations",
        headers=alice_bearer,
        json={"email": "bob.creator@rostertech.com", "role": "CREATOR"},
    )
    assert invite_res.status_code == 201
    invite_token = invite_res.json()["invitation_token"]

    # 3. Bob accepts invitation
    accept_res = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": invite_token,
            "full_name": "Bob Creator",
            "password": "CreatorPassword123!",
        },
    )
    assert accept_res.status_code == 201
    bob_bearer = {"Authorization": f"Bearer {accept_res.json()['access_token']}"}

    # 4. Alice (ADMIN) retrieves organization roster
    roster_res = await client.get("/api/v1/invitations/members", headers=alice_bearer)
    assert roster_res.status_code == 200
    roster = roster_res.json()
    assert len(roster) == 2

    alice_entry = next((m for m in roster if m["email"] == "alice.admin@rostertech.com"), None)
    assert alice_entry is not None
    assert alice_entry["is_owner"] is True
    assert alice_entry["role"] == "ADMIN"
    assert alice_entry["is_active"] is True

    bob_entry = next((m for m in roster if m["email"] == "bob.creator@rostertech.com"), None)
    assert bob_entry is not None
    assert bob_entry["is_owner"] is False
    assert bob_entry["role"] == "CREATOR"
    assert bob_entry["is_active"] is True

    # 5. Bob (CREATOR) is forbidden from calling GET /api/v1/invitations/members
    bob_roster_res = await client.get("/api/v1/invitations/members", headers=bob_bearer)
    assert bob_roster_res.status_code == 403

    # 6. Organization B (Dave) is completely isolated
    org_b_res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Isolated Corp",
            "full_name": "Dave Admin",
            "email": "dave.admin@isolatedcorp.com",
            "password": "DavePassword123!",
        },
    )
    assert org_b_res.status_code == 201
    dave_bearer = {"Authorization": f"Bearer {org_b_res.json()['access_token']}"}

    dave_roster_res = await client.get("/api/v1/invitations/members", headers=dave_bearer)
    assert dave_roster_res.status_code == 200
    dave_roster = dave_roster_res.json()
    assert len(dave_roster) == 1
    assert dave_roster[0]["email"] == "dave.admin@isolatedcorp.com"


@pytest.mark.asyncio
async def test_organization_audit_trail_endpoint(lifecycle_env):
    """Verifies GET /api/v1/submissions/audit-trail:
    1. Returns tenant-isolated recent audit entries.
    2. Results are ordered by timestamp descending.
    """
    client, _ = lifecycle_env

    # 1. Onboard Organization A
    org_res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Audit Works",
            "full_name": "Audrey Admin",
            "email": "audrey.admin@auditworks.com",
            "password": "AuditPassword123!",
        },
    )
    assert org_res.status_code == 201
    audrey_bearer = {"Authorization": f"Bearer {org_res.json()['access_token']}"}

    # 2. Create a submission (generates audit entry)
    sub_res = await client.post(
        "/api/v1/submissions",
        headers=audrey_bearer,
        json={
            "title": "Audit Test Post",
            "content": "This is a clean and verified product update.",
            "target_channel": "twitter_x",
            "target_audience": "general_public",
        },
    )
    assert sub_res.status_code == 201

    # 3. Fetch organization audit trail
    audit_res = await client.get("/api/v1/submissions/audit-trail?limit=10", headers=audrey_bearer)
    assert audit_res.status_code == 200
    entries = audit_res.json()
    assert len(entries) >= 1
    assert entries[0]["action_type"] == "create_draft"
    assert entries[0]["organization_name"] == "Audit Works"


@pytest.mark.asyncio
async def test_standard_launch_copy_deduplication_five_violations(lifecycle_env):
    """Verifies that the standard launch copy produces exactly 5 discrete violations
    with deduplication suppressing overlapping/contained spans.
    """
    client, session_maker = lifecycle_env

    # 1. Onboard Org
    org_res = await client.post(
        "/api/v1/auth/onboard",
        json={
            "organization_name": "Launch Brand",
            "full_name": "Laura Launch",
            "email": "laura@launchbrand.com",
            "password": "LaunchPassword123!",
        },
    )
    assert org_res.status_code == 201
    org_id = uuid.UUID(org_res.json()["user"]["organization_id"])
    admin_bearer = {"Authorization": f"Bearer {org_res.json()['access_token']}"}

    # 2. Seed standard guidelines into Org (purging starter guidelines to test exact 5 benchmark rules)
    async with session_maker() as session:
        await session.execute(
            delete(BrandGuideline).where(BrandGuideline.organization_id == org_id)
        )
        guidelines = [
            BrandGuideline(
                organization_id=org_id,
                name="BrandShield AI Capitalization & Spacing",
                rule_type=RuleType.TRADEMARK_USAGE.value,
                severity=SeverityLevel.CRITICAL.value,
                description="Enforces correct camel-case spelling and spacing for BrandShield AI.",
                directive='Always spell as two words: "BrandShield" (one word, capital B and S) followed by a space and "AI". Never write as "Brandshield", "Brand Shield", or "BrandshieldAI".',
                examples_approved=["BrandShield AI protects enterprise brand integrity."],
                examples_prohibited=["Brandshield provides brand checking.", "Brand Shield AI is easy to set up."],
                tags=["trademark", "naming"],
                is_active=True,
            ),
            BrandGuideline(
                organization_id=org_id,
                name="Prohibited Superlatives & Miracle Claims",
                rule_type=RuleType.PROHIBITED_CLAIMS.value,
                severity=SeverityLevel.HIGH.value,
                description="No unverified superlatives like miracle",
                directive="Use measured, verifiable language.",
                examples_approved=["breakthrough tool", "advanced platform"],
                examples_prohibited=["miracle AI tool", "miracle"],
                tags=["claims", "compliance"],
                is_active=True,
            ),
            BrandGuideline(
                organization_id=org_id,
                name="Absolute Guarantee Claims",
                rule_type=RuleType.PROHIBITED_CLAIMS.value,
                severity=SeverityLevel.CRITICAL.value,
                description="No guarantees of 100% compliance",
                directive="State optimization and risk reduction, not guarantees.",
                examples_approved=["helps optimize brand consistency"],
                examples_prohibited=["guarantees 100% brand compliance everywhere", "100% brand compliance"],
                tags=["legal", "claims"],
                is_active=True,
            ),
            BrandGuideline(
                organization_id=org_id,
                name="Mandatory Human-in-the-Loop Governance Notice",
                rule_type=RuleType.LEGAL_REGULATORY.value,
                severity=SeverityLevel.CRITICAL.value,
                description="AI cannot post autonomously without human sign-off",
                directive="All publications require human approval.",
                examples_approved=["generates draft content for human review and scheduled publishing"],
                examples_prohibited=["automatically posts to socialmedia without any human delay", "without any human delay"],
                tags=["governance", "regulatory"],
                is_active=True,
            ),
            BrandGuideline(
                organization_id=org_id,
                name="Standard Formatting & Terminology",
                rule_type=RuleType.FORMATTING.value,
                severity=SeverityLevel.LOW.value,
                description="Use social media with a space",
                directive="Always write social media as two words.",
                examples_approved=["social media"],
                examples_prohibited=["GET REAL TIME ALERTS ON SOCIALMEDIA NOW!!", "Check out our socialmedia updates!"],
                tags=["formatting", "tone"],
                is_active=True,
            ),
        ]
        session.add_all(guidelines)
        await session.commit()

    # 3. Create submission with standard copy
    copy_text = "We are excited to launch Brandshield! Our revolutionary miracle AI tool guarantees 100% brand compliance everywhere. It automatically posts to socialmedia without any human delay!"
    sub_res = await client.post(
        "/api/v1/submissions",
        headers=admin_bearer,
        json={
            "title": "Q2 Enterprise Feature Launch",
            "content": copy_text,
            "target_channel": "twitter_x",
            "target_audience": "general_public",
        },
    )
    assert sub_res.status_code == 201
    sub_id = sub_res.json()["id"]

    # 4. Trigger analysis
    analyze_res = await client.post(f"/api/v1/submissions/{sub_id}/analyze", headers=admin_bearer)
    assert analyze_res.status_code == 200

    report_res = await client.get(f"/api/v1/submissions/{sub_id}/report", headers=admin_bearer)
    assert report_res.status_code == 200
    report_data = report_res.json()

    # 5. Assert EXACTLY 5 discrete violations
    assert len(report_data["violations"]) == 5, f"Expected exactly 5 violations, got {len(report_data['violations'])}: {[v['rule_name'] for v in report_data['violations']]}"
    assert report_data["is_compliant"] is False

    # 6. Verify remediated draft resolves all 5
    summary = report_data.get("remediation_summary", {})
    assert summary.get("remediated_violations") == 5
    assert summary.get("unresolved_violations") == 0
    assert summary.get("is_fully_remediated") is True
    assert summary.get("is_fully_remediated") is True
