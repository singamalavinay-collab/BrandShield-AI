"""Comprehensive test suite for Phase 1, Milestone 4: Claim Verification & Fact Checking Engine.

Validates:
1. All five classification categories (VERIFIED, UNSUPPORTED, OUTDATED, CONTRADICTORY, NEEDS_HUMAN_REVIEW).
2. Evidence accuracy, source references, and zero hallucination of document names.
3. Distinct handling of policy restrictions vs factual contradictions.
4. Outdated source version detection (requires identifiable older & newer sources).
5. Anti-shallow-overlap invariant (never VERIFIED on simple n-gram overlap alone).
6. Exclusively active guidelines used (never pending/rejected candidate rules).
7. Gemini failure resilience and deterministic fallback (timeout, quota, invalid JSON, unconfigured).
8. Risk assessment escalation integration (is_escalated = True propagated).
9. Cross-tenant isolation and foreign key integrity.
10. Database persistence, cascading deletion, and immutable audit ledger metrics.
11. API serialization endpoints (GET /submissions/{id}/report and GET /submissions/{id}/claims).
"""

from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.engine.ai_provider import AIProvider
from app.engine.claim_verifier import (
    ClaimVerificationResult,
    extract_candidate_claims,
    verify_claims,
    verify_claims_sync,
)
from app.engine.evaluator import compliance_engine
from app.engine.gemini_client import GeminiClient, GeminiClientError, GeminiErrorCode
from app.main import app
from app.models.compliance import ClaimVerification, ComplianceReport, RuleViolation
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.review import AuditEntry
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.common import ClaimStatus, RuleType, SeverityLevel, SubmissionStatus


# ==============================================================================
# Database & Authentication Fixtures
# ==============================================================================

@pytest_asyncio.fixture
async def claim_test_db():
    """Isolated async SQLite database session for claim verification tests."""
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
            name="Alpha Corp",
            slug=f"alpha-{uuid.uuid4().hex[:6]}",
            is_active=True,
        )
        # Organization 2 (Secondary Tenant)
        org2 = Organization(
            id=uuid.uuid4(),
            name="Beta Corp",
            slug=f"beta-{uuid.uuid4().hex[:6]}",
            is_active=True,
        )
        session.add_all([org1, org2])
        await session.flush()

        # Users
        admin_user = User(
            id=uuid.uuid4(),
            organization_id=org1.id,
            email="admin@alphacorp.com",
            hashed_password=get_password_hash("AdminPass123!"),
            full_name="Alpha Admin",
            role="ADMIN",
            is_active=True,
        )
        reviewer_user = User(
            id=uuid.uuid4(),
            organization_id=org1.id,
            email="reviewer@alphacorp.com",
            hashed_password=get_password_hash("ReviewerPass123!"),
            full_name="Alpha Reviewer",
            role="REVIEWER",
            is_active=True,
        )
        session.add_all([admin_user, reviewer_user])
        await session.flush()

        yield {
            "session": session,
            "engine": test_engine,
            "org1": org1,
            "org2": org2,
            "admin": admin_user,
            "reviewer": reviewer_user,
        }

    await test_engine.dispose()


# ==============================================================================
# Unit Tests: Five Classification Categories & Core Rules
# ==============================================================================

