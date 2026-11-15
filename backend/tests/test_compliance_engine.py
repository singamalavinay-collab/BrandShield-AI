from datetime import datetime, timezone
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.engine.ai_provider import ai_provider
from app.engine.evaluator import compliance_engine
from app.main import app
from app.models.compliance import ComplianceReport, CorrectionSuggestion, EvidenceCitation, RuleViolation
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.review import AuditEntry
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.common import RuleType, SeverityLevel, SubmissionStatus, TargetChannel


@pytest_asyncio.fixture
async def engine_session():
    """Isolated async SQLite engine and database session for engine tests."""
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
        # Organization 1 (Primary tenant)
        org1 = Organization(
            id=uuid.uuid4(),
            name="Acme Corporation",
            slug="acme-corp",
            is_active=True,
        )
        session.add(org1)

        # Organization 2 (Secondary tenant for isolation checks)
        org2 = Organization(
            id=uuid.uuid4(),
            name="Beta Industries",
            slug="beta-industries",
            is_active=True,
        )
        session.add(org2)
        await session.flush()

        # User in Org 1
        reviewer = User(
            id=uuid.uuid4(),
            organization_id=org1.id,
            email="lead.reviewer@acme.com",
            hashed_password=get_password_hash("ValidPass123!"),
            full_name="Lead Brand Reviewer",
            role="REVIEWER",
            is_active=True,
        )
        session.add(reviewer)

        # Active Rule 1 in Org 1: Trademark Capitalization
        rule_trademark = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org1.id,
            name="BrandShield AI Capitalization & Spacing",
            rule_type=RuleType.TRADEMARK_USAGE.value,
            severity=SeverityLevel.HIGH.value,
            directive="The official product brand name must always be spelled strictly as 'BrandShield AI'. Never lowercase as 'brandshield ai'.",
            description="Protect trademark integrity across public distribution channels.",
            examples_approved=["BrandShield AI delivers comprehensive compliance monitoring."],
            examples_prohibited=["brandshield ai", "Brandshield AI"],
            tags=["trademark", "branding"],
            is_active=True,
        )
        session.add(rule_trademark)

        # Active Rule 2 in Org 1: Prohibited Absolute Claims
        rule_claims = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org1.id,
            name="Absolute Security & Infallibility Claims Prohibition",
            rule_type=RuleType.PROHIBITED_CLAIMS.value,
            severity=SeverityLevel.CRITICAL.value,
            directive="Do not state that our platform is '100% infallible' or 'guarantees zero risk'. Qualified risk statements must be used.",
            description="Prevent false advertising liability and regulatory sanctions.",
            examples_approved=["substantially reduces brand risk across modern channels"],
            examples_prohibited=["100% infallible", "guaranteed zero risk"],
            tags=["legal", "compliance", "claims"],
            is_active=True,
        )
        session.add(rule_claims)

        # Active Rule 3 in Org 1: Mandatory Governance Disclosure
        rule_disclosure = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org1.id,
            name="Mandatory Human-in-the-Loop Governance Notice",
            rule_type=RuleType.LEGAL_REGULATORY.value,
            severity=SeverityLevel.CRITICAL.value,
            directive="All AI-generated brand copy must explicitly acknowledge human-in-the-loop authorization before publication.",
            description="Regulatory transparency compliance.",
            examples_approved=["All recommendations require human-in-the-loop authorization."],
            examples_prohibited=["Posts to social media without human delay."],
            tags=["regulatory", "human-in-the-loop"],
            is_active=True,
        )
        session.add(rule_disclosure)

        # Inactive Rule in Org 1: Should NOT trigger violations
        rule_inactive = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org1.id,
            name="Deprecated Inactive Rule",
            rule_type=RuleType.TERMINOLOGY.value,
            severity=SeverityLevel.LOW.value,
            directive="Do not use the word 'legacy' when describing customer systems.",
            description="Former messaging directive.",
            is_active=False,
        )
        session.add(rule_inactive)

        # Rule in Org 2: Should NOT be evaluated for Org 1 submissions (Tenant Isolation)
        rule_org2 = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org2.id,
            name="Org 2 Competitor Rule",
            rule_type=RuleType.COMPETITOR_REFERENCE.value,
            severity=SeverityLevel.HIGH.value,
            directive="Do not mention CompetitorX in promotional marketing.",
            description="Org 2 specific policy.",
            is_active=True,
        )
        session.add(rule_org2)

        await session.commit()
        yield session

    await test_engine.dispose()


@pytest_asyncio.fixture
async def engine_client(engine_session: AsyncSession):
    """Authenticated AsyncClient for API lifecycle tests."""
    res = await engine_session.execute(select(User).where(User.email == "lead.reviewer@acme.com"))
    user = res.scalar_one()

    token = create_access_token(
        subject=str(user.id),
        org_id=str(user.organization_id),
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )

    async def override_get_db():
        yield engine_session

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
# 1. Deterministic Rule & Grounding Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_compliant_content_passes_checks(engine_session: AsyncSession):
    """Verify compliant content produces 0 violations, is_compliant=True, and passed_checks status."""
    res = await engine_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org = res.scalar_one()

    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Compliant Corporate Announcement",
        content="BrandShield AI delivers comprehensive compliance monitoring with human-in-the-loop authorization.",
        target_channel=TargetChannel.EMAIL_NEWSLETTER.value,
        target_audience="Enterprise Executives",
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(submission)
    await engine_session.flush()

    report = await compliance_engine.run_inspection(session=engine_session, submission=submission)

    assert report.is_compliant is True
    assert report.total_violations == 0
    assert len(report.violations) == 0
    assert submission.status == SubmissionStatus.PASSED_CHECKS.value

    # Verify audit entry recorded
    audit_res = await engine_session.execute(
        select(AuditEntry).where(AuditEntry.submission_id == submission.id)
    )
    audit = audit_res.scalar_one()
    assert audit.action_type == "automated_compliance_inspection"
    assert audit.new_status == SubmissionStatus.PASSED_CHECKS.value


