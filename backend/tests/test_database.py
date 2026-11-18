from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import (
    Base,
    ImmutableAuditError,
    get_engine_options,
    set_tenant_context,
)
from app.models import (
    AuditEntry,
    BrandGuideline,
    ComplianceReport,
    CorrectionSuggestion,
    EvidenceCitation,
    Organization,
    ReviewDecision,
    RuleViolation,
    ContentSubmission,
    User,
)


@pytest_asyncio.fixture
async def async_test_session():
    """Fixture providing an isolated in-memory SQLite async session with foreign keys enabled."""
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with test_engine.begin() as conn:
        # Enable SQLite foreign key constraint checks
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON;")
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_maker() as session:
        yield session
        await session.close()

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_complete_entity_graph_and_relationships(async_test_session: AsyncSession) -> None:
    """Verify that all 10 models persist, link via foreign keys, and load relations correctly."""
    session = async_test_session

    # 1. Create Organization (Tenant)
    org = Organization(
        name="Acme Corporation",
        slug="acme-corp",
    )
    session.add(org)
    await session.flush()
    assert isinstance(org.id, uuid.UUID)

    # 2. Create Users
    author = User(
        organization_id=org.id,
        email="author@acme.com",
        hashed_password="argon2_hashed_secret",
        full_name="Alice Author",
        role="CREATOR",
    )
    reviewer = User(
        organization_id=org.id,
        email="reviewer@acme.com",
        hashed_password="argon2_hashed_secret",
        full_name="Bob Reviewer",
        role="REVIEWER",
    )
    session.add_all([author, reviewer])
    await session.flush()

    # 3. Create Brand Guideline
    guideline = BrandGuideline(
        organization_id=org.id,
        name="Trademark Naming Convention",
        rule_type="terminology",
        severity="high",
        description="Brand name must be written as BrandShield AI.",
        directive="Never use brandshield or Brandshield AI.",
        examples_approved=["BrandShield AI Platform"],
        examples_prohibited=["brandshield ai"],
        tags=["core", "naming"],
        created_by=reviewer.id,
    )
    session.add(guideline)
    await session.flush()

    # 4. Create Content Submission
    submission = ContentSubmission(
        organization_id=org.id,
        author_id=author.id,
        title="Q4 Product Launch Announcement",
        content="Welcome to brandshield ai - the new compliance tool.",
        target_channel="linkedin",
        status="under_human_review",
        version=1,
    )
    session.add(submission)
    await session.flush()

    # 5. Create Compliance Report
    report = ComplianceReport(
        submission_id=submission.id,
        submission_version=1,
        is_compliant=False,
        total_violations=1,
        summary="Found 1 high-severity terminology violation.",
    )
    session.add(report)
    await session.flush()

    # 6. Create Rule Violation
    violation = RuleViolation(
        report_id=report.id,
        rule_id=guideline.id,
        rule_name=guideline.name,
        rule_type=guideline.rule_type,
        severity=guideline.severity,
        flagged_text="brandshield ai",
        char_start=11,
        char_end=25,
        explanation="Lowercase brand name violates trademark naming convention.",
    )
    session.add(violation)
    await session.flush()

    # 7. Create Multiple Evidence Citations for the Same Violation (Verifies 1:N requirement)
    citation_primary = EvidenceCitation(
        violation_id=violation.id,
        rule_id=guideline.id,
        rule_name=guideline.name,
        rule_type=guideline.rule_type,
        source_clause="Never use brandshield or Brandshield AI.",
        document_name="Official Brand Guidelines 2026",
        confidence_score=0.99,
    )
    citation_secondary = EvidenceCitation(
        violation_id=violation.id,
        rule_id=guideline.id,
        rule_name=guideline.name,
        rule_type=guideline.rule_type,
        source_clause="BrandShield AI must always capitalize both B and S.",
        document_name="Legal Trademarks Register",
        confidence_score=0.95,
    )
    session.add_all([citation_primary, citation_secondary])
    await session.flush()

    # 8. Create AI Correction Suggestion
    suggestion = CorrectionSuggestion(
        violation_id=violation.id,
        suggested_text="BrandShield AI",
        rationale="Capitalizes B and S in adherence with Section 2.1.",
        source="ai_generated",
    )
    session.add(suggestion)
    await session.flush()

    # 9. Create Human Review Decision
    decision = ReviewDecision(
        submission_id=submission.id,
        submission_version=1,
        reviewer_id=reviewer.id,
        action="edit_and_approve",
        edited_content="Welcome to BrandShield AI - the new compliance tool.",
    )
    session.add(decision)
    await session.flush()

    # Link latest_review_id on submission
    submission.latest_review_id = decision.id
    submission.status = "approved"
    await session.flush()

    # 10. Create Audit Entry
    audit = AuditEntry(
        organization_id=org.id,
        submission_id=submission.id,
        previous_status="under_human_review",
        new_status="approved",
        action_type="human_review_decision",
        actor_id=str(reviewer.id),
        actor_type="human",
        actor_name=reviewer.full_name,
        notes="Human reviewer edited and approved draft.",
    )
    session.add(audit)
    await session.commit()

    # Verification: Query and assert all relations
    query = select(Organization).where(Organization.id == org.id)
    result = await session.execute(query)
    queried_org = result.scalar_one()

    assert len(queried_org.users) == 2
    assert len(queried_org.guidelines) == 1
    assert len(queried_org.submissions) == 1
    assert len(queried_org.audit_entries) == 1

    # Verify multiple citations per violation
    v_query = select(RuleViolation).where(RuleViolation.id == violation.id)
    v_res = await session.execute(v_query)
    queried_violation = v_res.scalar_one()
    assert len(queried_violation.evidence_citations) == 2
    assert len(queried_violation.suggestions) == 1
    assert queried_violation.suggestions[0].source == "ai_generated"


