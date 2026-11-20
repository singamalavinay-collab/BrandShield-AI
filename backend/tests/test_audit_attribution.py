from datetime import datetime, timezone
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import get_password_hash
from app.engine.evaluator import compliance_engine
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.review import AuditEntry
from app.models.submission import ContentSubmission
from app.models.user import User
from app.schemas.auth import UserRole
from app.schemas.common import RuleType, SeverityLevel, SubmissionStatus, TargetChannel


@pytest_asyncio.fixture
async def audit_session():
    """Isolated async SQLite engine and database session for audit attribution tests."""
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
        org = Organization(
            id=uuid.uuid4(),
            name="Audit Test Org",
            slug="audit-org",
            created_at=datetime.now(timezone.utc),
        )
        session.add(org)

        admin = User(
            id=uuid.uuid4(),
            organization_id=org.id,
            email="admin@audittest.com",
            hashed_password=get_password_hash("ValidPass123!"),
            full_name="Alice Admin",
            role=UserRole.ADMIN.value,
            created_at=datetime.now(timezone.utc),
        )
        session.add(admin)

        rule = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Trademark Casing",
            rule_type=RuleType.TRADEMARK_USAGE.value,
            severity=SeverityLevel.HIGH.value,
            description="Use exact casing for BrandShield AI",
            directive="Always spell BrandShield AI with exact casing",
            is_active=True,
            examples_approved=["BrandShield AI"],
            examples_prohibited=["brandshield ai", "Brandshield"],
            created_at=datetime.now(timezone.utc),
        )
        session.add(rule)
        await session.commit()
        yield session

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_audit_actor_attribution_system(audit_session: AsyncSession):
    """Verify automated compliance inspection sets actor_type='system', actor_id='compliance_engine', and records initiating human in details."""
    res = await audit_session.execute(select(Organization).where(Organization.slug == "audit-org"))
    org = res.scalar_one()

    user_res = await audit_session.execute(select(User).where(User.email == "admin@audittest.com"))
    admin = user_res.scalar_one()

    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Trademark Test Submission",
        content="Welcome to BrandShield AI enterprise launch.",
        target_channel=TargetChannel.TWITTER_X.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    audit_session.add(submission)
    await audit_session.flush()

    report = await compliance_engine.run_inspection(
        session=audit_session,
        submission=submission,
        actor=admin,
    )
    await audit_session.commit()

    assert submission.status == SubmissionStatus.PASSED_CHECKS.value

    # Verify audit entry attribution
    audit_res = await audit_session.execute(
        select(AuditEntry).where(AuditEntry.submission_id == submission.id)
    )
    audits = audit_res.scalars().all()
    assert len(audits) == 1
    audit = audits[0]

    assert audit.action_type == "automated_compliance_inspection"
    assert audit.actor_id == "compliance_engine"
    assert audit.actor_name == "BrandShield Compliance Engine"
    assert audit.actor_type == "system"
    assert audit.details.get("triggered_by_id") == str(admin.id)
    assert audit.details.get("triggered_by_name") == "Alice Admin"
    assert audit.details.get("triggered_by_email") == "admin@audittest.com"
    assert audit.details.get("is_reinspection") is False


@pytest.mark.asyncio
async def test_audit_reinspection_action_type(audit_session: AsyncSession):
    """Verify re-running inspection when status does not change records action_type='compliance_reinspection'."""
    res = await audit_session.execute(select(Organization).where(Organization.slug == "audit-org"))
    org = res.scalar_one()

    user_res = await audit_session.execute(select(User).where(User.email == "admin@audittest.com"))
    admin = user_res.scalar_one()

    # Submission with violation so status becomes VIOLATIONS_FOUND
    submission = ContentSubmission(
        id=uuid.uuid4(),
        organization_id=org.id,
        title="Violation Test Submission",
        content="Welcome to brandshield ai enterprise launch.",
        target_channel=TargetChannel.TWITTER_X.value,
        status=SubmissionStatus.SUBMITTED.value,
        version=1,
    )
    audit_session.add(submission)
    await audit_session.flush()

    # First inspection: SUBMITTED -> VIOLATIONS_FOUND
    await compliance_engine.run_inspection(
        session=audit_session,
        submission=submission,
        actor=admin,
    )
    await audit_session.commit()
    assert submission.status == SubmissionStatus.VIOLATIONS_FOUND.value

    # Second inspection on same submission: VIOLATIONS_FOUND -> VIOLATIONS_FOUND
    await compliance_engine.run_inspection(
        session=audit_session,
        submission=submission,
        actor=admin,
    )
    await audit_session.commit()

    # Query all audit entries for this submission
    audit_res = await audit_session.execute(
        select(AuditEntry).where(AuditEntry.submission_id == submission.id).order_by(AuditEntry.timestamp)
    )
    audits = audit_res.scalars().all()
    assert len(audits) == 2

    # First entry: initial inspection
    assert audits[0].action_type == "automated_compliance_inspection"
    assert audits[0].previous_status == SubmissionStatus.SUBMITTED.value
    assert audits[0].new_status == SubmissionStatus.VIOLATIONS_FOUND.value
    assert audits[0].details.get("is_reinspection") is False

    # Second entry: re-inspection
    assert audits[1].action_type == "compliance_reinspection"
    assert audits[1].previous_status == SubmissionStatus.VIOLATIONS_FOUND.value
    assert audits[1].new_status == SubmissionStatus.VIOLATIONS_FOUND.value
    assert audits[1].details.get("is_reinspection") is True
    assert audits[1].details.get("status_reaffirmed") is True
    assert "reaffirmed" in audits[1].notes.lower()
