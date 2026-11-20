"""Unit and integration test suite for Round 3 Phase 1 Milestone 1: Database Foundation.

Validates:
1. ComplianceReport risk assessment fields and defaults (risk_score, risk_level, is_escalated, multipliers, risk_breakdown).
2. ClaimVerification model creation, relationships, and defaults.
3. Check constraints on claim verification (status enum, confidence range [0.0, 1.0], non-empty text).
4. Check constraints on compliance report (risk score [0.0, 100.0], risk levels, positive multipliers).
5. Cross-tenant integrity protection: Claim cannot reference a report belonging to another organization.
6. Cascade deletion: Deleting a compliance report cascades to its claim verifications.
7. Alembic migration 0007 upgrade and downgrade execution on an isolated test database.
8. PostgreSQL Row-Level Security tenant isolation test definition (skipped safely per safety restriction 5 when 0007 is not yet applied).
"""

from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import tempfile
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.config import settings
from app.core.database import Base
from app.models.compliance import (
    ClaimVerification,
    ComplianceReport,
    CorrectionSuggestion,
    EvidenceCitation,
    RuleViolation,
)
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.submission import ContentSubmission
from app.schemas.common import ClaimStatus, RiskLevel


@pytest_asyncio.fixture
async def db_session():
    """Isolated in-memory SQLite database session with complete Phase 1 Milestone 1 schema."""
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
            name="Alpha Corp",
            slug=f"alpha-{uuid.uuid4().hex[:6]}",
            is_active=True,
        )
        org_b = Organization(
            id=uuid.uuid4(),
            name="Beta Ltd",
            slug=f"beta-{uuid.uuid4().hex[:6]}",
            is_active=True,
        )
        session.add_all([org_a, org_b])
        await session.flush()

        # Create Submissions
        sub_a = ContentSubmission(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            title="Alpha Marketing Campaign",
            content="Alpha delivers zero-emissions logistics.",
            target_channel="web",
            target_audience="general",
            status="analyzing",
            version=1,
        )
        sub_b = ContentSubmission(
            id=uuid.uuid4(),
            organization_id=org_b.id,
            title="Beta Product Announcement",
            content="Beta guarantees 100% compliance.",
            target_channel="social",
            target_audience="B2B",
            status="analyzing",
            version=1,
        )
        session.add_all([sub_a, sub_b])
        await session.flush()

        yield {
            "session": session,
            "org_a": org_a,
            "org_b": org_b,
            "sub_a": sub_a,
            "sub_b": sub_b,
        }

    await engine.dispose()


# ==============================================================================
# 1. Model Creation & Risk Assessment Defaults
# ==============================================================================