@pytest.mark.asyncio
async def test_audit_entry_immutability(async_test_session: AsyncSession) -> None:
    """Test that AuditEntry cannot be mutated or deleted via ORM (raises ImmutableAuditError)."""
    session = async_test_session

    org = Organization(name="Audit Test Org", slug="audit-test-org")
    session.add(org)
    await session.flush()
    org_id = org.id

    sub = ContentSubmission(
        organization_id=org_id,
        title="Audit Test Draft",
        content="Test content",
        target_channel="email",
    )
    session.add(sub)
    await session.flush()
    sub_id = sub.id

    # 1. Test update rejection
    audit_update_target = AuditEntry(
        organization_id=org_id,
        submission_id=sub_id,
        previous_status="draft",
        new_status="submitted",
        action_type="submit",
        actor_id="user_123",
        actor_type="human",
        actor_name="Human User",
    )
    session.add(audit_update_target)
    await session.commit()

    audit_update_target.notes = "Mutated note"
    with pytest.raises(ImmutableAuditError) as exc_info_update:
        await session.flush()
    assert "Audit entries are immutable and cannot be updated" in str(exc_info_update.value)

    await session.rollback()

    # 2. Test delete rejection on committed entry
    audit_delete_target = AuditEntry(
        organization_id=org_id,
        submission_id=sub_id,
        previous_status="submitted",
        new_status="under_human_review",
        action_type="assign_review",
        actor_id="user_123",
        actor_type="human",
        actor_name="Human User",
    )
    session.add(audit_delete_target)
    await session.commit()

    with pytest.raises(ImmutableAuditError) as exc_info_delete:
        await session.delete(audit_delete_target)
        await session.flush()
    assert "Audit entries are immutable and cannot be deleted" in str(exc_info_delete.value)