@pytest.mark.asyncio
async def test_trademark_capitalization_violation_detected(engine_session: AsyncSession):
    """Verify trademark casing violation is flagged with exact offsets, verbatim directive citation, and suggestion."""
    res = await engine_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org = res.scalar_one()

    sub_content = "We are proud to announce that brandshield ai has launched."
    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Social Post Announcement",
        content=sub_content,
        target_channel=TargetChannel.TWITTER_X.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(submission)
    await engine_session.flush()

    report = await compliance_engine.run_inspection(session=engine_session, submission=submission)

    assert report.is_compliant is False
    assert report.total_violations >= 1
    assert submission.status == SubmissionStatus.VIOLATIONS_FOUND.value

    # Find trademark violation
    tm_violations = [v for v in report.violations if v.rule_type == RuleType.TRADEMARK_USAGE.value]
    assert len(tm_violations) == 1
    v = tm_violations[0]
    assert v.flagged_text.lower() == "brandshield ai"
    assert v.severity == SeverityLevel.HIGH.value
    assert v.char_start is not None and v.char_end is not None
    assert sub_content[v.char_start:v.char_end].lower() == "brandshield ai"

    # Verifiable evidence citation
    assert len(v.evidence_citations) >= 1
    citation = v.evidence_citations[0]
    assert "strictly as 'BrandShield AI'" in citation.source_clause
    assert citation.confidence_score >= 0.95

    # Grounded suggestion with provenance
    assert len(v.suggestions) >= 1
    suggestion = v.suggestions[0]
    assert suggestion.suggested_text == "BrandShield AI"
    assert suggestion.source == "rule_derived"


@pytest.mark.asyncio
async def test_prohibited_claims_detected(engine_session: AsyncSession):
    """Verify absolute claim '100% infallible' is flagged as critical severity with legal directive citation."""
    res = await engine_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org = res.scalar_one()

    sub_content = "Our security architecture is 100% infallible against all attacks."
    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Security Blog Post",
        content=sub_content,
        target_channel=TargetChannel.LINKEDIN.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(submission)
    await engine_session.flush()

    report = await compliance_engine.run_inspection(session=engine_session, submission=submission)

    assert report.is_compliant is False
    claims_viols = [v for v in report.violations if v.rule_type == RuleType.PROHIBITED_CLAIMS.value]
    assert len(claims_viols) >= 1
    v = claims_viols[0]
    assert "100% infallible" in v.flagged_text.lower()
    assert v.severity == SeverityLevel.CRITICAL.value

    # Verifiable source clause citation
    citation = v.evidence_citations[0]
    assert "Do not state that our platform is '100% infallible'" in citation.source_clause
    assert citation.confidence_score >= 0.90


@pytest.mark.asyncio
async def test_multiple_violations_detected(engine_session: AsyncSession):
    """Verify content with both trademark casing and prohibited claims violations produces multiple grounded violations."""
    res = await engine_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org = res.scalar_one()

    sub_content = "brandshield ai provides a 100% infallible protection layer for your brand."
    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Multi-violation Draft",
        content=sub_content,
        target_channel=TargetChannel.TWITTER_X.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(submission)
    await engine_session.flush()

    report = await compliance_engine.run_inspection(session=engine_session, submission=submission)

    assert report.is_compliant is False
    assert report.total_violations >= 2

    rule_types = {v.rule_type for v in report.violations}
    assert RuleType.TRADEMARK_USAGE.value in rule_types
    assert RuleType.PROHIBITED_CLAIMS.value in rule_types


@pytest.mark.asyncio
async def test_inactive_guidelines_ignored(engine_session: AsyncSession):
    """Verify that guidelines with is_active=False are not evaluated and trigger no violations."""
    res = await engine_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org = res.scalar_one()

    # Content contains 'legacy systems', which matches inactive Rule 'Deprecated Inactive Rule'
    sub_content = "BrandShield AI seamlessly integrates with legacy enterprise databases."
    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Integration Guide",
        content=sub_content,
        target_channel=TargetChannel.EMAIL_NEWSLETTER.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(submission)
    await engine_session.flush()

    report = await compliance_engine.run_inspection(session=engine_session, submission=submission)

    # Inactive rule must not trigger any violation
    inactive_violations = [v for v in report.violations if "legacy" in v.flagged_text.lower()]
    assert len(inactive_violations) == 0


@pytest.mark.asyncio
async def test_tenant_isolation_in_inspection(engine_session: AsyncSession):
    """Verify that guidelines belonging to Org 2 are not evaluated for an Org 1 submission."""
    res = await engine_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org1 = res.scalar_one()

    # Org 2 has a rule against mentioning CompetitorX; Org 1 does NOT have that rule
    sub_content = "BrandShield AI outperforms CompetitorX in automated compliance velocity."
    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org1.id,
        title="Comparison Analysis",
        content=sub_content,
        target_channel=TargetChannel.LINKEDIN.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(submission)
    await engine_session.flush()

    report = await compliance_engine.run_inspection(session=engine_session, submission=submission)

    # Competitor rule from Org 2 must NOT be applied to Org 1
    competitor_violations = [
        v for v in report.violations if v.rule_type == RuleType.COMPETITOR_REFERENCE.value
    ]
    assert len(competitor_violations) == 0


@pytest.mark.asyncio
async def test_evidence_citation_verbatim_grounding(engine_session: AsyncSession):
    """Verify all evidence citations contain verbatim directive text and valid confidence score."""
    res = await engine_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org = res.scalar_one()

    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Evidence Grounding Test",
        content="brandshield ai guarantees zero risk across modern channels.",
        target_channel=TargetChannel.TWITTER_X.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(submission)
    await engine_session.flush()

    report = await compliance_engine.run_inspection(session=engine_session, submission=submission)

    for v in report.violations:
        assert len(v.evidence_citations) >= 1
        for citation in v.evidence_citations:
            assert citation.rule_id == v.rule_id
            assert len(citation.source_clause.strip()) > 5
            assert 0.0 <= citation.confidence_score <= 1.0


