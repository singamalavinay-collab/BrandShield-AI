"""Unit and integration test suite for BrandShield AI Phase 1, Milestone 2: Risk Assessment Engine.

Validates:
1. Exact mathematical benchmark scenarios (Clean, Typo, 2 Med, Social/B2B, Social/Regulated, Broadcast/General).
2. Severity weighting, partial confidence scaling, score clamping [0, 100], and risk boundary bands.
3. Multi-modal finding deduplication (text span overlap, document page/span, visual bounding box IoU > 0.70).
4. Retention policy: preserves higher severity / higher confidence, never merges distinct rule types.
5. LangGraph compliance graph integration and persistence to ComplianceReport entity.
6. Server-side escalation RBAC enforcement (REVIEWER vs ADMIN, mandatory human feedback on escalated approval, rejection/revision allowance).
7. Cross-tenant isolation and immutable human-only audit ledger enforcement.
"""

from datetime import datetime, timezone
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.engine.evaluator import compliance_engine
from app.engine.risk_scorer import (
    calculate_iou,
    calculate_risk_score,
    deduplicate_findings,
    get_audience_multiplier,
    get_channel_multiplier,
    get_risk_level,
    get_severity_weight,
    round_half_up,
)
from app.models.compliance import ComplianceReport, RuleViolation
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.review import AuditEntry, ReviewDecision
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.common import ReviewAction, SubmissionStatus


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest_asyncio.fixture
async def db_session():
    """Isolated in-memory SQLite database session with complete entity graph."""
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
        # Create Tenants
        org_a = Organization(
            id=uuid.uuid4(),
            name="Alpha Org",
            slug=f"alpha-{uuid.uuid4().hex[:6]}",
            is_active=True,
        )
        org_b = Organization(
            id=uuid.uuid4(),
            name="Beta Corp",
            slug=f"beta-{uuid.uuid4().hex[:6]}",
            is_active=True,
        )
        session.add_all([org_a, org_b])
        await session.flush()

        # Create Users
        admin_user = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email=f"admin-{uuid.uuid4().hex[:4]}@alpha.com",
            full_name="Alice Admin",
            hashed_password="hashed_secret",
            role="ADMIN",
            is_active=True,
        )
        reviewer_user = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email=f"reviewer-{uuid.uuid4().hex[:4]}@alpha.com",
            full_name="Bob Reviewer",
            hashed_password="hashed_secret",
            role="REVIEWER",
            is_active=True,
        )
        creator_user = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email=f"creator-{uuid.uuid4().hex[:4]}@alpha.com",
            full_name="Charlie Creator",
            hashed_password="hashed_secret",
            role="CREATOR",
            is_active=True,
        )
        session.add_all([admin_user, reviewer_user, creator_user])
        await session.flush()

        yield {
            "session": session,
            "org_a": org_a,
            "org_b": org_b,
            "admin": admin_user,
            "reviewer": reviewer_user,
            "creator": creator_user,
        }

    await engine.dispose()


# ==============================================================================
# 1. Exact Benchmark Scenarios Suite
# ==============================================================================

def test_benchmark_scenario_1_clean_content():
    """Scenario 1: Clean content -> Score 0, LOW, not escalated."""
    res = calculate_risk_score([], target_channel="web", target_audience="general")
    assert res.risk_score == 0.0
    assert res.display_score == 0.0
    assert res.risk_level == "LOW"
    assert res.is_escalated is False
    assert res.channel_multiplier == 1.00
    assert res.audience_multiplier == 1.00


def test_benchmark_scenario_2_one_low_typo_web_general():
    """Scenario 2: One low-severity typo, web/general -> Score 4 (4.0 * 1.0 * 1.0 = 4)."""
    findings = [
        {"rule_type": "spelling", "severity": "LOW", "confidence_score": 1.0}
    ]
    res = calculate_risk_score(findings, target_channel="web", target_audience="general")
    assert res.risk_score == 4.0
    assert res.display_score == 4.0
    assert res.risk_level == "LOW"
    assert res.is_escalated is False


def test_benchmark_scenario_3_two_medium_social_general():
    """Scenario 3: Two medium findings, social/general -> Score 27.6 ((12 + 12) * 1.15 * 1.0 = 27.6)."""
    findings = [
        {"rule_type": "tone_of_voice", "severity": "MEDIUM", "confidence_score": 1.0, "char_start": 0, "char_end": 10},
        {"rule_type": "formatting", "severity": "MEDIUM", "confidence_score": 1.0, "char_start": 20, "char_end": 30},
    ]
    res = calculate_risk_score(findings, target_channel="social", target_audience="general")
    assert res.risk_score == 27.6
    assert res.display_score == 27.6
    assert res.risk_level == "LOW"
    assert res.is_escalated is False