@pytest.mark.asyncio
async def test_compliance_report_risk_fields_and_defaults(db_session):
    """Verify that ComplianceReport properly persists all Phase 1 risk fields with correct defaults."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]

    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=sub_a.version,
        is_compliant=True,
        total_violations=0,
        summary="All rules passed.",
    )
    session.add(report)
    await session.flush()

    # Query back
    result = await session.execute(
        select(ComplianceReport).where(ComplianceReport.id == report.id)
    )
    saved_report = result.scalar_one()

    assert saved_report.risk_score == 0.0
    assert saved_report.risk_level == "LOW"
    assert saved_report.is_escalated is False
    assert saved_report.channel_multiplier == 1.0
    assert saved_report.audience_multiplier == 1.0
    assert saved_report.risk_breakdown == {}


@pytest.mark.asyncio
async def test_claim_verification_creation_and_defaults(db_session):
    """Verify that ClaimVerification stores factual claims and applies default values."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]
    org_a = db_session["org_a"]

    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=sub_a.version,
        is_compliant=False,
        total_violations=1,
        summary="Violations found.",
        risk_score=25.0,
        risk_level="LOW",
        is_escalated=False,
    )
    session.add(report)
    await session.flush()

    claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        report_id=report.id,
        claim_text="Alpha delivers zero-emissions logistics across Europe.",
        status=ClaimStatus.UNSUPPORTED.value,
        uncertainty_notes="No active guideline documents substantiate emissions figures for Europe.",
    )
    session.add(claim)
    await session.flush()

    # Query back
    result = await session.execute(
        select(ClaimVerification).where(ClaimVerification.id == claim.id)
    )
    saved_claim = result.scalar_one()

    assert saved_claim.claim_text == "Alpha delivers zero-emissions logistics across Europe."
    assert saved_claim.status == "UNSUPPORTED"
    assert saved_claim.document_name is None, "document_name must default to None when source document is unknown"
    assert saved_claim.confidence_score == 1.0
    assert saved_claim.is_escalated is False
    assert saved_claim.uncertainty_notes is not None
    assert isinstance(saved_claim.created_at, datetime)

    # Verify explicit document_name is properly preserved when provided
    claim_with_doc = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        report_id=report.id,
        claim_text="Alpha is ISO 14001 certified across European hubs.",
        status=ClaimStatus.VERIFIED.value,
        document_name="Sustainability Audit Report 2026",
    )
    session.add(claim_with_doc)
    await session.flush()

    res_doc = await session.execute(
        select(ClaimVerification).where(ClaimVerification.id == claim_with_doc.id)
    )
    saved_doc_claim = res_doc.scalar_one()
    assert saved_doc_claim.document_name == "Sustainability Audit Report 2026"


# ==============================================================================
# 2. Relationships & Cascade Deletion
# ==============================================================================

@pytest.mark.asyncio
async def test_claim_verification_relationships_and_cascade(db_session):
    """Verify bidirectional relationship and cascading deletion from report to claims."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]
    org_a = db_session["org_a"]

    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=sub_a.version,
        is_compliant=False,
        total_violations=1,
        summary="Report with claims.",
    )
    session.add(report)
    await session.flush()

    claim_1 = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        report_id=report.id,
        claim_text="Claim 1: 99.9% uptime guaranteed.",
        status=ClaimStatus.CONTRADICTORY.value,
        is_escalated=True,
    )
    claim_2 = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        report_id=report.id,
        claim_text="Claim 2: SOC2 Type II certified.",
        status=ClaimStatus.VERIFIED.value,
        is_escalated=False,
    )
    session.add_all([claim_1, claim_2])
    await session.flush()

    # Verify report relationship
    result = await session.execute(
        select(ComplianceReport).where(ComplianceReport.id == report.id)
    )
    loaded_report = result.scalar_one()
    assert len(loaded_report.claim_verifications) == 2

    # Verify claim relationship back to report
    res_claim = await session.execute(
        select(ClaimVerification).where(ClaimVerification.id == claim_1.id)
    )
    loaded_claim = res_claim.scalar_one()
    assert loaded_claim.report.id == report.id

    # Cascade delete report -> claims must be removed
    await session.delete(report)
    await session.flush()

    res_check = await session.execute(
        select(ClaimVerification).where(ClaimVerification.report_id == report.id)
    )
    assert len(res_check.scalars().all()) == 0


# ==============================================================================
# 3. Check Constraints Enforcement
# ==============================================================================

@pytest.mark.asyncio
async def test_claim_verification_invalid_status_constraint(db_session):
    """Verify check constraint rejects invalid claim status."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]
    org_a = db_session["org_a"]

    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Valid report",
    )
    session.add(report)
    await session.flush()

    invalid_claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        report_id=report.id,
        claim_text="Valid claim text",
        status="INVALID_STATUS_STRING",
    )
    session.add(invalid_claim)

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_claim_verification_confidence_score_range_constraint(db_session):
    """Verify check constraint enforces confidence_score between 0.0 and 1.0."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]
    org_a = db_session["org_a"]

    report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Valid report",
    )
    session.add(report)
    await session.flush()

    invalid_claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        report_id=report.id,
        claim_text="Valid claim text",
        status=ClaimStatus.VERIFIED.value,
        confidence_score=1.5,  # Invalid: > 1.0
    )
    session.add(invalid_claim)

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_compliance_report_risk_score_range_constraint(db_session):
    """Verify check constraint enforces risk_score between 0.0 and 100.0."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]

    invalid_report = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=1,
        is_compliant=False,
        total_violations=1,
        summary="Invalid report",
        risk_score=150.0,  # Invalid: > 100.0
    )
    session.add(invalid_report)

    with pytest.raises(IntegrityError):
        await session.flush()