@pytest.mark.asyncio
async def test_suggestion_provenance_tagging(engine_session: AsyncSession):
    """Verify suggestions created by deterministic detectors carry strict rule_derived provenance."""
    res = await engine_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    org = res.scalar_one()

    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Provenance Test",
        content="Welcome to brandshield ai platform.",
        target_channel=TargetChannel.TWITTER_X.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(submission)
    await engine_session.flush()

    report = await compliance_engine.run_inspection(session=engine_session, submission=submission)

    for v in report.violations:
        for sug in v.suggestions:
            # Must be labeled rule_derived, NOT ai_generated
            assert sug.source == "rule_derived"
            assert len(sug.suggested_text.strip()) > 0
            assert len(sug.rationale.strip()) > 0


@pytest.mark.asyncio
async def test_ai_provider_unconfigured_graceful_handling():
    """Verify AI provider accurately reports lack of API keys without fabricating synthetic hallucinations."""
    # When keys are absent
    status = ai_provider.get_provider_status()
    assert "gemini_configured" in status
    assert "openai_configured" in status

    # Evaluator handles lack of key without crashing
    result = await ai_provider.evaluate_semantic_nuance(
        content="Sample content draft.",
        guidelines=[],
    )
    assert result["ai_available"] is False
    assert result["reasoning_applied"] is False
    assert "API key" in result["status_note"]


# ==============================================================================
# 2. End-to-End API Lifecycle Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_full_inspection_api_lifecycle(engine_client: AsyncClient):
    """End-to-end API test: create submission -> trigger /analyze -> retrieve /report -> verify report schema."""
    # 1. Create draft
    create_res = await engine_client.post(
        "/api/v1/submissions",
        json={
            "title": "API Lifecycle Announcement",
            "content": "Discover how brandshield ai guarantees zero risk for marketing teams.",
            "target_channel": "twitter_x",
            "target_audience": "Chief Marketing Officers",
        },
    )
    assert create_res.status_code == 201
    sub_data = create_res.json()
    sub_id = sub_data["id"]
    assert sub_data["status"] == "draft"

    # 2. Trigger analysis via POST /api/v1/submissions/{id}/analyze
    analyze_res = await engine_client.post(f"/api/v1/submissions/{sub_id}/analyze")
    assert analyze_res.status_code == 200
    analyzed_sub = analyze_res.json()
    assert analyzed_sub["status"] == "violations_found"

    # 3. Retrieve report via GET /api/v1/submissions/{id}/report
    report_res = await engine_client.get(f"/api/v1/submissions/{sub_id}/report")
    assert report_res.status_code == 200
    report_data = report_res.json()

    assert report_data["is_analyzed"] is True
    assert report_data["status"] == "completed"
    assert report_data["is_compliant"] is False
    assert report_data["total_violations"] >= 2
    assert len(report_data["violations"]) >= 2
    assert "remediated_draft" in report_data
    assert "remediation_summary" in report_data
    assert report_data["remediation_summary"]["total_violations"] == len(report_data["violations"])
    assert report_data["remediation_summary"]["remediated_violations"] >= 1

    # Verify violation fields and citations in API response
    first_viol = report_data["violations"][0]
    assert "flagged_text" in first_viol
    assert "rule_name" in first_viol
    assert "severity" in first_viol
    assert "evidence_citations" in first_viol
    assert len(first_viol["evidence_citations"]) >= 1
    assert "source_clause" in first_viol["evidence_citations"][0]

    # 4. Retrieve violations via GET /api/v1/submissions/{id}/violations
    viols_res = await engine_client.get(f"/api/v1/submissions/{sub_id}/violations")
    assert viols_res.status_code == 200
    assert len(viols_res.json()) >= 2

    # 5. Retrieve suggestions via GET /api/v1/submissions/{id}/suggestions
    suggs_res = await engine_client.get(f"/api/v1/submissions/{sub_id}/suggestions")
    assert suggs_res.status_code == 200
    suggestions = suggs_res.json()
    assert len(suggestions) >= 1
    assert all(s["source"] == "rule_derived" for s in suggestions)


@pytest.mark.asyncio
async def test_cannot_analyze_approved_submission(engine_client: AsyncClient):
    """Verify that attempting to analyze an approved submission returns 400 Bad Request."""
    # 1. Create compliant submission
    create_res = await engine_client.post(
        "/api/v1/submissions",
        json={
            "title": "Already Approved Post",
            "content": "BrandShield AI delivers reliable monitoring with human-in-the-loop authorization.",
            "target_channel": "linkedin",
        },
    )
    sub_id = create_res.json()["id"]

    # 2. Analyze -> passed_checks
    await engine_client.post(f"/api/v1/submissions/{sub_id}/analyze")

    # 3. Advance to review
    await engine_client.post(f"/api/v1/submissions/{sub_id}/advance-to-review")

    # 4. Human approves
    review_res = await engine_client.post(
        f"/api/v1/submissions/{sub_id}/review",
        json={"action": "approve", "feedback": "Approved by lead reviewer."},
    )
    assert review_res.status_code == 200
    assert review_res.json()["submission"]["status"] == "approved"

    # 5. Attempt to re-analyze approved content -> Must return 400
    fail_res = await engine_client.post(f"/api/v1/submissions/{sub_id}/analyze")
    assert fail_res.status_code == 400
    assert "Human review decision has already been finalized" in fail_res.json()["message"]


# ==============================================================================
# Regression Tests for Phase 4 Inspection Workflow
# ==============================================================================