def test_benchmark_scenario_4_one_high_one_medium_web_b2b():
    """Scenario 4: One high + one medium, web/LinkedIn + B2B -> Score 31.45 (display 31.5).
    
    Verifies that Web / LinkedIn (multiplier 1.00) + B2B (multiplier 0.85):
    Arithmetic: (25 + 12) * 1.00 * 0.85 = 37 * 0.85 = 31.45 (display 31.5).
    """
    findings = [
        {"rule_type": "trademark_usage", "severity": "HIGH", "confidence_score": 1.0, "char_start": 0, "char_end": 15},
        {"rule_type": "terminology", "severity": "MEDIUM", "confidence_score": 1.0, "char_start": 25, "char_end": 40},
    ]
    # Web + B2B
    res_web = calculate_risk_score(findings, target_channel="web", target_audience="b2b")
    assert res_web.risk_score == 31.45
    assert res_web.display_score == 31.5
    assert res_web.risk_level == "MEDIUM"
    assert res_web.is_escalated is False
    assert res_web.channel_multiplier == 1.00
    assert res_web.audience_multiplier == 0.85

    # LinkedIn + B2B
    res_li = calculate_risk_score(findings, target_channel="linkedin", target_audience="b2b")
    assert res_li.risk_score == 31.45
    assert res_li.display_score == 31.5
    assert res_li.channel_multiplier == 1.00
    assert res_li.audience_multiplier == 0.85


def test_independent_multipliers_social_b2b():
    """Independent multipliers test: One high + one medium, social + B2B -> Score 36.1675 (display 36.2).
    
    Verifies that channel and audience multipliers are strictly independent:
    Social = 1.15 regardless of audience. B2B = 0.85.
    Arithmetic: (25 + 12) * 1.15 * 0.85 = 37 * 0.9775 = 36.1675 (display 36.2).
    """
    findings = [
        {"rule_type": "trademark_usage", "severity": "HIGH", "confidence_score": 1.0, "char_start": 0, "char_end": 15},
        {"rule_type": "terminology", "severity": "MEDIUM", "confidence_score": 1.0, "char_start": 25, "char_end": 40},
    ]
    res_soc = calculate_risk_score(findings, target_channel="social", target_audience="b2b")
    assert res_soc.risk_score == 36.1675
    assert res_soc.display_score == 36.2
    assert res_soc.risk_level == "MEDIUM"
    assert res_soc.is_escalated is False
    assert res_soc.channel_multiplier == 1.15
    assert res_soc.audience_multiplier == 0.85


def test_benchmark_scenario_5_one_high_two_medium_social_regulated():
    """Scenario 5: One high + two medium, social/regulated -> Score 70.4375 (display 70.4, escalated).
    
    Arithmetic: (25 + 12 + 12) * 1.15 * 1.25 = 49 * 1.4375 = 70.4375.
    Score >= 60 triggers mandatory escalation!
    """
    findings = [
        {"rule_type": "regulatory_disclosure", "severity": "HIGH", "confidence_score": 1.0, "char_start": 0, "char_end": 15},
        {"rule_type": "terminology", "severity": "MEDIUM", "confidence_score": 1.0, "char_start": 20, "char_end": 35},
        {"rule_type": "tone_of_voice", "severity": "MEDIUM", "confidence_score": 1.0, "char_start": 40, "char_end": 55},
    ]
    res = calculate_risk_score(findings, target_channel="social", target_audience="regulated")
    assert res.risk_score == 70.4375
    assert res.display_score == 70.4
    assert res.risk_level == "HIGH"
    assert res.is_escalated is True
    assert any(">= 60.0" in r for r in res.escalation_reasons)


def test_benchmark_scenario_6_one_critical_one_high_broadcast_general():
    """Scenario 6: One critical + one high, broadcast/general -> Score 84.5 (CRITICAL, escalated).
    
    Arithmetic: (40 + 25) * 1.30 * 1.0 = 65 * 1.30 = 84.5.
    Contains CRITICAL violation and score >= 60 -> escalated!
    """
    findings = [
        {"rule_type": "prohibited_claims", "severity": "CRITICAL", "confidence_score": 1.0, "char_start": 0, "char_end": 20},
        {"rule_type": "trademark_usage", "severity": "HIGH", "confidence_score": 1.0, "char_start": 30, "char_end": 45},
    ]
    res = calculate_risk_score(findings, target_channel="broadcast", target_audience="general")
    assert res.risk_score == 84.5
    assert res.display_score == 84.5
    assert res.risk_level == "CRITICAL"
    assert res.is_escalated is True
    assert any("CRITICAL" in r for r in res.escalation_reasons)