@pytest.mark.asyncio
async def test_audit_entry_database_level_triggers_block_raw_sql(async_test_session: AsyncSession) -> None:
    """Verify that native database triggers reject raw SQL UPDATE and DELETE on audit_entries,
    proving immutability is enforced at the database layer beyond ORM event listeners.
    """
    session = async_test_session

    org = Organization(name="Trigger Test Org", slug="trigger-test-org")
    session.add(org)
    await session.flush()

    sub = ContentSubmission(
        organization_id=org.id,
        title="Trigger Test Draft",
        content="Testing raw SQL trigger enforcement",
        target_channel="press_release",
    )
    session.add(sub)
    await session.flush()

    audit_entry = AuditEntry(
        id=uuid.uuid4(),
        organization_id=org.id,
        submission_id=sub.id,
        previous_status="draft",
        new_status="submitted",
        action_type="submit",
        actor_id="user_admin",
        actor_type="human",
        actor_name="Test Admin",
        notes="Original note before raw SQL attack",
    )
    session.add(audit_entry)
    await session.commit()

    # Save audit ID string/hex before any session operations/rollbacks to avoid async greenlet lazy-load
    audit_id_hex = audit_entry.id.hex

    # 1. Attempt raw SQL UPDATE bypassing SQLAlchemy ORM entity events
    with pytest.raises((DBAPIError, Exception)) as exc_raw_update:
        await session.execute(
            text("UPDATE audit_entries SET notes = 'tampered' WHERE id = :id"),
            {"id": audit_id_hex},
        )
        await session.commit()
    assert "immutable" in str(exc_raw_update.value).lower()
    await session.rollback()

    # 2. Attempt raw SQL DELETE bypassing SQLAlchemy ORM entity events
    with pytest.raises((DBAPIError, Exception)) as exc_raw_delete:
        await session.execute(
            text("DELETE FROM audit_entries WHERE id = :id"),
            {"id": audit_id_hex},
        )
        await session.commit()
    assert "immutable" in str(exc_raw_delete.value).lower()
    await session.rollback()


@pytest.mark.asyncio
async def test_foreign_key_restrict_prevents_parent_deletion_with_audit_entries(async_test_session: AsyncSession) -> None:
    """Verify that ondelete='RESTRICT' blocks hard-deletion of parent submissions and organizations
    when audit entries exist, preventing cascade destruction of the immutable audit history.
    """
    session = async_test_session

    org = Organization(name="Restrict Test Org", slug="restrict-test-org")
    session.add(org)
    await session.flush()

    sub = ContentSubmission(
        organization_id=org.id,
        title="Restrict Test Draft",
        content="Cannot be hard deleted because audit history exists",
        target_channel="blog_post",
    )
    session.add(sub)
    await session.flush()

    audit = AuditEntry(
        id=uuid.uuid4(),
        organization_id=org.id,
        submission_id=sub.id,
        previous_status="draft",
        new_status="submitted",
        action_type="submit",
        actor_id="user_creator",
        actor_type="human",
        actor_name="Creator User",
    )
    session.add(audit)
    await session.commit()

    # Save identifiers before any rollbacks to avoid async lazy-loading
    sub_id = sub.id
    sub_id_hex = sub.id.hex
    org_id_hex = org.id.hex

    # 1. Attempting ORM-level deletion of submission is blocked by audit immutability
    with pytest.raises((ImmutableAuditError, IntegrityError)):
        await session.delete(sub)
        await session.flush()
    await session.rollback()

    # 2. Attempting raw SQL deletion of submission is blocked by DB-level FK RESTRICT
    with pytest.raises(IntegrityError):
        await session.execute(
            text("DELETE FROM content_submissions WHERE id = :id"),
            {"id": sub_id_hex},
        )
        await session.commit()
    await session.rollback()

    # 3. Attempting raw SQL deletion of parent organization is blocked by DB-level FK RESTRICT
    with pytest.raises(IntegrityError):
        await session.execute(
            text("DELETE FROM organizations WHERE id = :id"),
            {"id": org_id_hex},
        )
        await session.commit()
    await session.rollback()

    # 4. Safe archival alternative: submission can be safely archived without deletion
    refetched_sub = (await session.execute(select(ContentSubmission).where(ContentSubmission.id == sub_id))).scalar_one()
    refetched_sub.is_archived = True
    refetched_sub.archived_at = datetime.now(timezone.utc)
    await session.commit()
    assert refetched_sub.is_archived is True