@pytest.mark.asyncio
async def test_inspection_with_zero_guidelines_reports_not_compliant_and_aborts_status(
    engine_session: AsyncSession,
):
    """Verify that inspecting content with zero active guidelines does not falsely declare compliance."""
    # 1. Create org and submission with NO guidelines
    org = Organization(
        id=uuid.uuid4(),
        name="Empty Org",
        slug="empty-org",
        is_active=True,
    )
    engine_session.add(org)
    await engine_session.flush()

    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Draft in Empty Org",
        content="Some content that has no applicable guidelines.",
        target_channel=TargetChannel.TWITTER_X.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(sub)
    await engine_session.flush()

    # 2. Run inspection
    report = await compliance_engine.run_inspection(session=engine_session, submission=sub)

    # 3. Assert invariants
    assert report.is_compliant is False, "Empty guidelines must NEVER be reported as compliant"
    assert report.total_violations == 0
    assert "No active brand guidelines are configured" in report.summary
    assert sub.status == SubmissionStatus.SUBMITTED.value, "Must not advance to passed_checks without rules"


@pytest.mark.asyncio
async def test_sample_with_violations_content_detects_all_five_violations(
    engine_session: AsyncSession,
):
    """Verify that the standard test sample flags all 5 distinct violation categories:
    1. Trademark casing ('Brandshield' -> 'BrandShield AI')
    2. Tone of voice ('revolutionary miracle' -> objective copy)
    3. Prohibited claims ('guarantees 100% brand compliance' -> qualified copy)
    4. Regulatory governance ('automatically posts to socialmedia without any human delay')
    5. Formatting & terminology ('socialmedia' -> 'social media')
    """
    # 1. Setup organization
    org = Organization(
        id=uuid.uuid4(),
        name="BrandShield Benchmark Org",
        slug="brandshield-benchmark",
        is_active=True,
    )
    engine_session.add(org)
    await engine_session.flush()

    # 2. Seed the 5 standard brand guidelines
    g1 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="BrandShield AI Capitalization & Spacing",
        rule_type=RuleType.TRADEMARK_USAGE.value,
        severity=SeverityLevel.CRITICAL.value,
        description="Enforces correct camel-case spelling and spacing for BrandShield AI.",
        directive='Always spell as two words: "BrandShield" (one word, capital B and S) followed by a space and "AI". Never write as "Brandshield", "Brand Shield", or "BrandshieldAI".',
        examples_approved=["BrandShield AI protects enterprise brand integrity."],
        examples_prohibited=["Brandshield provides brand checking.", "Brand Shield AI is easy to set up."],
        tags=["trademark", "naming"],
        is_active=True,
    )
    g2 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Absolute Security Claim Prohibition",
        rule_type=RuleType.PROHIBITED_CLAIMS.value,
        severity=SeverityLevel.HIGH.value,
        description="Prohibits unqualified guarantees of 100% compliance or absolute immunity from violations.",
        directive="Never state that BrandShield AI guarantees 100% violation-free output or replaces human legal counsel.",
        examples_approved=["Substantially reduces brand guideline deviations by over 90%."],
        examples_prohibited=["Guarantees 100% brand safety on every channel.", "Guarantees 100% brand compliance everywhere."],
        tags=["legal", "claims"],
        is_active=True,
    )
    g3 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Empowering & Authoritative Tone of Voice",
        rule_type=RuleType.TONE_OF_VOICE.value,
        severity=SeverityLevel.MEDIUM.value,
        description="Maintains professional, confident, yet humble tone avoiding exaggerated buzzwords.",
        directive='Maintain an empowering, objective tone. Avoid hyperbolic jargon such as "game-changer", "revolutionary miracle", or "unmatched magic".',
        examples_approved=["BrandShield AI provides rigorous governance for modern enterprise brands."],
        examples_prohibited=["Our revolutionary miracle AI tool guarantees 100% brand compliance everywhere."],
        tags=["tone", "messaging"],
        is_active=True,
    )
    g4 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Mandatory Human-in-the-Loop Governance Notice",
        rule_type=RuleType.LEGAL_REGULATORY.value,
        severity=SeverityLevel.CRITICAL.value,
        description="Requires explicit mention that AI proposals require human approval before publishing.",
        directive="Any public release describing automated workflows must explicitly state that human brand officers retain final approval authority.",
        examples_approved=["AI proposes corrections; human officers authorize publication."],
        examples_prohibited=["It automatically posts to socialmedia without any human delay!"],
        tags=["governance", "regulatory"],
        is_active=True,
    )
    g5 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Standard Formatting & Terminology",
        rule_type=RuleType.FORMATTING.value,
        severity=SeverityLevel.LOW.value,
        description="Standardizes technical terms and punctuation conventions.",
        directive='Use "social media" (two words, lowercase), "real-time" (hyphenated when modifying a noun), and avoid all-caps shout words.',
        examples_approved=["Delivers real-time alerts across social media channels."],
        examples_prohibited=["automatically posts to socialmedia without any human delay"],
        tags=["formatting", "style"],
        is_active=True,
    )
    engine_session.add_all([g1, g2, g3, g4, g5])
    await engine_session.flush()

    # 3. Create submission with the target test content
    target_content = (
        "We are excited to launch Brandshield! Our revolutionary miracle AI tool guarantees 100% brand compliance everywhere. "
        "It automatically posts to socialmedia without any human delay!"
    )
    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Q2 Launch Announcement with Multiple Violations",
        content=target_content,
        target_channel=TargetChannel.TWITTER_X.value,
        target_audience="Enterprise Executives",
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(sub)
    await engine_session.flush()

    # 4. Execute inspection
    report = await compliance_engine.run_inspection(session=engine_session, submission=sub)

    # 5. Assert report properties
    assert report.is_compliant is False
    assert report.total_violations >= 5, f"Expected at least 5 violations, got {report.total_violations}"
    assert sub.status == SubmissionStatus.VIOLATIONS_FOUND.value

    # 6. Verify each violation has exact flagged text and grounded citations
    flagged_texts = {v.flagged_text for v in report.violations}
    rule_types = {v.rule_type for v in report.violations}

    # Verify all 5 violation types are present
    assert "trademark_usage" in rule_types
    assert "prohibited_claims" in rule_types
    assert "tone_of_voice" in rule_types
    assert "legal_regulatory" in rule_types
    assert "formatting" in rule_types

    # Verify flagged texts match expected segments
    assert any("Brandshield" in t for t in flagged_texts), f"Missing trademark violation in {flagged_texts}"
    assert any("revolutionary miracle" in t for t in flagged_texts), f"Missing tone violation in {flagged_texts}"
    assert any("100%" in t for t in flagged_texts), f"Missing claim violation in {flagged_texts}"
    assert any("without" in t and "human" in t for t in flagged_texts), f"Missing governance violation in {flagged_texts}"
    assert any("socialmedia" in t for t in flagged_texts), f"Missing formatting violation in {flagged_texts}"

    # Verify citations and suggestions exist on each violation
    for v in report.violations:
        assert len(v.evidence_citations) >= 1
        assert v.evidence_citations[0].source_clause
        assert len(v.suggestions) >= 1
        assert v.suggestions[0].suggested_text
        assert v.suggestions[0].source == "rule_derived"