# ==============================================================================
# 2. Risk Formula, Confidence Weighting, Clamping & Boundaries
# ==============================================================================

def test_confidence_weighting_partial():
    """Verify confidence score linearly scales finding contribution."""
    findings = [
        {"rule_type": "trademark_usage", "severity": "HIGH", "confidence_score": 0.5},  # 25 * 0.5 = 12.5
        {"rule_type": "terminology", "severity": "MEDIUM", "confidence_score": 0.8},   # 12 * 0.8 = 9.6
    ]
    res = calculate_risk_score(findings, target_channel="web", target_audience="general")
    # Base: 12.5 + 9.6 = 22.1
    assert res.risk_score == 22.1
    assert res.display_score == 22.1
    assert res.risk_level == "LOW"


def test_score_clamping_upper_bound():
    """Verify extreme violations are clamped to maximum 100.0."""
    findings = [
        {"rule_type": "c1", "severity": "CRITICAL", "confidence_score": 1.0},
        {"rule_type": "c2", "severity": "CRITICAL", "confidence_score": 1.0},
        {"rule_type": "c3", "severity": "CRITICAL", "confidence_score": 1.0},
    ]  # Raw base: 120 * 1.30 * 1.25 = 195.0
    res = calculate_risk_score(findings, target_channel="broadcast", target_audience="regulated")
    assert res.raw_score == 195.0
    assert res.risk_score == 100.0
    assert res.display_score == 100.0
    assert res.risk_level == "CRITICAL"
    assert res.is_escalated is True


def test_score_clamping_lower_bound():
    """Verify zero or empty findings clamped to 0.0."""
    res = calculate_risk_score([], target_channel=None, target_audience=None)
    assert res.risk_score == 0.0
    assert res.display_score == 0.0
    assert res.risk_level == "LOW"
    assert res.is_escalated is False


def test_risk_level_boundaries():
    """Verify exact threshold boundary transitions."""
    assert get_risk_level(0.0) == "LOW"
    assert get_risk_level(29.9) == "LOW"
    assert get_risk_level(30.0) == "MEDIUM"
    assert get_risk_level(59.9) == "MEDIUM"
    assert get_risk_level(60.0) == "HIGH"
    assert get_risk_level(79.9) == "HIGH"
    assert get_risk_level(80.0) == "CRITICAL"
    assert get_risk_level(100.0) == "CRITICAL"


def test_critical_finding_triggers_escalation_even_at_low_score():
    """Escalation MUST trigger if a CRITICAL finding exists, even if multipliers place score < 30."""
    findings = [
        {"rule_type": "prohibited_claims", "severity": "CRITICAL", "confidence_score": 0.5}  # 40 * 0.5 = 20
    ]
    # Channel internal (0.75) * B2B (0.85) = 0.6375 -> Score: 20 * 0.6375 = 12.75 (< 30, LOW band)
    res = calculate_risk_score(findings, target_channel="internal", target_audience="b2b")
    assert res.risk_score == 12.75
    assert res.risk_level == "LOW"
    assert res.is_escalated is True, "Critical violation must trigger escalation regardless of score"
    assert any("CRITICAL" in r for r in res.escalation_reasons)


# ==============================================================================
# 3. Multi-Modal Finding Deduplication
# ==============================================================================

def test_deduplicate_text_overlapping_spans_same_rule_type():
    """Text: Overlapping spans for same rule_type keep higher severity finding."""
    findings = [
        {"rule_type": "trademark_usage", "severity": "MEDIUM", "char_start": 10, "char_end": 30, "flagged_text": "BrandShield AI"},
        {"rule_type": "trademark_usage", "severity": "CRITICAL", "char_start": 20, "char_end": 45, "flagged_text": "BrandShield AI Platform"},
    ]
    deduped = deduplicate_findings(findings)
    assert len(deduped) == 1
    assert deduped[0]["severity"] == "CRITICAL"
    assert deduped[0]["flagged_text"] == "BrandShield AI Platform"