@pytest.mark.asyncio
async def test_database_check_constraints(async_test_session: AsyncSession) -> None:
    """Test database-level CheckConstraints (approval invariant, review feedback requirements)."""
    session = async_test_session

    org = Organization(name="Constraint Org", slug="constraint-org")
    session.add(org)
    await session.flush()

    # 1. Unapproved content submission cannot be in approved status without latest_review_id
    sub = ContentSubmission(
        organization_id=org.id,
        title="Unreviewed Approved Content",
        content="Should fail DB check",
        target_channel="twitter_x",
        status="approved",
        latest_review_id=None,  # Violates chk_submission_approved_has_review
    )
    session.add(sub)
    with pytest.raises(IntegrityError):
        await session.flush()

    await session.rollback()

    # Re-add org for next check
    session.add(org)
    await session.flush()

    # 2. Non-human actor cannot approve in audit entry
    sub_valid = ContentSubmission(
        organization_id=org.id,
        title="Valid Draft",
        content="Valid content",
        target_channel="twitter_x",
    )
    session.add(sub_valid)
    await session.flush()

    bad_audit = AuditEntry(
        organization_id=org.id,
        submission_id=sub_valid.id,
        previous_status="under_human_review",
        new_status="approved",
        action_type="auto_approval",
        actor_id="ai_agent_id",
        actor_type="ai_agent",  # Violates chk_audit_human_approval_only
        actor_name="AI Agent",
    )
    session.add(bad_audit)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_tenant_isolation_filtering(async_test_session: AsyncSession) -> None:
    """Verify that multiple tenants remain strictly segregated by organization_id."""
    session = async_test_session

    org_a = Organization(name="Tenant Alpha", slug="tenant-alpha")
    org_b = Organization(name="Tenant Beta", slug="tenant-beta")
    session.add_all([org_a, org_b])
    await session.flush()

    # Create guidelines in Org A
    g_a = BrandGuideline(
        organization_id=org_a.id,
        name="Alpha Rule",
        rule_type="terminology",
        description="Alpha description",
        directive="Alpha directive",
    )
    # Create guidelines in Org B
    g_b = BrandGuideline(
        organization_id=org_b.id,
        name="Beta Rule",
        rule_type="terminology",
        description="Beta description",
        directive="Beta directive",
    )
    session.add_all([g_a, g_b])
    await session.commit()

    # Query filtered by Tenant Alpha
    query_a = select(BrandGuideline).where(BrandGuideline.organization_id == org_a.id)
    res_a = await session.execute(query_a)
    alpha_rules = res_a.scalars().all()

    assert len(alpha_rules) == 1
    assert alpha_rules[0].name == "Alpha Rule"

    # Query filtered by Tenant Beta
    query_b = select(BrandGuideline).where(BrandGuideline.organization_id == org_b.id)
    res_b = await session.execute(query_b)
    beta_rules = res_b.scalars().all()

    assert len(beta_rules) == 1
    assert beta_rules[0].name == "Beta Rule"