@pytest.mark.asyncio
async def test_remediation_synthesizer_resolves_all_overlapping_violations(engine_session: AsyncSession):
    """Verify that remediation synthesizer handles overlapping and nested violations cleanly,
    generating a coherent draft with 100% resolution and 0 unresolved infractions."""
    from app.engine.remediator import remediation_synthesizer

    # 1. Dedicated test tenant organization
    org = Organization(
        id=uuid.uuid4(),
        name="Gamma Innovations",
        slug=f"gamma-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    engine_session.add(org)
    await engine_session.flush()

    # 2. Add the 5 rules for the multi-violation test
    g1 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="BrandShield AI Trademark & Capitalization",
        rule_type=RuleType.TRADEMARK_USAGE.value,
        severity=SeverityLevel.HIGH.value,
        directive="The official product name must always be capitalized as 'BrandShield AI'. Never write 'Brandshield' or 'brandshield'.",
        description="Enforces exact trademark capitalization.",
        examples_approved=["BrandShield AI provides governance."],
        examples_prohibited=["Brandshield", "brandshield"],
        tags=["trademark", "branding"],
        is_active=True,
    )
    g2 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Absolute Performance Claims Prohibition",
        rule_type=RuleType.PROHIBITED_CLAIMS.value,
        severity=SeverityLevel.CRITICAL.value,
        directive="Never state that the platform 'guarantees 100% brand compliance' or offers 'zero risk'. Use defensible qualified claims.",
        description="Prohibits non-defensible absolute claims.",
        examples_approved=["substantially elevates brand compliance across modern channels"],
        examples_prohibited=["guarantees 100% brand compliance everywhere", "100% brand compliance"],
        tags=["legal", "compliance"],
        is_active=True,
    )
    g3 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Enterprise Tone of Voice",
        rule_type=RuleType.TONE_OF_VOICE.value,
        severity=SeverityLevel.MEDIUM.value,
        directive="Maintain an authoritative, measured, and professional tone. Avoid sensationalist hyperbole such as 'revolutionary miracle'.",
        description="Preserves enterprise-grade credibility.",
        examples_approved=["BrandShield AI provides rigorous governance."],
        examples_prohibited=["revolutionary miracle"],
        tags=["tone", "messaging"],
        is_active=True,
    )
    g4 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Mandatory Human-in-the-Loop Governance Notice",
        rule_type=RuleType.LEGAL_REGULATORY.value,
        severity=SeverityLevel.CRITICAL.value,
        directive="Any public release describing automated workflows must explicitly state that human brand officers retain final approval authority.",
        description="Requires human-in-the-loop governance statements.",
        examples_approved=["AI proposes corrections; human officers authorize publication."],
        examples_prohibited=["It automatically posts to socialmedia without any human delay!"],
        tags=["governance", "regulatory"],
        is_active=True,
    )
    g5 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Standard Formatting & Terminology",
        rule_type=RuleType.FORMATTING.value,
        severity=SeverityLevel.LOW.value,
        directive='Use "social media" (two words, lowercase), "real-time" (hyphenated when modifying a noun), and avoid all-caps shout words.',
        description="Standardizes terminology.",
        examples_approved=["Delivers real-time alerts across social media channels."],
        examples_prohibited=["automatically posts to socialmedia without any human delay"],
        tags=["formatting", "style"],
        is_active=True,
    )
    engine_session.add_all([g1, g2, g3, g4, g5])
    await engine_session.flush()

    target_content = (
        "We are excited to launch Brandshield! Our revolutionary miracle AI tool guarantees 100% brand compliance everywhere. "
        "It automatically posts to socialmedia without any human delay!"
    )
    sub = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Overlapping Violations Remediation Test",
        content=target_content,
        target_channel=TargetChannel.TWITTER_X.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    engine_session.add(sub)
    await engine_session.flush()

    report = await compliance_engine.run_inspection(session=engine_session, submission=sub)
    assert report.total_violations >= 5

    serialized_guidelines = [
        {
            "id": str(g.id),
            "name": g.name,
            "rule_type": g.rule_type,
            "severity": g.severity,
            "description": g.description,
            "directive": g.directive,
            "examples_approved": g.examples_approved or [],
            "examples_prohibited": g.examples_prohibited or [],
            "is_active": g.is_active,
        }
        for g in [g1, g2, g3, g4, g5]
    ]

    formatted_violations = [
        {
            "id": str(v.id),
            "rule_id": str(v.rule_id),
            "rule_name": v.rule_name,
            "rule_type": v.rule_type,
            "severity": v.severity,
            "flagged_text": v.flagged_text,
            "char_start": v.char_start,
            "char_end": v.char_end,
            "explanation": v.explanation,
            "suggestions": [
                {
                    "id": str(s.id),
                    "violation_id": str(v.id),
                    "suggested_text": s.suggested_text,
                    "rationale": s.rationale,
                    "source": s.source,
                }
                for s in v.suggestions
            ],
            "evidence_citations": [
                {
                    "id": str(c.id),
                    "violation_id": str(v.id),
                    "rule_id": str(c.rule_id),
                    "rule_name": c.rule_name,
                    "rule_type": c.rule_type,
                    "source_clause": c.source_clause,
                    "document_name": c.document_name,
                    "confidence_score": c.confidence_score,
                }
                for c in v.evidence_citations
            ],
        }
        for v in report.violations
    ]

    remediation = remediation_synthesizer.synthesize_remediated_draft(
        content=target_content,
        violations=formatted_violations,
        guidelines=serialized_guidelines,
    )

    remediated_draft = remediation["remediated_draft"]
    # 1. Assert accurate count accounting
    assert remediation["total_violations"] == len(formatted_violations)
    assert remediation["remediated_violations"] == len(formatted_violations)
    assert remediation["unresolved_violations"] == 0
    assert remediation["is_fully_remediated"] is True
    assert remediation["new_violations_detected"] == 0

    # 2. Assert text quality and natural phrasing
    assert "BrandShield AI" in remediated_draft
    assert "Brandshield" not in remediated_draft
    assert "guarantees 100%" not in remediated_draft
    assert "revolutionary miracle" not in remediated_draft
    assert "without any human delay" not in remediated_draft
    assert "socialmedia" not in remediated_draft
    assert "mandatory human review" in remediated_draft