def test_never_merge_different_rule_types_even_with_overlapping_spans():
    """Invariant: Never merge different violation types just because their spans overlap."""
    findings = [
        {"rule_type": "trademark_usage", "severity": "MEDIUM", "char_start": 15, "char_end": 35, "flagged_text": "Fast AI"},
        {"rule_type": "tone_of_voice", "severity": "HIGH", "char_start": 15, "char_end": 35, "flagged_text": "Fast AI"},
    ]
    deduped = deduplicate_findings(findings)
    assert len(deduped) == 2, "Distinct violation types must never be merged"
    rule_types = {d["rule_type"] for d in deduped}
    assert "trademark_usage" in rule_types
    assert "tone_of_voice" in rule_types


def test_deduplicate_document_modality_page_and_spans():
    """Document: Same page with overlapping spans deduplicates; different pages remain separate."""
    findings = [
        {"rule_type": "regulatory_disclosure", "severity": "LOW", "page": 1, "char_start": 10, "char_end": 50},
        {"rule_type": "regulatory_disclosure", "severity": "HIGH", "page": 1, "char_start": 25, "char_end": 70},
        {"rule_type": "regulatory_disclosure", "severity": "MEDIUM", "page": 2, "char_start": 25, "char_end": 70},
    ]
    deduped = deduplicate_findings(findings)
    assert len(deduped) == 2
    p1 = [f for f in deduped if f["page"] == 1][0]
    p2 = [f for f in deduped if f["page"] == 2][0]
    assert p1["severity"] == "HIGH"
    assert p2["severity"] == "MEDIUM"


def test_deduplicate_image_modality_iou_threshold():
    """Image: Same brand entity with bounding box IoU > 0.70 deduplicates; IoU <= 0.70 retained."""
    # Box 1: [0, 0, 100, 100] (area 10000)
    # Box 2: [0, 0, 100, 85] (area 8500) -> Intersection: 8500, Union: 10000 -> IoU = 0.85 (> 0.70)
    # Box 3: [200, 200, 300, 300] (disjoint box) -> IoU = 0.0
    findings = [
        {"rule_type": "logo_misuse", "brand_entity": "primary_logo", "bounding_box": [0, 0, 100, 100], "severity": "MEDIUM"},
        {"rule_type": "logo_misuse", "brand_entity": "primary_logo", "bounding_box": [0, 0, 100, 85], "severity": "HIGH"},
        {"rule_type": "logo_misuse", "brand_entity": "primary_logo", "bounding_box": [200, 200, 300, 300], "severity": "LOW"},
    ]
    deduped = deduplicate_findings(findings)
    assert len(deduped) == 2
    assert deduped[0]["severity"] == "HIGH"
    assert deduped[1]["severity"] == "LOW"


def test_image_modality_different_entities_not_merged():
    """Image: Even with high IoU, different brand entities are not merged."""
    findings = [
        {"rule_type": "logo_misuse", "brand_entity": "logo_symbol", "bounding_box": [0, 0, 100, 100], "severity": "MEDIUM"},
        {"rule_type": "logo_misuse", "brand_entity": "logo_wordmark", "bounding_box": [0, 0, 100, 100], "severity": "HIGH"},
    ]
    deduped = deduplicate_findings(findings)
    assert len(deduped) == 2


# ==============================================================================
# 4. LangGraph Compliance Pipeline Integration & Report Persistence
# ==============================================================================

@pytest.mark.asyncio
async def test_langgraph_inspection_persists_risk_fields(db_session):
    """Verify that ComplianceEngine.run_inspection computes and persists all risk assessment fields."""
    session = db_session["session"]
    org_a = db_session["org_a"]
    admin = db_session["admin"]

    # Create active brand guideline
    gl = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        name="Trademark Directive",
        rule_type="trademark_usage",
        severity="HIGH",
        directive="Always capitalize BrandShield properly.",
        description="BrandShield capitalization standard.",
        examples_prohibited=["brandshield", "Brandshield"],
        examples_approved=["BrandShield"],
        is_active=True,
    )
    session.add(gl)
    await session.flush()

    # Create submission with prohibited text
    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Product Launch",
        content="Welcome to brandshield, the new standard.",
        target_channel="social",
        target_audience="general",
        status="submitting",
        version=1,
    )
    session.add(sub)
    await session.flush()

    # Run inspection
    report = await compliance_engine.run_inspection(
        session=session,
        submission=sub,
        guidelines_override=[gl],
        actor=admin,
    )

    # Verify report risk assessment fields
    assert report.risk_score > 0.0
    assert report.risk_level in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert report.channel_multiplier == 1.15  # social
    assert report.audience_multiplier == 1.00  # general
    assert isinstance(report.risk_breakdown, dict)
    assert "findings_breakdown" in report.risk_breakdown
    assert len(report.risk_breakdown["findings_breakdown"]) > 0

    # Verify summary contains risk score
    assert "Risk Score:" in report.summary

    # Query back from DB
    rep_db = await session.execute(
        select(ComplianceReport).where(ComplianceReport.id == report.id)
    )
    saved = rep_db.scalar_one()
    assert saved.risk_score == report.risk_score
    assert saved.risk_level == report.risk_level
    assert saved.is_escalated == report.is_escalated