@pytest.mark.asyncio
async def test_claim_verified_with_exact_and_semantic_facts():
    """VERIFIED: Claim matches approved corporate facts and metrics with specific evidence."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Customer Scale Metric",
            "rule_type": "factual_accuracy",
            "severity": "high",
            "directive": "BrandShield AI protects over 50,000 enterprise brands worldwide.",
            "examples_approved": ["protects over 50,000 enterprise brands", "protecting 50,000+ brands"],
            "examples_prohibited": [],
            "document_name": "Official Brand Guidelines 2026.pdf",
            "source_reference": "Section 4.1 (Metrics)",
            "is_active": True,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Foundation Fact",
            "rule_type": "factual_accuracy",
            "severity": "medium",
            "directive": "BrandShield AI was founded in 2021 in San Francisco.",
            "examples_approved": ["founded in 2021"],
            "examples_prohibited": [],
            "document_name": "Corporate Factsheet.pdf",
            "source_reference": "History, Page 2",
            "is_active": True,
        },
    ]

    content = "BrandShield AI was founded in 2021. Today, BrandShield AI protects over 50,000 enterprise brands worldwide."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 2
    for r in results:
        assert r["status"] == ClaimStatus.VERIFIED.value
        assert r["confidence_score"] >= 0.85
        assert r["evidence"] is not None
        assert r["is_escalated"] is False
        assert r["document_name"] in ["Official Brand Guidelines 2026.pdf", "Corporate Factsheet.pdf"]


@pytest.mark.asyncio
async def test_claim_unsupported_not_marked_false():
    """UNSUPPORTED: Uncorroborated assertions must never be marked as FALSE or CONTRADICTORY."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "General Tone",
            "rule_type": "tone_of_voice",
            "directive": "Maintain an objective, technical tone.",
            "is_active": True,
        }
    ]

    content = "BrandShield AI recently opened a regional headquarters in Zurich."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 1
    r = results[0]
    assert r["status"] == ClaimStatus.UNSUPPORTED.value
    assert r["confidence_score"] == 0.50
    assert r["evidence"] is None
    assert r["document_name"] is None
    assert r["source_reference"] is None
    assert r["is_escalated"] is False
    assert "Unsubstantiated assertion" in r["uncertainty_notes"]
    assert "not indicate the claim is factually false" in r["uncertainty_notes"]


@pytest.mark.asyncio
async def test_claim_outdated_specification_detection():
    """OUTDATED: Claim citing superseded metric where an identifiable older & newer standard exist."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Enterprise Customer Count Metric (v2.0)",
            "rule_type": "factual_accuracy",
            "severity": "medium",
            "directive": "BrandShield AI protects over 50,000 enterprise brands worldwide (supersedes prior 10,000 figure from 2023).",
            "examples_approved": ["protects over 50,000 enterprise brands"],
            "examples_prohibited": ["protects 10,000 brands", "over 10,000 enterprise brands"],
            "document_name": "Metrics Update Q1 2026.pdf",
            "source_reference": "Section 2.1",
            "is_active": True,
        }
    ]

    content = "BrandShield AI protects over 10,000 enterprise brands across global markets."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 1
    r = results[0]
    assert r["status"] == ClaimStatus.OUTDATED.value
    assert r["confidence_score"] >= 0.85
    assert "supersedes prior 10,000 figure" in r["evidence"]
    assert "Outdated specification" in r["uncertainty_notes"]
    assert r["document_name"] == "Metrics Update Q1 2026.pdf"


@pytest.mark.asyncio
async def test_claim_outdated_requires_identifiable_older_and_newer_sources():
    """Safeguard 2: If no newer superseding approved source exists, claim must NOT be OUTDATED."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Unrelated Rule",
            "rule_type": "formatting",
            "directive": "Capitalize all product features.",
            "is_active": True,
        }
    ]

    # Without an active guideline establishing an updated figure, uncorroborated metric is UNSUPPORTED
    content = "BrandShield AI achieved a 250% increase in revenue in 2019."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 1
    assert results[0]["status"] == ClaimStatus.UNSUPPORTED.value
    assert results[0]["status"] != ClaimStatus.OUTDATED.value


@pytest.mark.asyncio
async def test_claim_contradictory_policy_violation_distinction():
    """Safeguard 3: Prohibited marketing statements must be labeled as policy restrictions, not factual falsehoods."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Absolute Performance Claims Prohibition",
            "rule_type": "prohibited_claims",
            "severity": "critical",
            "directive": "Never guarantee 100% compliance or claim zero brand risk.",
            "examples_prohibited": ["guarantee 100% compliance", "100% infallible", "zero risk"],
            "examples_approved": ["substantially reduces compliance risk"],
            "document_name": "Compliance Legal Policy.pdf",
            "is_active": True,
        }
    ]

    content = "Our enterprise platform will guarantee 100% compliance across modern distribution channels."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 1
    r = results[0]
    assert r["status"] == ClaimStatus.CONTRADICTORY.value
    assert r["is_escalated"] is True
    assert "Policy restriction" in r["uncertainty_notes"]
    assert "not necessarily a factual falsehood" in r["uncertainty_notes"] or "Absolute performance guarantees are prohibited" in r["uncertainty_notes"]


@pytest.mark.asyncio
async def test_claim_contradictory_factual_conflict():
    """CONTRADICTORY: Direct conflict with verified corporate facts."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Company Founding Standard",
            "rule_type": "factual_accuracy",
            "severity": "high",
            "directive": "BrandShield AI was founded in 2021 in San Francisco.",
            "examples_approved": ["founded in 2021"],
            "document_name": "Corporate Factsheet.pdf",
            "is_active": True,
        }
    ]

    content = "BrandShield AI was founded in 2010 in London, England."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 1
    r = results[0]
    assert r["status"] == ClaimStatus.CONTRADICTORY.value
    assert r["is_escalated"] is True
    assert "Factual contradiction" in r["uncertainty_notes"]
    assert "contradicts verified corporate fact" in r["uncertainty_notes"]