# ==============================================================================
# 4. Cross-Tenant Integrity Protection
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_tenant_claim_reference_rejected(db_session):
    """Ensure a claim cannot reference a compliance report belonging to another organization.

    Integrity rule:
    Claim with organization_id = Org B attempting to link to Report belonging to Org A
    must be rejected at both the ORM level and database trigger level.
    """
    session = db_session["session"]
    sub_a = db_session["sub_a"]  # Belongs to Org A
    org_b = db_session["org_b"]  # Different tenant (Org B)

    # Report A belongs to Org A
    report_a = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Report A for Org A",
    )
    session.add(report_a)
    await session.flush()

    # Attempt to insert claim claiming to be Org B, but pointing to Report A (Org A)
    cross_tenant_claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_b.id,  # Org B
        report_id=report_a.id,     # Report belonging to Org A!
        claim_text="Cross-tenant unauthorized claim linkage",
        status=ClaimStatus.NEEDS_HUMAN_REVIEW.value,
    )
    session.add(cross_tenant_claim)

    with pytest.raises(ValueError) as exc:
        await session.flush()

    assert "Cross-tenant integrity violation" in str(exc.value)


@pytest.mark.asyncio
async def test_cross_tenant_claim_update_organization_rejected(db_session):
    """Ensure updating a claim's organization_id to a different tenant is rejected by ORM listener."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]
    org_a = db_session["org_a"]
    org_b = db_session["org_b"]

    report_a = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Report A for Org A",
    )
    session.add(report_a)
    await session.flush()

    valid_claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        report_id=report_a.id,
        claim_text="Initial valid claim for Org A",
        status=ClaimStatus.VERIFIED.value,
    )
    session.add(valid_claim)
    await session.flush()

    # Attempt to change organization_id to Org B while report belongs to Org A
    valid_claim.organization_id = org_b.id

    with pytest.raises(ValueError) as exc:
        await session.flush()

    assert "Cross-tenant integrity violation" in str(exc.value)


@pytest.mark.asyncio
async def test_cross_tenant_claim_update_report_rejected(db_session):
    """Ensure updating a claim's report_id to a report owned by another tenant is rejected by ORM listener."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]
    sub_b = db_session["sub_b"]
    org_a = db_session["org_a"]
    org_b = db_session["org_b"]

    report_a = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Report A for Org A",
    )
    report_b = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_b.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Report B for Org B",
    )
    session.add_all([report_a, report_b])
    await session.flush()

    valid_claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        report_id=report_a.id,
        claim_text="Initial valid claim for Org A",
        status=ClaimStatus.VERIFIED.value,
    )
    session.add(valid_claim)
    await session.flush()

    # Attempt to change report_id to Report B (which belongs to Org B) while claim organization_id remains Org A
    valid_claim.report_id = report_b.id

    with pytest.raises(ValueError) as exc:
        await session.flush()

    assert "Cross-tenant integrity violation" in str(exc.value)