# ==============================================================================
# 5. Server-Side Escalation Enforcement & RBAC
# ==============================================================================

@pytest.mark.asyncio
async def test_standard_reviewer_cannot_approve_escalated_submission(db_session):
    """Standard reviewer role cannot approve or edit_and_approve escalated content."""
    from fastapi import HTTPException
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    reviewer = db_session["reviewer"]  # Role: REVIEWER

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="High Risk Campaign",
        content="Violating content",
        target_channel="social",
        status="under_human_review",
        version=1,
    )
    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=1,
        is_compliant=False,
        total_violations=1,
        summary="High risk report",
        risk_score=75.0,
        risk_level="HIGH",
        is_escalated=True,
    )
    session.add_all([sub, report])
    await session.flush()

    # Reviewer attempts APPROVE
    payload = ReviewDecisionCreate(action=ReviewAction.APPROVE, feedback="Approving anyway", override_reason="Override")
    with pytest.raises(HTTPException) as exc1:
        await record_human_review(
            submission_id=sub.id,
            payload=payload,
            session=session,
            org=org_a,
            current_reviewer=reviewer,
        )
    assert exc1.value.status_code == 403
    assert "Standard reviewers cannot approve escalated content" in str(exc1.value.detail)

    # Reviewer attempts EDIT_AND_APPROVE
    payload_edit = ReviewDecisionCreate(
        action=ReviewAction.EDIT_AND_APPROVE,
        feedback="Cleaned up copy",
        edited_content="Compliant content",
    )
    with pytest.raises(HTTPException) as exc2:
        await record_human_review(
            submission_id=sub.id,
            payload=payload_edit,
            session=session,
            org=org_a,
            current_reviewer=reviewer,
        )
    assert exc2.value.status_code == 403
    assert "Standard reviewers cannot approve escalated content" in str(exc2.value.detail)


@pytest.mark.asyncio
async def test_admin_can_approve_escalated_submission_with_mandatory_feedback(db_session):
    """Admin can approve escalated submission, but MUST supply human feedback."""
    from fastapi import HTTPException
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    admin = db_session["admin"]  # Role: ADMIN

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Critical Submission",
        content="Prohibited statement",
        target_channel="broadcast",
        status="under_human_review",
        version=1,
    )
    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=1,
        is_compliant=False,
        total_violations=1,
        summary="Critical report",
        risk_score=85.0,
        risk_level="CRITICAL",
        is_escalated=True,
    )
    session.add_all([sub, report])
    await session.flush()

    # Admin attempts APPROVE without feedback -> 400 Bad Request
    payload_empty_fb = ReviewDecisionCreate(
        action=ReviewAction.APPROVE,
        feedback="",
        override_reason="Authorized legal waiver",
    )
    with pytest.raises(HTTPException) as exc:
        await record_human_review(
            submission_id=sub.id,
            payload=payload_empty_fb,
            session=session,
            org=org_a,
            current_reviewer=admin,
        )
    assert exc.value.status_code == 400
    assert "Escalated approvals require mandatory human review feedback" in str(exc.value.detail)

    # Admin approves with mandatory feedback and override reason -> 200 OK
    payload_valid = ReviewDecisionCreate(
        action=ReviewAction.APPROVE,
        feedback="Approved after legal counsel and compliance VP review.",
        override_reason="Formal C-level exemption granted.",
    )
    res = await record_human_review(
        submission_id=sub.id,
        payload=payload_valid,
        session=session,
        org=org_a,
        current_reviewer=admin,
    )
    assert res["success"] is True
    assert res["submission"]["status"] == "approved"

    # Verify audit entry is recorded
    audit_res = await session.execute(
        select(AuditEntry).where(AuditEntry.submission_id == sub.id)
    )
    audit = audit_res.scalar_one()
    assert audit.action_type == "human_review_approve"
    assert audit.actor_type == "human"
    assert audit.details["is_escalated"] is True
    assert audit.details["reviewer_role"] == "ADMIN"