@pytest.mark.asyncio
async def test_claim_needs_human_review_on_ambiguity():
    """NEEDS_HUMAN_REVIEW: Borderline, ambiguous, or qualifying phrasing routes to human review."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Security Claims Policy",
            "rule_type": "prohibited_claims",
            "directive": "Accurately state security capabilities without overpromising.",
            "is_active": True,
        }
    ]

    content = "BrandShield AI provides a virtually impenetrable security posture for modern enterprises."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 1
    r = results[0]
    assert r["status"] == ClaimStatus.NEEDS_HUMAN_REVIEW.value
    assert r["is_escalated"] is True
    assert r["confidence_score"] < 0.70
    assert "Ambiguous claim phrasing" in r["uncertainty_notes"]


@pytest.mark.asyncio
async def test_never_verify_on_simple_ngram_overlap_alone():
    """Safeguard 4: Never classify as VERIFIED using loose text or word overlap alone."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Logo Spacing Rule",
            "rule_type": "formatting",
            "directive": "Maintain 20px padding around all enterprise logos and brand assets.",
            "examples_approved": ["20px padding around logo"],
            "is_active": True,
        }
    ]

    # Content shares words "enterprise", "brand", "padding", but makes a distinct, uncorroborated metric claim
    content = "Our enterprise brand provides 20px padding for widget containers."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 1
    assert results[0]["status"] != ClaimStatus.VERIFIED.value
    assert results[0]["status"] == ClaimStatus.UNSUPPORTED.value


