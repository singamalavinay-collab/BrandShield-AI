import logging
from typing import List
import uuid

from sqlalchemy import select
from app.core.config import settings
from app.core.database import Base, async_session_factory, engine
from app.core.security import get_password_hash
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.user import User

logger = logging.getLogger("brandshield.bootstrap")

# Canonical identifiers for deterministic seeding
PRIMARY_ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
REVIEWER_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
CREATOR_USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")

DEFAULT_GUIDELINES: List[dict] = [
    {
        "id": uuid.UUID("00000001-0000-0000-0000-000000000001"),
        "name": "BrandShield AI Capitalization & Spacing",
        "rule_type": "trademark_usage",
        "severity": "critical",
        "description": "Enforces correct camel-case spelling and spacing for BrandShield AI.",
        "directive": 'Always spell as two words: "BrandShield" (one word, capital B and S) followed by a space and "AI". Never write as "Brandshield", "Brand Shield", or "BrandshieldAI".',
        "examples_approved": [
            "BrandShield AI protects enterprise brand integrity.",
            "Deploy BrandShield AI in your compliance pipeline.",
        ],
        "examples_prohibited": [
            "Brandshield provides brand checking.",
            "Brand Shield AI is easy to set up.",
            "Try brandshieldai today.",
        ],
        "tags": ["trademark", "naming", "spelling"],
        "is_active": True,
    },
    {
        "id": uuid.UUID("00000002-0000-0000-0000-000000000002"),
        "name": "Absolute Security Claim Prohibition",
        "rule_type": "prohibited_claims",
        "severity": "high",
        "description": "Prohibits unqualified guarantees of 100% compliance or absolute immunity from violations.",
        "directive": "Never state that BrandShield AI guarantees 100% violation-free output or replaces human legal counsel. Frame efficacy as probabilistic assistance with mandatory human-in-the-loop oversight.",
        "examples_approved": [
            "Substantially reduces brand guideline deviations by over 90%.",
            "Assists compliance officers in detecting potential risks.",
        ],
        "examples_prohibited": [
            "Guarantees 100% brand safety on every channel.",
            "Guarantees 100% brand compliance everywhere.",
            "Eliminates all legal and regulatory risks completely.",
        ],
        "tags": ["legal", "claims", "risk-management"],
        "is_active": True,
    },
    {
        "id": uuid.UUID("00000003-0000-0000-0000-000000000003"),
        "name": "Empowering & Authoritative Tone of Voice",
        "rule_type": "tone_of_voice",
        "severity": "medium",
        "description": "Maintains professional, confident, yet humble tone avoiding exaggerated buzzwords.",
        "directive": 'Maintain an empowering, objective tone. Avoid hyperbolic jargon such as "game-changer", "revolutionary miracle", or "unmatched magic". Highlight precision, governance, and auditability.',
        "examples_approved": [
            "BrandShield AI provides rigorous governance for modern enterprise brands.",
            "Structured compliance auditing built for scale.",
        ],
        "examples_prohibited": [
            "Our revolutionary miracle AI tool guarantees 100% brand compliance everywhere.",
            "Our insane revolutionary game-changer will blow your mind!",
            "Magical AI that solves everything effortlessly.",
        ],
        "tags": ["tone", "messaging", "copywriting"],
        "is_active": True,
    },
    {
        "id": uuid.UUID("00000004-0000-0000-0000-000000000004"),
        "name": "Mandatory Human-in-the-Loop Governance Notice",
        "rule_type": "legal_regulatory",
        "severity": "critical",
        "description": "Requires explicit mention that AI proposals require human approval before publishing.",
        "directive": "Any public release describing automated workflows must explicitly state that human brand officers retain final approval authority.",
        "examples_approved": [
            "AI proposes corrections; human officers authorize publication.",
            "Includes mandatory human review before external deployment.",
        ],
        "examples_prohibited": [
            "It automatically posts to socialmedia without any human delay!",
            "AI automatically posts directly to social media without human checks.",
            "Full auto-pilot publishing enabled.",
        ],
        "tags": ["governance", "human-oversight", "regulatory"],
        "is_active": True,
    },
    {
        "id": uuid.UUID("00000005-0000-0000-0000-000000000005"),
        "name": "Standard Formatting & Terminology",
        "rule_type": "formatting",
        "severity": "low",
        "description": "Standardizes technical terms and punctuation conventions.",
        "directive": 'Use "social media" (two words, lowercase), "real-time" (hyphenated when modifying a noun), and avoid all-caps shout words in public copy.',
        "examples_approved": [
            "Delivers real-time violation alerts across social media channels.",
        ],
        "examples_prohibited": [
            "GET REAL TIME ALERTS ON SOCIALMEDIA NOW!!",
            "Check out our socialmedia updates!",
        ],
        "tags": ["formatting", "style", "typography"],
        "is_active": True,
    },
]