@pytest.mark.asyncio
async def test_reviewer_can_reject_or_request_revision_on_escalated_submission(db_session):
    """Reviewers are permitted to reject or request revisions on escalated content."""
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    reviewer = db_session["reviewer"]

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Escalated Content for Rejection",
        content="Harmful claims",
        target_channel="broadcast",
        status="under_human_review",
        version=1,
    )
    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=1,
        is_compliant=False,
        total_violations=2,
        summary="Escalated report",
        risk_score=90.0,
        risk_level="CRITICAL",
        is_escalated=True,
    )
    session.add_all([sub, report])
    await session.flush()

    # Reviewer requests revision
    payload_rev = ReviewDecisionCreate(
        action=ReviewAction.REQUEST_REVISION,
        feedback="Please remove the unsubstantiated guarantee on line 3.",
    )
    res_rev = await record_human_review(
        submission_id=sub.id,
        payload=payload_rev,
        session=session,
        org=org_a,
        current_reviewer=reviewer,
    )
    assert res_rev["success"] is True
    assert res_rev["submission"]["status"] == "revision_requested"

    # Transition back to under_human_review to test rejection
    sub.status = "under_human_review"
    await session.flush()

    # Reviewer rejects
    payload_rej = ReviewDecisionCreate(
        action=ReviewAction.REJECT,
        feedback="Content strictly breaches safety directives. Rejected.",
    )
    res_rej = await record_human_review(
        submission_id=sub.id,
        payload=payload_rej,
        session=session,
        org=org_a,
        current_reviewer=reviewer,
    )
    assert res_rej["success"] is True
    assert res_rej["submission"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_non_escalated_submission_approved_by_reviewer(db_session):
    """Non-escalated submissions (low/medium risk without critical violations) can be approved by standard reviewers."""
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    reviewer = db_session["reviewer"]

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Standard Blog Post",
        content="Clean content",
        target_channel="web",
        status="under_human_review",
        version=1,
    )
    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Clean report",
        risk_score=0.0,
        risk_level="LOW",
        is_escalated=False,
    )
    session.add_all([sub, report])
    await session.flush()

    payload = ReviewDecisionCreate(action=ReviewAction.APPROVE, feedback="Looks great.")
    res = await record_human_review(
        submission_id=sub.id,
        payload=payload,
        session=session,
        org=org_a,
        current_reviewer=reviewer,
    )
    assert res["success"] is True
    assert res["submission"]["status"] == "approved"


@pytest.mark.asyncio
async def test_cross_tenant_review_rejected(db_session):
    """Tenant isolation: Reviewer from Org A cannot review a submission belonging to Org B."""
    from fastapi import HTTPException
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    org_b = db_session["org_b"]
    admin_a = db_session["admin"]

    # Submission belongs to Org B
    sub_b = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        title="Org B Submission",
        content="Content for Org B",
        target_channel="web",
        status="under_human_review",
        version=1,
    )
    session.add(sub_b)
    await session.flush()

    # User from Org A attempts to review Org B submission
    payload = ReviewDecisionCreate(action=ReviewAction.APPROVE, feedback="Unauthorized cross-tenant attempt")
    with pytest.raises(HTTPException) as exc:
        await record_human_review(
            submission_id=sub_b.id,
            payload=payload,
            session=session,
            org=org_a,  # Org A context
            current_reviewer=admin_a,
        )
    assert exc.value.status_code == 404