@pytest.mark.asyncio
async def test_cascade_delete_integrity(async_test_session: AsyncSession) -> None:
    """Verify that deleting a report cascades to its violations, citations, and suggestions."""
    session = async_test_session

    org = Organization(name="Cascade Org", slug="cascade-org")
    session.add(org)
    await session.flush()

    g = BrandGuideline(
        organization_id=org.id,
        name="Cascade Rule",
        rule_type="tone_of_voice",
        description="Tone rule",
        directive="Tone directive",
    )
    session.add(g)
    await session.flush()

    sub = ContentSubmission(
        organization_id=org.id,
        title="Cascade Draft",
        content="Draft content",
        target_channel="blog_post",
    )
    session.add(sub)
    await session.flush()

    report = ComplianceReport(
        submission_id=sub.id,
        submission_version=1,
        is_compliant=False,
        summary="Report summary",
    )
    session.add(report)
    await session.flush()

    violation = RuleViolation(
        report_id=report.id,
        rule_id=g.id,
        rule_name=g.name,
        rule_type=g.rule_type,
        severity=g.severity,
        flagged_text="Bad tone text",
        explanation="Tone violation",
    )
    session.add(violation)
    await session.flush()

    citation = EvidenceCitation(
        violation_id=violation.id,
        rule_id=g.id,
        rule_name=g.name,
        rule_type=g.rule_type,
        source_clause="Tone directive quote",
    )
    suggestion = CorrectionSuggestion(
        violation_id=violation.id,
        suggested_text="Polite text",
        rationale="Better tone",
    )
    session.add_all([citation, suggestion])
    await session.commit()

    # Delete the report
    await session.delete(report)
    await session.commit()

    # Assert that violations, citations, and suggestions were cascaded and removed
    v_res = await session.execute(select(RuleViolation).where(RuleViolation.id == violation.id))
    assert v_res.scalar_one_or_none() is None

    c_res = await session.execute(select(EvidenceCitation).where(EvidenceCitation.id == citation.id))
    assert c_res.scalar_one_or_none() is None

    s_res = await session.execute(select(CorrectionSuggestion).where(CorrectionSuggestion.id == suggestion.id))
    assert s_res.scalar_one_or_none() is None


def test_database_engine_options() -> None:
    """Verify get_engine_options builds appropriate pooling parameters."""
    pg_opts = get_engine_options("postgresql+asyncpg://user:pass@host:5432/db")
    assert "pool_size" in pg_opts
    assert "max_overflow" in pg_opts
    assert "pool_pre_ping" in pg_opts
    assert pg_opts["pool_pre_ping"] is True

    sqlite_opts = get_engine_options("sqlite+aiosqlite:///:memory:")
    assert "pool_size" not in sqlite_opts


@pytest.mark.asyncio
async def test_set_tenant_context_postgresql_dialect() -> None:
    """Verify that PostgreSQL dialect executes parameterized set_config with transaction-local scope."""
    test_org_id = uuid.uuid4()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.bind = MagicMock()
    mock_session.bind.dialect.name = "postgresql"

    await set_tenant_context(mock_session, test_org_id)

    # Verify session.execute was called exactly once
    assert mock_session.execute.await_count == 1
    call_args = mock_session.execute.await_args
    assert call_args is not None

    statement = call_args.args[0]
    params = call_args.args[1]

    # Verify statement text matches approved safe set_config pattern
    raw_sql = str(statement.text if hasattr(statement, "text") else statement)
    assert "SELECT set_config('app.current_org_id', :org_id, true)" in raw_sql
    # Verify transaction-local scope argument is true
    assert ", true)" in raw_sql
    # Verify no raw UUID string was interpolated into the SQL statement itself
    assert str(test_org_id) not in raw_sql

    # Verify parameters dictionary contains correct UUID string bound to :org_id
    assert params == {"org_id": str(test_org_id)}


@pytest.mark.asyncio
async def test_set_tenant_context_sqlite_dialect_skipped() -> None:
    """Verify that SQLite dialect safely skips PostgreSQL-specific set_config execution."""
    test_org_id = uuid.uuid4()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.bind = MagicMock()
    mock_session.bind.dialect.name = "sqlite"

    await set_tenant_context(mock_session, test_org_id)

    # Verify session.execute was not called for SQLite
    assert mock_session.execute.await_count == 0


@pytest.mark.asyncio
async def test_set_tenant_context_unbound_session_safely_skipped() -> None:
    """Verify that sessions without an active bind or dialect safely bypass execution."""
    test_org_id = uuid.uuid4()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.bind = None

    await set_tenant_context(mock_session, test_org_id)
    assert mock_session.execute.await_count == 0