async def bootstrap_database() -> None:
    """Initializes schema tables and seeds baseline organization, users, and guidelines.
    
    Safe for repeated invocation (idempotent).
    """
    logger.info("Verifying database schema and initial seed data...")

    # Ensure tables exist (for SQLite local development / tests)
    async with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # 1. Organization
        org_stmt = select(Organization).where(Organization.slug == "brandshield-primary")
        org_res = await session.execute(org_stmt)
        org = org_res.scalar_one_or_none()

        if not org:
            org = Organization(
                id=PRIMARY_ORG_ID,
                name="BrandShield Primary Organization",
                slug="brandshield-primary",
                is_active=True,
            )
            session.add(org)
            await session.flush()
            logger.info("Created primary organization: %s (%s)", org.name, org.id)

        # 2. Users (Role System & Tenant Isolation Preserved)
        is_production = settings.ENVIRONMENT.lower() == "production"

        # Determine credentials:
        # In development: safe default test passwords support local UI quick-fills and test workflows.
        # In production: hardcoded demo passwords are strictly forbidden. Users must be provisioned
        # via explicit secure environment credentials or via administrative invitation workflows.
        reviewer_pw = (
            settings.BOOTSTRAP_REVIEWER_PASSWORD
            if is_production
            else (settings.BOOTSTRAP_REVIEWER_PASSWORD or "ValidReviewerPass123!")
        )
        creator_pw = (
            settings.BOOTSTRAP_CREATOR_PASSWORD
            if is_production
            else (settings.BOOTSTRAP_CREATOR_PASSWORD or "ValidCreatorPass123!")
        )

        if reviewer_pw:
            reviewer_stmt = select(User).where(User.email == "sarah.jenkins@brandshield.ai")
            reviewer_res = await session.execute(reviewer_stmt)
            if not reviewer_res.scalar_one_or_none():
                reviewer = User(
                    id=REVIEWER_USER_ID,
                    organization_id=org.id,
                    email="sarah.jenkins@brandshield.ai",
                    hashed_password=get_password_hash(reviewer_pw),
                    full_name="Sarah Jenkins (Senior Compliance Officer)",
                    role="REVIEWER",
                    is_active=True,
                )
                session.add(reviewer)
                logger.info("Seeded reviewer user: %s (Env: %s)", reviewer.email, settings.ENVIRONMENT)
        elif is_production:
            logger.info("Production mode: Reviewer demo account with hardcoded password disabled.")

        if creator_pw:
            creator_stmt = select(User).where(User.email == "mark.creator@brandshield.ai")
            creator_res = await session.execute(creator_stmt)
            if not creator_res.scalar_one_or_none():
                creator = User(
                    id=CREATOR_USER_ID,
                    organization_id=org.id,
                    email="mark.creator@brandshield.ai",
                    hashed_password=get_password_hash(creator_pw),
                    full_name="Mark Creator (Content Author)",
                    role="CREATOR",
                    is_active=True,
                )
                session.add(creator)
                logger.info("Seeded creator user: %s (Env: %s)", creator.email, settings.ENVIRONMENT)
        elif is_production:
            logger.info("Production mode: Creator demo account with hardcoded password disabled.")

        # Optional development-only administrator seeded via environment variables
        if settings.ENVIRONMENT == "development" and settings.DEV_ADMIN_EMAIL and settings.DEV_ADMIN_PASSWORD:
            admin_email = settings.DEV_ADMIN_EMAIL.strip().lower()
            admin_stmt = select(User).where(User.email == admin_email)
            admin_res = await session.execute(admin_stmt)
            if not admin_res.scalar_one_or_none():
                admin_user = User(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    email=admin_email,
                    hashed_password=get_password_hash(settings.DEV_ADMIN_PASSWORD),
                    full_name="Development Administrator",
                    role="ADMIN",
                    is_active=True,
                )
                session.add(admin_user)
                logger.info("Seeded development admin user: %s", admin_email)

        await session.flush()

        # 3. Brand Guidelines
        guideline_stmt = select(BrandGuideline).where(BrandGuideline.organization_id == org.id)
        existing_guidelines = (await session.execute(guideline_stmt)).scalars().all()
        existing_names = {g.name for g in existing_guidelines}

        for g_data in DEFAULT_GUIDELINES:
            if g_data["name"] not in existing_names:
                guideline = BrandGuideline(
                    id=g_data["id"],
                    organization_id=org.id,
                    name=g_data["name"],
                    rule_type=g_data["rule_type"],
                    severity=g_data["severity"],
                    description=g_data["description"],
                    directive=g_data["directive"],
                    examples_approved=g_data["examples_approved"],
                    examples_prohibited=g_data["examples_prohibited"],
                    tags=g_data["tags"],
                    is_active=g_data["is_active"],
                )
                session.add(guideline)
                logger.info("Seeded brand guideline: %s (%s)", guideline.name, guideline.rule_type)

        await session.commit()
        logger.info("Database bootstrap successfully concluded.")