# ==============================================================================
# 5. Security & Correctness Remediation Tests (Phase 1, Milestone 2)
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("deceptive_name", [
    "Sarah Jenkins (Senior Compliance Officer)",
    "Lead Reviewer",
    "Alex Leadbetter",
    "Senior Executive Officer",
    "Team Lead Compliance",
])
async def test_reviewer_title_substrings_cannot_grant_elevated_privileges(db_session, deceptive_name: str):
    """Vulnerability Fix: Substrings in full_name ('Senior', 'Lead', 'Leadbetter') MUST NOT grant elevated approval rights.
    
    Only trusted users with explicit role='ADMIN' may approve escalated submissions.
    """
    from fastapi import HTTPException
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]

    # Reviewer with role='REVIEWER' but carrying deceptive display name
    deceptive_reviewer = User(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        email=f"deceptive-{uuid.uuid4().hex[:4]}@alpha.com",
        full_name=deceptive_name,
        hashed_password="hashed_secret",
        role="REVIEWER",  # Untrusted standard role
        is_active=True,
    )
    session.add(deceptive_reviewer)

    # Escalated submission
    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Escalated Campaign",
        content="Flagged copy",
        target_channel="broadcast",
        status="under_human_review",
        version=1,
    )
    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=1,
        is_compliant=False,
        total_violations=1,
        summary="Escalated critical report",
        risk_score=85.0,
        risk_level="CRITICAL",
        is_escalated=True,
    )
    session.add_all([sub, report])
    await session.flush()

    # Attempt APPROVE -> Must be rejected with 403 Forbidden
    payload_approve = ReviewDecisionCreate(
        action=ReviewAction.APPROVE,
        feedback="Attempting unauthorized approval using title",
        override_reason="None",
    )
    with pytest.raises(HTTPException) as exc:
        await record_human_review(
            submission_id=sub.id,
            payload=payload_approve,
            session=session,
            org=org_a,
            current_reviewer=deceptive_reviewer,
        )
    assert exc.value.status_code == 403
    assert "Approval requires an ADMIN role" in exc.value.detail or "Standard reviewers cannot approve escalated content" in exc.value.detail

    # Attempt EDIT_AND_APPROVE -> Must also be rejected with 403 Forbidden
    payload_edit = ReviewDecisionCreate(
        action=ReviewAction.EDIT_AND_APPROVE,
        feedback="Attempting unauthorized edit_and_approve",
        edited_content="Edited copy",
    )
    with pytest.raises(HTTPException) as exc_edit:
        await record_human_review(
            submission_id=sub.id,
            payload=payload_edit,
            session=session,
            org=org_a,
            current_reviewer=deceptive_reviewer,
        )
    assert exc_edit.value.status_code == 403


@pytest.mark.asyncio
async def test_concurrent_review_attempts_prevent_conflicting_decisions(db_session):
    """Concurrency Guard: Once a review decision transitions a submission, subsequent concurrent reviews must fail."""
    from fastapi import HTTPException
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    reviewer = db_session["reviewer"]

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Concurrent Test Copy",
        content="Clean content",
        target_channel="web",
        status="under_human_review",
        version=1,
    )
    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Clean report",
        risk_score=0.0,
        risk_level="LOW",
        is_escalated=False,
    )
    session.add_all([sub, report])
    await session.flush()

    # First reviewer executes approval -> transitions to 'approved'
    payload1 = ReviewDecisionCreate(action=ReviewAction.APPROVE, feedback="First reviewer signs off.")
    res1 = await record_human_review(
        submission_id=sub.id,
        payload=payload1,
        session=session,
        org=org_a,
        current_reviewer=reviewer,
    )
    assert res1["success"] is True
    assert res1["submission"]["status"] == "approved"

    # Second concurrent review attempt on already transitioned submission -> 400 Bad Request
    payload2 = ReviewDecisionCreate(action=ReviewAction.REJECT, feedback="Second reviewer attempts conflicting decision.")
    with pytest.raises(HTTPException) as exc:
        await record_human_review(
            submission_id=sub.id,
            payload=payload2,
            session=session,
            org=org_a,
            current_reviewer=reviewer,
        )
    assert exc.value.status_code == 400
    assert "under_human_review" in exc.value.detail


@pytest.mark.asyncio
async def test_missing_report_rejects_approval(db_session):
    """Missing Report Guard: Submissions without a compliance report cannot be approved."""
    from fastapi import HTTPException
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    reviewer = db_session["reviewer"]

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="No Report Submission",
        content="Uninspected copy",
        target_channel="web",
        status="under_human_review",
        version=1,
    )
    session.add(sub)
    await session.flush()

    # Attempt APPROVE without a report -> 400 Bad Request
    payload = ReviewDecisionCreate(action=ReviewAction.APPROVE, feedback="Blind approval attempt")
    with pytest.raises(HTTPException) as exc:
        await record_human_review(
            submission_id=sub.id,
            payload=payload,
            session=session,
            org=org_a,
            current_reviewer=reviewer,
        )
    assert exc.value.status_code == 400
    assert "No compliance report exists for current submission version" in exc.value.detail