@pytest.mark.asyncio
async def test_remediation_synthesizer_accurately_tracks_unresolved_violations():
    """Verify that when a violation cannot be resolved, the synthesizer never claims 100% remediation."""
    from app.engine.remediator import remediation_synthesizer

    content = "This is a statement with an unresolved custom brand term."
    violations = [
        {
            "id": "v-1",
            "rule_id": "r-1",
            "rule_name": "Trademark Rule",
            "rule_type": "trademark_usage",
            "severity": "high",
            "flagged_text": "custom brand term",
            "char_start": 36,
            "char_end": 54,
            "explanation": "Must use approved term.",
            "suggestions": [],  # No suggestions available
        }
    ]
    guidelines = [
        {
            "id": "r-1",
            "name": "Trademark Rule",
            "rule_type": "trademark_usage",
            "directive": "Do not use 'custom brand term'.",
            "is_active": True,
        }
    ]

    res = remediation_synthesizer.synthesize_remediated_draft(
        content=content,
        violations=violations,
        guidelines=guidelines,
    )

    # Must accurately report unresolved violation
    assert res["is_fully_remediated"] is False
    assert res["unresolved_violations"] == 1
    assert "v-1" in res["unresolved_violation_ids"]
    assert res["remediated_violations"] == 0


@pytest.mark.asyncio
async def test_remediation_zero_corruption_on_q1_product_launch_content(engine_session: AsyncSession):
    """Critical Phase 4.1 Regression Test:
    Using exact original content:
    'We are thrilled to unveil Brandshield! Our revolutionary miracle platform guarantees 100% brand safety across every channel. It automatically posts to socialmedia without any human delay!'
    
    Verifies:
    1. Zero corrupted or merged words (e.g. 'unveilBrandShield AId', 'Ourintelligent', 'platformosubstantially', 'channelsnel', 'distributionlay').
    2. Exact word boundaries and spaces preserved around all replacements.
    3. Safe span validation corrects shifted/corrupted input offsets without data corruption.
    4. Closed-loop validation confirms 0 violations in remediated draft.
    5. is_fully_remediated is strictly True only when all checks pass.
    """
    from app.engine.remediator import remediation_synthesizer

    target_content = (
        "We are thrilled to unveil Brandshield! Our revolutionary miracle platform guarantees 100% brand safety across every channel. "
        "It automatically posts to socialmedia without any human delay!"
    )

    org = Organization(
        id=uuid.uuid4(),
        name="Apex Enterprise",
        slug=f"apex-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    engine_session.add(org)
    await engine_session.flush()

    g1 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="BrandShield AI Capitalization & Spacing",
        rule_type=RuleType.TRADEMARK_USAGE.value,
        severity=SeverityLevel.HIGH.value,
        directive="The official product name must always be capitalized as 'BrandShield AI'. Never write 'Brandshield' or 'brandshield'.",
        description="Enforces exact trademark capitalization.",
        examples_approved=["BrandShield AI provides governance."],
        examples_prohibited=["Brandshield", "brandshield"],
        tags=["trademark", "branding"],
        is_active=True,
    )
    g2 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Absolute Security Claim Prohibition",
        rule_type=RuleType.PROHIBITED_CLAIMS.value,
        severity=SeverityLevel.CRITICAL.value,
        directive="Never state that the platform 'guarantees 100% brand safety across every channel' or offers 'zero risk'. Use defensible qualified claims.",
        description="Prohibits non-defensible absolute claims.",
        examples_approved=["substantially elevates brand compliance across modern channels"],
        examples_prohibited=["guarantees 100% brand safety across every channel", "100% brand safety"],
        tags=["legal", "compliance"],
        is_active=True,
    )
    g3 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Empowering & Authoritative Tone of Voice",
        rule_type=RuleType.TONE_OF_VOICE.value,
        severity=SeverityLevel.MEDIUM.value,
        directive="Maintain an authoritative, measured, and professional tone. Avoid sensationalist hyperbole such as 'revolutionary miracle platform'.",
        description="Preserves enterprise tone.",
        examples_approved=["intelligent brand governance platform"],
        examples_prohibited=["revolutionary miracle platform", "revolutionary miracle"],
        tags=["tone", "messaging"],
        is_active=True,
    )
    g4 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Mandatory Human-in-the-Loop Governance Notice",
        rule_type=RuleType.LEGAL_REGULATORY.value,
        severity=SeverityLevel.CRITICAL.value,
        directive="Any public release describing automated workflows must explicitly state that human brand officers retain final approval authority.",
        description="Requires human-in-the-loop notice.",
        examples_approved=["accelerates social media publishing with mandatory human review before distribution"],
        examples_prohibited=["automatically posts to socialmedia without any human delay"],
        tags=["governance", "regulatory"],
        is_active=True,
    )
    g5 = BrandGuideline(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Standard Formatting & Terminology",
        rule_type=RuleType.FORMATTING.value,
        severity=SeverityLevel.LOW.value,
        directive='Use "social media" (two words, lowercase), "real-time" (hyphenated when modifying a noun), and avoid all-caps shout words.',
        description="Standard formatting.",
        examples_approved=["Delivers real-time alerts across social media channels."],
        examples_prohibited=["automatically posts to socialmedia without any human delay"],
        tags=["formatting", "style"],
        is_active=True,
    )
    engine_session.add_all([g1, g2, g3, g4, g5])
    await engine_session.flush()

    # Pass deliberately shifted/corrupted input offsets to verify safe validator relocation
    violations_with_shifted_offsets = [
        {
            "id": "viol-1",
            "rule_id": str(g1.id),
            "rule_name": g1.name,
            "rule_type": g1.rule_type,
            "severity": g1.severity,
            "flagged_text": "Brandshield",
            "char_start": 25,  # Shifted: starts with space, drops 'd'
            "char_end": 36,
            "explanation": "Misspelled brand name.",
            "suggestions": [{"suggested_text": "BrandShield AI", "source": "rule_derived"}],
            "evidence_citations": [{"source_clause": g1.directive, "document_name": "Brand Guide", "confidence_score": 1.0}],
        },
        {
            "id": "viol-2",
            "rule_id": str(g2.id),
            "rule_name": g2.name,
            "rule_type": g2.rule_type,
            "severity": g2.severity,
            "flagged_text": "guarantees 100% brand safety across every channel",
            "char_start": 71,  # Shifted: starts at 'rm', drops 'nel'
            "char_end": 120,
            "explanation": "Absolute guarantee creates legal liability.",
            "suggestions": [{"suggested_text": "substantially elevates brand compliance across modern channels", "source": "rule_derived"}],
            "evidence_citations": [{"source_clause": g2.directive, "document_name": "Legal Directives", "confidence_score": 1.0}],
        },
        {
            "id": "viol-3",
            "rule_id": str(g3.id),
            "rule_name": g3.name,
            "rule_type": g3.rule_type,
            "severity": g3.severity,
            "flagged_text": "revolutionary miracle platform",
            "char_start": 42,  # Shifted: starts at space, drops 'orm'
            "char_end": 70,
            "explanation": "Hyperbolic language.",
            "suggestions": [{"suggested_text": "intelligent brand governance platform", "source": "rule_derived"}],
            "evidence_citations": [{"source_clause": g3.directive, "document_name": "Tone Playbook", "confidence_score": 1.0}],
        },
        {
            "id": "viol-4",
            "rule_id": str(g4.id),
            "rule_name": g4.name,
            "rule_type": g4.rule_type,
            "severity": g4.severity,
            "flagged_text": "automatically posts to socialmedia without any human delay",
            "char_start": 125,  # Shifted: starts at 'It', drops 'lay'
            "char_end": 183,
            "explanation": "Autonomous posting claim.",
            "suggestions": [{"suggested_text": "accelerates social media publishing with mandatory human review before distribution", "source": "rule_derived"}],
            "evidence_citations": [{"source_clause": g4.directive, "document_name": "Governance Charter", "confidence_score": 1.0}],
        },
    ]

    serialized_guidelines = [
        {
            "id": str(g.id),
            "name": g.name,
            "rule_type": g.rule_type,
            "severity": g.severity,
            "description": g.description,
            "directive": g.directive,
            "examples_approved": g.examples_approved or [],
            "examples_prohibited": g.examples_prohibited or [],
            "is_active": g.is_active,
        }
        for g in [g1, g2, g3, g4, g5]
    ]

    res = remediation_synthesizer.synthesize_remediated_draft(
        content=target_content,
        violations=violations_with_shifted_offsets,
        guidelines=serialized_guidelines,
    )

    remediated = res["remediated_draft"]

    # 1. Verify exact expected natural draft
    expected = (
        "We are thrilled to unveil BrandShield AI! Our intelligent brand governance platform substantially elevates "
        "brand compliance across modern channels. It accelerates social media publishing with mandatory human review before distribution!"
    )
    assert remediated == expected

    # 2. Verify complete absence of all 5 critical corruption patterns
    assert "unveilBrandShield" not in remediated, "Detected 'unveilBrandShield' concatenation"
    assert "BrandShield AId" not in remediated, "Detected trailing 'd' in 'BrandShield AId'"
    assert "Ourintelligent" not in remediated, "Detected 'Ourintelligent' concatenation"
    assert "platformosubstantially" not in remediated, "Detected 'platformosubstantially' corruption"
    assert "channelsnel" not in remediated, "Detected 'channelsnel' corruption"
    assert "distributionlay" not in remediated, "Detected 'distributionlay' corruption"

    # 3. Verify zero corruptions flagged
    assert res["corruptions"] == []
    assert res["is_fully_remediated"] is True
    assert res["total_violations"] == 4
    assert res["remediated_violations"] == 4
    assert res["unresolved_violations"] == 0
    assert res["new_violations_detected"] == 0