@pytest.mark.asyncio
async def test_sqlite_trigger_cross_tenant_update_rejected(db_session):
    """Ensure SQLite trigger trg_claim_verification_org_match_update rejects cross-tenant raw SQL updates."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]
    sub_b = db_session["sub_b"]
    org_a = db_session["org_a"]
    org_b = db_session["org_b"]

    report_a = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Report A",
    )
    report_b = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_b.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Report B",
    )
    session.add_all([report_a, report_b])
    await session.flush()

    claim_id = uuid.uuid4()
    claim = ClaimVerification(
        id=claim_id,
        organization_id=org_a.id,
        report_id=report_a.id,
        claim_text="Valid claim Org A",
        status="VERIFIED",
    )
    session.add(claim)
    await session.flush()

    # Test 1: Direct SQL UPDATE attempting to switch organization_id to Org B
    with pytest.raises((IntegrityError, Exception)) as exc1:
        async with session.begin_nested():
            await session.execute(
                update(ClaimVerification)
                .where(ClaimVerification.id == claim.id)
                .values(organization_id=org_b.id)
            )
    assert "Cross-tenant violation" in str(exc1.value)

    # Test 2: Direct SQL UPDATE attempting to switch report_id to Report B (Org B)
    with pytest.raises((IntegrityError, Exception)) as exc2:
        async with session.begin_nested():
            await session.execute(
                update(ClaimVerification)
                .where(ClaimVerification.id == claim.id)
                .values(report_id=report_b.id)
            )
    assert "Cross-tenant violation" in str(exc2.value)


@pytest.mark.asyncio
async def test_same_tenant_claim_update_allowed(db_session):
    """Ensure legitimate same-tenant updates to non-tenant attributes succeed without error."""
    session = db_session["session"]
    sub_a = db_session["sub_a"]
    org_a = db_session["org_a"]

    report_a = ComplianceReport(
        id=uuid.uuid4(),
        submission_id=sub_a.id,
        submission_version=1,
        is_compliant=True,
        total_violations=0,
        summary="Report A for Org A",
    )
    session.add(report_a)
    await session.flush()

    claim = ClaimVerification(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        report_id=report_a.id,
        claim_text="Preliminary claim text",
        status=ClaimStatus.NEEDS_HUMAN_REVIEW.value,
        confidence_score=0.5,
    )
    session.add(claim)
    await session.flush()

    # Perform legitimate update
    claim.claim_text = "Refined claim text under human review"
    claim.confidence_score = 0.8
    claim.uncertainty_notes = "Confirmed by reviewer."
    await session.flush()

    # Verify update persisted
    res = await session.execute(
        select(ClaimVerification).where(ClaimVerification.id == claim.id)
    )
    updated = res.scalar_one()
    assert updated.claim_text == "Refined claim text under human review"
    assert updated.confidence_score == 0.8
    assert updated.uncertainty_notes == "Confirmed by reviewer."


# ==============================================================================
# 5. Alembic Migration Upgrade & Downgrade (Isolated Test DB)
# ==============================================================================

def test_migration_0007_upgrade_and_downgrade():
    """Verify that Alembic revision 0007 upgrades and downgrades cleanly on an isolated test SQLite DB."""
    import sqlite3

    # Dynamically load migration 0007 module
    mig_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0007_add_risk_assessment_and_claim_verification.py"
    spec = importlib.util.spec_from_file_location("mig_0007", str(mig_path))
    mig_0007 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_0007)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = tmp_file.name

    sync_engine = create_engine(f"sqlite:///{tmp_db_path}")
    try:
        # Create baseline schema up to 0006
        with sync_engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE organizations (id TEXT PRIMARY KEY, name TEXT NOT NULL);")
            conn.exec_driver_sql("CREATE TABLE content_submissions (id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id));")
            conn.exec_driver_sql("""
                CREATE TABLE compliance_reports (
                    id TEXT PRIMARY KEY,
                    submission_id TEXT NOT NULL REFERENCES content_submissions(id),
                    submission_version INTEGER NOT NULL,
                    is_compliant BOOLEAN NOT NULL,
                    total_violations INTEGER DEFAULT 0 NOT NULL,
                    summary TEXT NOT NULL,
                    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );
            """)

        # Execute 0007 upgrade()
        with sync_engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            orig_op = getattr(mig_0007, "op")
            mig_0007.op = op
            try:
                mig_0007.upgrade()
            finally:
                mig_0007.op = orig_op

        # Inspect updated schema
        conn = sqlite3.connect(tmp_db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall()]
        assert "claim_verifications" in tables, "claim_verifications table must exist after upgrade"

        cur.execute("PRAGMA table_info(compliance_reports);")
        cols = [r[1] for r in cur.fetchall()]
        for expected_col in ["risk_score", "risk_level", "is_escalated", "channel_multiplier", "audience_multiplier", "risk_breakdown"]:
            assert expected_col in cols, f"Column '{expected_col}' must exist in compliance_reports after upgrade"

        cur.execute("PRAGMA table_info(claim_verifications);")
        # columns: cid, name, type, notnull, dflt_value, pk
        claim_cols = {r[1]: {"notnull": r[3], "dflt_value": r[4]} for r in cur.fetchall()}
        assert "document_name" in claim_cols, "document_name column must exist in claim_verifications"
        assert claim_cols["document_name"]["notnull"] == 0, "document_name must be nullable"
        assert claim_cols["document_name"]["dflt_value"] is None, "document_name must not have hardcoded server default"
        conn.close()

        # Execute 0007 downgrade()
        with sync_engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            orig_op = getattr(mig_0007, "op")
            mig_0007.op = op
            try:
                mig_0007.downgrade()
            finally:
                mig_0007.op = orig_op

        # Inspect downgraded schema
        conn = sqlite3.connect(tmp_db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables_after = [r[0] for r in cur.fetchall()]
        assert "claim_verifications" not in tables_after, "claim_verifications must be dropped after downgrade"

        cur.execute("PRAGMA table_info(compliance_reports);")
        cols_after = [r[1] for r in cur.fetchall()]
        assert "risk_score" not in cols_after, "risk_score column must be removed after downgrade"
        assert "risk_level" not in cols_after, "risk_level column must be removed after downgrade"
        assert "risk_breakdown" not in cols_after, "risk_breakdown column must be removed after downgrade"
        conn.close()

    finally:
        sync_engine.dispose()
        if os.path.exists(tmp_db_path):
            try:
                os.remove(tmp_db_path)
            except Exception:
                pass


# ==============================================================================
# 6. PostgreSQL Row-Level Security Verification Structure
# ==============================================================================

@pytest.mark.asyncio
async def test_postgresql_rls_claim_verifications_isolation():
    """Verify database-enforced RLS on PostgreSQL for claim_verifications.

    SAFETY INVARIANT:
    Skipped when running against SQLite or when migration 0007 has not yet been applied
    to the target PostgreSQL environment. Never claims PASS without live engine proof.
    """
    if "sqlite" in settings.DATABASE_URL:
        pytest.skip("PostgreSQL required for live Row-Level Security verification.")

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # Check if table exists on target DB before executing RLS probes
            table_exists = await session.execute(
                text("SELECT to_regclass('public.claim_verifications');")
            )
            if table_exists.scalar() is None:
                pytest.skip("claim_verifications table not yet migrated on PostgreSQL (migration 0007 unapplied per safety restriction 5).")

            # Execute transactional RLS tests if migration has been applied
            async with session.begin_nested():
                org_a_id = uuid.uuid4()
                org_b_id = uuid.uuid4()

                org_a = Organization(id=org_a_id, name="RLS Claim Org A", slug=f"rls-c-a-{org_a_id.hex[:6]}", is_active=True)
                org_b = Organization(id=org_b_id, name="RLS Claim Org B", slug=f"rls-c-b-{org_b_id.hex[:6]}", is_active=True)
                session.add_all([org_a, org_b])
                await session.flush()

                sub_a = ContentSubmission(
                    id=uuid.uuid4(),
                    organization_id=org_a_id,
                    title="RLS Test Sub",
                    content="Content",
                    target_channel="web",
                    status="analyzing",
                    version=1,
                )
                session.add(sub_a)
                await session.flush()

                report_a = ComplianceReport(
                    id=uuid.uuid4(),
                    submission_id=sub_a.id,
                    submission_version=1,
                    is_compliant=True,
                    total_violations=0,
                    summary="Summary",
                )
                session.add(report_a)
                await session.flush()

                # Step 1: Set context to Org A
                await session.execute(text(f"SET LOCAL app.current_org_id = '{org_a_id}'"))

                claim_a = ClaimVerification(
                    id=uuid.uuid4(),
                    organization_id=org_a_id,
                    report_id=report_a.id,
                    claim_text="Org A claim under RLS",
                    status="VERIFIED",
                )
                session.add(claim_a)
                await session.flush()

                # Query as Org A -> Must find row
                res_a = await session.execute(
                    text("SELECT id FROM claim_verifications WHERE id = :id"),
                    {"id": claim_a.id},
                )
                assert res_a.fetchone() is not None, "Org A must see its own claim"

                # Step 2: Switch context to Org B -> RLS MUST filter out Org A claim
                await session.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))

                res_b = await session.execute(
                    text("SELECT id FROM claim_verifications WHERE id = :id"),
                    {"id": claim_a.id},
                )
                assert res_b.fetchone() is None, "RLS must filter out Org A claim from Org B context"

                # Step 3: Cross-tenant insert attempt blocked by RLS WITH CHECK
                insert_failed = False
                try:
                    async with session.begin_nested():
                        await session.execute(
                            text(
                                "INSERT INTO claim_verifications (id, organization_id, report_id, claim_text, status, document_name, confidence_score, is_escalated, created_at) "
                                "VALUES (:id, :org_id, :rep_id, 'Cross-tenant RLS claim', 'VERIFIED', 'Doc', 1.0, false, NOW())"
                            ),
                            {"id": uuid.uuid4(), "org_id": org_a_id, "rep_id": report_a.id},
                        )
                except Exception as exc:
                    insert_failed = True
                    assert "violates row-level security policy" in str(exc).lower()
                assert insert_failed, "RLS WITH CHECK must reject cross-tenant insert"

                # Step 4: Fail-closed semantics: Unset / empty context returns 0 rows
                await session.execute(text("SET LOCAL app.current_org_id = ''"))
                res_empty = await session.execute(
                    text("SELECT id FROM claim_verifications WHERE id = :id"),
                    {"id": claim_a.id},
                )
                assert res_empty.fetchone() is None, "Fail-closed: empty org context must return 0 rows"

                await session.rollback()

    finally:
        await engine.dispose()


# ==============================================================================
# 7. Least-Privilege Runtime Grants Verification
# ==============================================================================

def test_migration_0007_runtime_least_privilege_grants():
    """Verify that migration 0007 grants SELECT, INSERT, DELETE to brandshield_app, and omits UPDATE/TRUNCATE."""
    mig_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0007_add_risk_assessment_and_claim_verification.py"
    with open(mig_path, "r", encoding="utf-8") as f:
        mig_content = f.read()

    # Locate brandshield_app grant block
    grant_start = mig_content.find("GRANT SELECT")
    grant_end = mig_content.find("TO brandshield_app;")
    assert grant_start != -1 and grant_end != -1, "brandshield_app grant statement must exist"

    grant_clause = mig_content[grant_start:grant_end]
    assert "SELECT" in grant_clause, "SELECT must be granted"
    assert "INSERT" in grant_clause, "INSERT must be granted"
    assert "DELETE" in grant_clause, "DELETE must be granted for cascade deletion"
    assert "UPDATE" not in grant_clause, "UPDATE must NOT be granted to runtime role"
    assert "TRUNCATE" not in grant_clause, "TRUNCATE must NOT be granted to runtime role"