@pytest.mark.asyncio
async def test_stale_report_rejects_approval(db_session):
    """Stale Report Guard: An older version's report (e.g. v1) CANNOT be used to approve a newer version (e.g. v2)."""
    from fastapi import HTTPException
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    reviewer = db_session["reviewer"]

    # Submission has progressed to version 2
    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Version 2 Copy",
        content="Brand new copy",
        target_channel="web",
        status="under_human_review",
        version=2,
    )
    # But report in database is stale (from version 1)
    stale_report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=1,  # STALE: v1 != v2
        is_compliant=True,
        total_violations=0,
        summary="Clean report for v1",
        risk_score=0.0,
        risk_level="LOW",
        is_escalated=False,
    )
    session.add_all([sub, stale_report])
    await session.flush()

    # Attempt APPROVE v2 using stale v1 report -> 400 Bad Request
    payload = ReviewDecisionCreate(action=ReviewAction.APPROVE, feedback="Approving v2")
    with pytest.raises(HTTPException) as exc:
        await record_human_review(
            submission_id=sub.id,
            payload=payload,
            session=session,
            org=org_a,
            current_reviewer=reviewer,
        )
    assert exc.value.status_code == 400
    assert "No compliance report exists for current submission version (v2)" in exc.value.detail


@pytest.mark.asyncio
async def test_current_version_report_acceptance(db_session):
    """Current Version Acceptance: A valid report matching the current submission version permits approval."""
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    reviewer = db_session["reviewer"]

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Version 2 Clean Copy",
        content="Compliant copy for version 2",
        target_channel="web",
        status="under_human_review",
        version=2,
    )
    current_report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=2,  # MATCHES CURRENT VERSION
        is_compliant=True,
        total_violations=0,
        summary="Clean report for v2",
        risk_score=0.0,
        risk_level="LOW",
        is_escalated=False,
    )
    session.add_all([sub, current_report])
    await session.flush()

    payload = ReviewDecisionCreate(action=ReviewAction.APPROVE, feedback="Approving valid v2.")
    res = await record_human_review(
        submission_id=sub.id,
        payload=payload,
        session=session,
        org=org_a,
        current_reviewer=reviewer,
    )
    assert res["success"] is True
    assert res["submission"]["status"] == "approved"
    assert res["submission"]["version"] == 2


@pytest.mark.asyncio
async def test_missing_report_permits_rejection_and_revision(db_session):
    """Workflow Resilience: Reviewers CAN reject or request revision even if report is missing."""
    from app.api.v1.reviews import record_human_review
    from app.schemas.reviews import ReviewDecisionCreate

    session = db_session["session"]
    org_a = db_session["org_a"]
    reviewer = db_session["reviewer"]

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Malformed Copy",
        content="Obvious spam copy",
        target_channel="web",
        status="under_human_review",
        version=1,
    )
    session.add(sub)
    await session.flush()

    # Request Revision works without report
    payload_rev = ReviewDecisionCreate(
        action=ReviewAction.REQUEST_REVISION,
        feedback="Copy is completely malformed. Please resubmit proper draft.",
    )
    res_rev = await record_human_review(
        submission_id=sub.id,
        payload=payload_rev,
        session=session,
        org=org_a,
        current_reviewer=reviewer,
    )
    assert res_rev["success"] is True
    assert res_rev["submission"]["status"] == "revision_requested"

    # Reset to under_human_review and verify Reject also works
    sub.status = "under_human_review"
    await session.flush()

    payload_rej = ReviewDecisionCreate(
        action=ReviewAction.REJECT,
        feedback="Definite spam. Rejected.",
    )
    res_rej = await record_human_review(
        submission_id=sub.id,
        payload=payload_rej,
        session=session,
        org=org_a,
        current_reviewer=reviewer,
    )
    assert res_rej["success"] is True
    assert res_rej["submission"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_immutable_audit_integrity_on_reviews(db_session):
    """Audit Immutability: AuditEntry records cannot be modified or deleted."""
    from app.core.database import ImmutableAuditError

    session = db_session["session"]
    org_a = db_session["org_a"]
    admin = db_session["admin"]

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Audit Test Copy",
        content="Test content",
        target_channel="web",
        status="under_human_review",
        version=1,
    )
    session.add(sub)
    await session.flush()

    audit = AuditEntry(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        submission_id=sub.id,
        previous_status="draft",
        new_status="submitted",
        action_type="submit_content",
        actor_id=str(admin.id),
        actor_type="human",
        actor_name=admin.full_name,
        notes="Audit entry for immutability test",
        details={},
    )
    session.add(audit)
    await session.flush()

    # Attempting to mutate audit entry raises ImmutableAuditError
    audit.notes = "Tampered notes"
    with pytest.raises(ImmutableAuditError):
        await session.flush()

    await session.rollback()