@pytest.mark.asyncio
async def test_remediation_blocks_full_certification_when_corrupted_or_unresolved():
    """Verify that a draft containing unresolvable violations or corruptions is NEVER marked fully remediated."""
    from app.engine.remediator import remediation_synthesizer

    content = "We use an unresolvable custom term that cannot be mapped."
    violations = [
        {
            "id": "v-corrupt-1",
            "rule_id": "r-1",
            "rule_name": "Trademark Standard",
            "rule_type": "trademark_usage",
            "flagged_text": "nonexistent text not in draft",  # Flagged text absent from content
            "char_start": 999,
            "char_end": 1050,
            "suggestions": [{"suggested_text": "replacement"}],
        }
    ]
    guidelines = [
        {"id": "r-1", "name": "Trademark Standard", "rule_type": "trademark_usage", "directive": "No bad terms", "is_active": True}
    ]

    res = remediation_synthesizer.synthesize_remediated_draft(content, violations, guidelines)

    # Invariant: Must not be marked fully remediated
    assert res["is_fully_remediated"] is False
    assert res["unresolved_violations"] == 1
    assert "v-corrupt-1" in res["unresolved_violation_ids"]
    assert res["remediated_violations"] == 0


def test_correction_provenance_distinguishes_sources():
    """Verify that rule-derived, AI-generated, and human-edited corrections retain strict provenance."""
    from app.engine.remediator import remediation_synthesizer

    v_rule = {"id": "1", "suggestions": [{"suggested_text": "text1", "source": "rule_derived"}]}
    v_ai = {"id": "2", "suggestions": [{"suggested_text": "text2", "source": "ai_generated"}]}
    v_human = {"id": "3", "suggestions": [{"suggested_text": "text3", "source": "human_edited"}]}
    v_default = {"id": "4", "suggestions": []}

    assert remediation_synthesizer._extract_suggestion_source(v_rule) == "rule_derived"
    assert remediation_synthesizer._extract_suggestion_source(v_ai) == "ai_generated"
    assert remediation_synthesizer._extract_suggestion_source(v_human) == "human_edited"
    assert remediation_synthesizer._extract_suggestion_source(v_default) == "rule_derived"