@pytest.mark.asyncio
async def test_evidence_provenance_never_invents_document_names():
    """Safeguard 5: Never invent document names or source citations."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "General Guideline Without Document",
            "rule_type": "factual_accuracy",
            "directive": "BrandShield AI protects over 50,000 enterprise brands worldwide.",
            "examples_approved": ["protects over 50,000 enterprise brands"],
            # Explicitly no document name
            "document_name": None,
            "source_reference": None,
            "is_active": True,
        }
    ]

    content = "BrandShield AI protects over 50,000 enterprise brands worldwide."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 1
    assert results[0]["status"] == ClaimStatus.VERIFIED.value
    assert results[0]["document_name"] is None
    assert results[0]["source_reference"] is not None  # Fallback rule title reference is allowed


@pytest.mark.asyncio
async def test_verify_claims_exclusively_active_guidelines_never_pending():
    """Safeguard 1: Inactive guidelines or unapproved candidates must NEVER be used as evidence."""
    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Pending Extraction Rule",
            "rule_type": "factual_accuracy",
            "directive": "BrandShield AI protects 1,000,000 enterprises.",
            "examples_approved": ["protects 1,000,000 enterprises"],
            "is_active": False,  # Inactive / pending
        }
    ]

    content = "BrandShield AI protects 1,000,000 enterprises."
    results = await verify_claims(content=content, guidelines=guidelines)

    assert len(results) == 1
    # Because rule is inactive, it cannot corroborate the claim
    assert results[0]["status"] == ClaimStatus.UNSUPPORTED.value


# ==============================================================================
# Dual-Mode & Gemini Fallback Resilience Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_gemini_fallback_when_unconfigured():
    """Safeguard 6: Deterministic fallback executes cleanly when Gemini is unconfigured."""
    dummy_provider = AIProvider()
    dummy_provider.gemini_key = None
    dummy_provider.openai_key = None

    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Prohibited Absolute Claims",
            "rule_type": "prohibited_claims",
            "directive": "Never guarantee 100% compliance.",
            "examples_prohibited": ["100% compliance"],
            "is_active": True,
        }
    ]

    content = "We guarantee 100% compliance across all channels."
    results = await verify_claims(content=content, guidelines=guidelines, ai_provider=dummy_provider)

    assert len(results) == 1
    assert results[0]["status"] == ClaimStatus.CONTRADICTORY.value
    assert "[Engine: deterministic_fallback (Gemini unconfigured" in results[0]["uncertainty_notes"]


@pytest.mark.asyncio
async def test_gemini_fallback_on_timeout():
    """Safeguard 6: Graceful fallback on network timeout."""
    mock_client = MagicMock()
    mock_client.generate_content = AsyncMock(side_effect=httpx.TimeoutException("Connection timed out"))

    mock_provider = MagicMock()
    mock_provider.is_available = True
    mock_provider.client = mock_client

    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Brand Fact",
            "rule_type": "factual_accuracy",
            "directive": "BrandShield AI protects over 50,000 enterprise brands worldwide.",
            "examples_approved": ["protects over 50,000 enterprise brands"],
            "is_active": True,
        }
    ]

    content = "BrandShield AI protects over 50,000 enterprise brands worldwide."
    results = await verify_claims(content=content, guidelines=guidelines, ai_provider=mock_provider)

    assert len(results) == 1
    assert results[0]["status"] == ClaimStatus.VERIFIED.value
    assert "deterministic_fallback (Gemini request timed out)" in results[0]["uncertainty_notes"]


@pytest.mark.asyncio
async def test_gemini_fallback_on_quota_exhausted():
    """Safeguard 6: Graceful fallback on DAILY_QUOTA_EXHAUSTED."""
    mock_client = MagicMock()
    mock_client.generate_content = AsyncMock(
        side_effect=GeminiClientError(
            message="Resource has been exhausted",
            error_code=GeminiErrorCode.DAILY_QUOTA_EXHAUSTED,
        )
    )

    mock_provider = MagicMock()
    mock_provider.is_available = True
    mock_provider.client = mock_client

    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Brand Fact",
            "rule_type": "factual_accuracy",
            "directive": "BrandShield AI was founded in 2021.",
            "examples_approved": ["founded in 2021"],
            "is_active": True,
        }
    ]

    content = "BrandShield AI was founded in 2021."
    results = await verify_claims(content=content, guidelines=guidelines, ai_provider=mock_provider)

    assert len(results) == 1
    assert results[0]["status"] == ClaimStatus.VERIFIED.value
    assert "DAILY_QUOTA_EXHAUSTED" in results[0]["uncertainty_notes"]


@pytest.mark.asyncio
async def test_gemini_fallback_on_invalid_json():
    """Safeguard 6: Graceful fallback on malformed JSON response from Gemini."""
    mock_client = MagicMock()
    mock_client.generate_content = AsyncMock(
        return_value={
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Sorry, I am unable to parse this content into JSON."}]
                    }
                }
            ]
        }
    )

    mock_provider = MagicMock()
    mock_provider.is_available = True
    mock_provider.client = mock_client

    guidelines = [
        {
            "id": str(uuid.uuid4()),
            "name": "Brand Fact",
            "rule_type": "factual_accuracy",
            "directive": "BrandShield AI was founded in 2021.",
            "examples_approved": ["founded in 2021"],
            "is_active": True,
        }
    ]

    content = "BrandShield AI was founded in 2021."
    results = await verify_claims(content=content, guidelines=guidelines, ai_provider=mock_provider)

    assert len(results) == 1
    assert results[0]["status"] == ClaimStatus.VERIFIED.value
    assert "deterministic_fallback" in results[0]["uncertainty_notes"]


# ==============================================================================
# End-to-End Pipeline, Database Persistence & Audit Integrity Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_end_to_end_inspection_with_claim_verifications_persistence(claim_test_db):
    """End-to-end pipeline: evaluates content, persists report and ClaimVerification rows."""
    session = claim_test_db["session"]
    org = claim_test_db["org1"]
    admin = claim_test_db["admin"]

    # Active Guidelines in Org 1
    gl_facts = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Enterprise Scale Standards",
        rule_type="factual_accuracy",
        severity="high",
        directive="BrandShield AI protects over 50,000 enterprise brands worldwide.",
        description="Core scale metric",
        examples_approved=["protects over 50,000 enterprise brands"],
        examples_prohibited=[],
        is_active=True,
    )
    gl_claims = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Absolute Performance Prohibition",
        rule_type="prohibited_claims",
        severity="critical",
        directive="Never guarantee 100% brand safety or zero risk.",
        description="Advertising legal standard",
        examples_approved=["substantially reduces brand risk"],
        examples_prohibited=["guarantee 100% brand safety", "100% infallible"],
        is_active=True,
    )
    session.add_all([gl_facts, gl_claims])
    await session.flush()

    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Marketing Press Release",
        content="BrandShield AI protects over 50,000 enterprise brands worldwide. We guarantee 100% brand safety across every digital channel.",
        target_channel="press_release",
        target_audience="general",
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    session.add(submission)
    await session.flush()

    # Run inspection
    report = await compliance_engine.run_inspection(
        session=session,
        submission=submission,
        actor=admin,
    )

    assert report is not None
    assert report.is_compliant is False
    assert report.is_escalated is True  # Escalated due to critical violation / contradictory claim
    assert len(report.claim_verifications) >= 2

    # Verify claim verifications in database
    claims_stmt = select(ClaimVerification).where(ClaimVerification.report_id == report.id)
    db_claims = (await session.execute(claims_stmt)).scalars().all()
    assert len(db_claims) >= 2

    statuses = {c.status for c in db_claims}
    assert ClaimStatus.VERIFIED.value in statuses
    assert ClaimStatus.CONTRADICTORY.value in statuses

    verified_c = next(c for c in db_claims if c.status == ClaimStatus.VERIFIED.value)
    assert verified_c.organization_id == org.id
    assert verified_c.confidence_score >= 0.85
    assert verified_c.evidence is not None

    contra_c = next(c for c in db_claims if c.status == ClaimStatus.CONTRADICTORY.value)
    assert contra_c.organization_id == org.id
    assert contra_c.is_escalated is True

    # Verify audit ledger entry
    audit_stmt = (
        select(AuditEntry)
        .where(AuditEntry.submission_id == submission.id)
        .order_by(AuditEntry.timestamp.desc())
    )
    audit = (await session.execute(audit_stmt)).scalars().first()
    assert audit is not None
    assert audit.details["claims_evaluated_count"] >= 2
    assert audit.details["claims_verified_count"] >= 1
    assert audit.details["claims_contradictory_count"] >= 1


@pytest.mark.asyncio
async def test_claim_verification_cascade_deletion(claim_test_db):
    """Safeguard 9 & Milestone 1: Deleting a ComplianceReport cascades and deletes its ClaimVerification records."""
    session = claim_test_db["session"]
    org = claim_test_db["org1"]

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Cascade Test Submission",
        content="Testing cascade deletion.",
        target_channel="web",
        target_audience="general",
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    session.add(sub)
    await session.flush()

    rep = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Test report",
        risk_score=0.0,
        risk_level="LOW",
        is_escalated=False,
    )
    session.add(rep)
    await session.flush()

    claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org.id,
        report_id=rep.id,
        claim_text="BrandShield AI protects 50,000 brands.",
        status=ClaimStatus.VERIFIED.value,
        confidence_score=1.0,
    )
    session.add(claim)
    await session.flush()

    # Confirm claim exists
    assert (await session.execute(select(ClaimVerification).where(ClaimVerification.id == claim.id))).scalar_one_or_none() is not None

    # Delete Report
    await session.delete(rep)
    await session.flush()

    # Verify ClaimVerification was deleted by CASCADE
    assert (await session.execute(select(ClaimVerification).where(ClaimVerification.id == claim.id))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_cross_tenant_isolation_in_claim_verification(claim_test_db):
    """Safeguard 8: Tenant A guidelines must never verify Tenant B claims; mismatched organization_id fails."""
    session = claim_test_db["session"]
    org1 = claim_test_db["org1"]
    org2 = claim_test_db["org2"]

    # Org 1 has secret fact
    gl_org1 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org1.id,
        name="Org1 Secret Metric",
        rule_type="factual_accuracy",
        description="Org1 secret uptime metric",
        directive="Alpha Corp secures 99.999% uptime for Tier 1 defense clients.",
        examples_approved=["secures 99.999% uptime"],
        is_active=True,
    )
    session.add(gl_org1)
    await session.flush()

    # Org 2 submission asserts Org 1's fact
    sub_org2 = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org2.id,
        title="Org2 Submission",
        content="Alpha Corp secures 99.999% uptime for Tier 1 defense clients.",
        target_channel="web",
        target_audience="general",
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    session.add(sub_org2)
    await session.flush()

    # Run inspection under Org 2
    report_org2 = await compliance_engine.run_inspection(session=session, submission=sub_org2)

    # For Org 2, Org 1's guideline does NOT exist; claim must be UNSUPPORTED, never VERIFIED!
    assert len(report_org2.claim_verifications) >= 1
    assert report_org2.claim_verifications[0].status == ClaimStatus.UNSUPPORTED.value

    # Cross-tenant insertion attempt (claim org2 pointing to report org1) must be rejected by ORM listener
    rep_org1 = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_org2.id,  # belongs to org2
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Test",
        risk_score=0.0,
        risk_level="LOW",
        is_escalated=False,
    )
    session.add(rep_org1)
    await session.flush()

    mismatched_claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org1.id,  # Mismatched! Belongs to org1 while report is org2
        report_id=rep_org1.id,
        claim_text="Mismatched cross-tenant claim",
        status=ClaimStatus.UNSUPPORTED.value,
    )
    session.add(mismatched_claim)

    with pytest.raises(ValueError, match="Cross-tenant integrity violation"):
        await session.flush()
    await session.rollback()


# ==============================================================================
# API Endpoint Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_report_and_claims_endpoints(claim_test_db):
    """GET /submissions/{id}/report and GET /submissions/{id}/claims serialize claims correctly."""
    session = claim_test_db["session"]
    org = claim_test_db["org1"]
    admin = claim_test_db["admin"]

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="API Claims Test",
        content="BrandShield AI protects over 50,000 enterprise brands worldwide.",
        target_channel="web",
        target_audience="general",
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    session.add(sub)
    await session.flush()

    rep = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="API Test Report",
        risk_score=10.0,
        risk_level="LOW",
        is_escalated=False,
    )
    session.add(rep)
    await session.flush()

    claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org.id,
        report_id=rep.id,
        claim_text="BrandShield AI protects over 50,000 enterprise brands worldwide.",
        status=ClaimStatus.VERIFIED.value,
        confidence_score=0.98,
        evidence="Corporate Factsheet 2026",
        source_reference="Section 1",
        document_name="BrandGuidelines.pdf",
        uncertainty_notes="Fully verified against brand knowledge.",
        is_escalated=False,
    )
    session.add(claim)
    await session.flush()

    token = create_access_token(
        subject=str(admin.id),
        org_id=str(org.id),
        role=admin.role,
        email=admin.email,
        full_name=admin.full_name,
    )
    headers = {"Authorization": f"Bearer {token}"}

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Test /submissions/{id}/report
            res_rep = await client.get(f"/api/v1/submissions/{sub.id}/report", headers=headers)
            assert res_rep.status_code == 200
            data_rep = res_rep.json()
            assert "claim_verifications" in data_rep
            assert len(data_rep["claim_verifications"]) == 1
            c_data = data_rep["claim_verifications"][0]
            assert c_data["claim_text"] == claim.claim_text
            assert c_data["status"] == "VERIFIED"
            assert c_data["confidence_score"] == 0.98
            assert c_data["document_name"] == "BrandGuidelines.pdf"

            # 2. Test /submissions/{id}/claims
            res_claims = await client.get(f"/api/v1/submissions/{sub.id}/claims", headers=headers)
            assert res_claims.status_code == 200
            claims_list = res_claims.json()
            assert isinstance(claims_list, list)
            assert len(claims_list) == 1
            assert claims_list[0]["id"] == str(claim.id)
            assert claims_list[0]["status"] == "VERIFIED"

    finally:
        app.dependency_overrides.clear()