@pytest.mark.asyncio
async def test_backend_authority_remediation_api_lifecycle(engine_client: AsyncClient):
    """Phase 4.2 Authority Verification: Prove backend alone generates remediated drafts and summaries.
    
    Verifies on a real database submission:
    1. Uninspected submission reports pending state without fabricating a draft.
    2. Inspection triggers backend remediation engine.
    3. GET /api/v1/submissions/{id}/report returns authoritative remediated_draft and remediation_summary.
    4. Remediated draft has zero corruptions and all violation IDs are accurately accounted for.
    """
    raw_content = (
        "We are thrilled to announce brandshield ai! Our miracle platform guarantees 100% infallible "
        "compliance with zero human oversight, completely eliminating all legal risk."
    )

    # 1. Create real submission in database
    create_res = await engine_client.post(
        "/api/v1/submissions",
        json={
            "title": "Database Authority Lifecycle Test",
            "content": raw_content,
            "target_channel": "twitter_x",
            "target_audience": "Enterprise Security Teams",
        },
    )
    assert create_res.status_code == 201
    submission_data = create_res.json()
    sub_id = submission_data["id"]
    assert submission_data["status"] == "draft"

    # 2. Before inspection: GET /report must honestly report pending without fabricating drafts
    pending_report_res = await engine_client.get(f"/api/v1/submissions/{sub_id}/report")
    assert pending_report_res.status_code == 200
    pending_data = pending_report_res.json()
    assert pending_data["is_analyzed"] is False
    assert pending_data["status"] == "pending_analysis"
    assert pending_data.get("remediated_draft") is None
    assert pending_data.get("remediation_summary") is None
    assert pending_data["total_violations"] == 0

    # 3. Execute backend compliance inspection via POST /analyze
    analyze_res = await engine_client.post(f"/api/v1/submissions/{sub_id}/analyze")
    assert analyze_res.status_code == 200
    analyzed_sub = analyze_res.json()
    assert analyzed_sub["status"] == "violations_found"

    # 4. After inspection: GET /report returns authoritative remediated_draft and summary
    report_res = await engine_client.get(f"/api/v1/submissions/{sub_id}/report")
    assert report_res.status_code == 200
    report_data = report_res.json()

    assert report_data["is_analyzed"] is True
    assert report_data["status"] == "completed"
    assert report_data["is_compliant"] is False
    assert report_data["total_violations"] >= 2

    # Verify authoritative draft returned by backend
    remediated_draft = report_data.get("remediated_draft")
    assert remediated_draft is not None
    assert len(remediated_draft) > 0
    assert "BrandShield AI" in remediated_draft
    assert "brandshield ai" not in remediated_draft  # Casing fixed
    assert "100% infallible" not in remediated_draft.lower()  # Absolute claim remediated

    # Verify zero text corruption in backend draft
    assert "brandshield aid" not in remediated_draft.lower()
    assert "platformo" not in remediated_draft.lower()
    assert "channelsnel" not in remediated_draft.lower()
    assert "distributionlay" not in remediated_draft.lower()

    # Verify authoritative remediation_summary
    rem_summary = report_data.get("remediation_summary")
    assert rem_summary is not None
    assert rem_summary["total_violations"] == report_data["total_violations"]
    assert rem_summary["remediated_violations"] >= 1
    assert "resolved_violation_ids" in rem_summary
    assert "unresolved_violation_ids" in rem_summary
    assert isinstance(rem_summary["corruptions"], list)
    assert len(rem_summary["corruptions"]) == 0  # No corruptions detected

    # Verify that all resolved IDs exist in the report's violations
    report_violation_ids = {v["id"] for v in report_data["violations"]}
    for resolved_id in rem_summary["resolved_violation_ids"]:
        assert resolved_id in report_violation_ids


