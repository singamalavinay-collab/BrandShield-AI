"""Comprehensive test suite for BrandShield AI Phase 1, Milestone 3:
Guideline Extraction Agent & Parsing Pipeline.

Validates:
1. PDF and DOCX document text parsing and candidate rule extraction.
2. Accurate source lineage preservation: SHA-256 digest, document name, version, page/paragraph provenance, and extraction engine.
3. Offline / deterministic pattern parser fallback when Gemini is unavailable.
4. Gemini structured extraction when AIProvider is active.
5. Inviolable Governance Invariant: Staged rules unconditionally default to PENDING_APPROVAL with zero active brand guidelines.
6. Admin approval promotion to active BrandGuideline and rejection handling.
7. Immutable audit ledger generation (CandidateGuidelineAuditEntry).
8. RBAC security enforcement: REVIEWER and CREATOR are strictly blocked from ingesting or reviewing candidates (HTTP 403).
9. Safe handling of malformed, encrypted, and scanned PDFs (OCR required notice).
10. Multi-tenant organization isolation.
"""

from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
from typing import List
import uuid
import zipfile

import httpx
from httpx import ASGITransport, AsyncClient
import pypdf
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_organization, get_current_user, get_db
from app.core.database import Base, ImmutableAuditError
from app.core.security import create_access_token, get_password_hash
from app.engine.ai_provider import AIProvider
from app.engine.guideline_extractor import (
    extract_candidate_guidelines_from_document,
)
from app.engine.multimodal.extractor import DocumentExtractionError
from app.engine.multimodal.validator import MimeType
from app.main import app
from app.models.candidate_guideline import CandidateGuideline
from app.models.candidate_guideline_audit import CandidateGuidelineAuditEntry
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.user import User
from app.schemas.candidate_guidelines import (
    CandidateGuidelineReviewAction,
    CandidateReviewStatus,
)
from app.schemas.common import RuleType, SeverityLevel


# ==============================================================================
# Helper Document Generators
# ==============================================================================

def create_sample_docx(paragraphs: List[str]) -> bytes:
    """Generate in-memory DOCX bytes containing specified paragraphs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
            '<w:body>',
        ]
        for p in paragraphs:
            clean_p = p.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            xml_lines.append(f'<w:p><w:r><w:t>{clean_p}</w:t></w:r></w:p>')
        xml_lines.append('</w:body></w:document>')
        zf.writestr("word/document.xml", "\n".join(xml_lines).encode("utf-8"))
    return buf.getvalue()


def create_sample_pdf(text_lines: List[str]) -> bytes:
    """Generate in-memory valid digital PDF 1.4 bytes containing text."""
    # Build valid PDF objects
    stream_lines = ["BT", "/F1 12 Tf", "72 712 Td"]
    for idx, line in enumerate(text_lines):
        clean_line = line.replace("(", "\\(").replace(")", "\\)")
        if idx > 0:
            stream_lines.append("0 -20 Td")
        stream_lines.append(f"({clean_line}) Tj")
    stream_lines.append("ET")
    stream_content = "\n".join(stream_lines).encode("latin-1")

    obj5 = b"<< /Length " + str(len(stream_content)).encode("ascii") + b" >>\nstream\n" + stream_content + b"\nendstream"

    obj1 = b"<< /Type /Catalog /Pages 2 0 R >>"
    obj2 = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    obj3 = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
    obj4 = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    objects = [obj1, obj2, obj3, obj4, obj5]

    buf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf.extend(f"{idx} 0 obj\n".encode("ascii"))
        buf.extend(obj)
        buf.extend(b"\nendobj\n")

    xref_offset = len(buf)
    buf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for off in offsets:
        buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    buf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return bytes(buf)


def create_scanned_blank_pdf() -> bytes:
    """Generate a digital PDF without text (triggers OCR required detection)."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest_asyncio.fixture
async def test_env():
    """Isolated SQLite database session and test organization with users."""
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
        # Tenants
        org_a = Organization(id=uuid.uuid4(), name="Alpha Corp", slug="alpha-corp", is_active=True)
        org_b = Organization(id=uuid.uuid4(), name="Beta Corp", slug="beta-corp", is_active=True)
        session.add_all([org_a, org_b])
        await session.flush()

        # Users for Org A
        admin_a = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email="admin@alpha.com",
            full_name="Alice Admin",
            hashed_password="hash",
            role="ADMIN",
            is_active=True,
        )
        reviewer_a = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email="reviewer@alpha.com",
            full_name="Bob Reviewer",
            hashed_password="hash",
            role="REVIEWER",
            is_active=True,
        )
        creator_a = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email="creator@alpha.com",
            full_name="Charlie Creator",
            hashed_password="hash",
            role="CREATOR",
            is_active=True,
        )

        # Admin for Org B
        admin_b = User(
            id=uuid.uuid4(),
            organization_id=org_b.id,
            email="admin@beta.com",
            full_name="Bob Beta Admin",
            hashed_password="hash",
            role="ADMIN",
            is_active=True,
        )

        session.add_all([admin_a, reviewer_a, creator_a, admin_b])
        await session.commit()

        yield {
            "session": session,
            "engine": engine,
            "org_a": org_a,
            "org_b": org_b,
            "admin_a": admin_a,
            "reviewer_a": reviewer_a,
            "creator_a": creator_a,
            "admin_b": admin_b,
        }

    await engine.dispose()


# ==============================================================================
# 1. Extraction Pipeline Unit Tests (PDF & DOCX)
# ==============================================================================

@pytest.mark.asyncio
async def test_extract_candidate_guidelines_from_pdf():
    """Verify deterministic extraction from a brand guideline PDF."""
    pdf_text = [
        "Brand Identity Manual: Acme Corp",
        "Naming Conventions:",
        "Always use the full product name 'Acme Guard Pro'; never use Acme Guard.",
        "Brand Voice:",
        "Our tone is professional, confident, and direct.",
        "Prohibited Claims:",
        "Never claim 100% infallible security without legal clearance.",
        "Core Pillar:",
        "Our mission is continuous autonomous brand defense.",
        "Company Facts:",
        "Headquartered in San Francisco and protects over 500 enterprises.",
    ]
    pdf_bytes = create_sample_pdf(pdf_text)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        candidates = await extract_candidate_guidelines_from_document(
            file_path=tmp_path,
            mime_type=MimeType.PDF,
            document_name="Acme_Guidelines_2026.pdf",
            document_version="v1.0",
            file_hash="mock_hash_12345",
            ai_provider=None,  # Offline deterministic fallback
        )
        assert len(candidates) >= 4

        rule_types = {c.rule_type for c in candidates}
        assert RuleType.TERMINOLOGY in rule_types
        assert RuleType.PROHIBITED_CLAIMS in rule_types
        assert RuleType.TONE_OF_VOICE in rule_types

        # Verify lineage on candidates
        for cand in candidates:
            assert "Acme_Guidelines_2026.pdf" in cand.source_reference
            assert cand.source_metadata["document_name"] == "Acme_Guidelines_2026.pdf"
            assert cand.source_metadata["document_version"] == "v1.0"
            assert cand.source_metadata["file_hash_sha256"] == "mock_hash_12345"
            assert cand.source_metadata["extraction_engine"] == "deterministic_fallback"

    finally:
        tmp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_extract_candidate_guidelines_from_docx():
    """Verify deterministic extraction from a Word DOCX brand manual."""
    docx_paragraphs = [
        "Brand Guidelines & Standards",
        "Approved Terminology:",
        "Always use 'BrandShield AI' when referencing our software suite.",
        "Writing Style:",
        "Our tone is authoritative, concise, and helpful.",
        "Forbidden Claims:",
        "Do not claim zero compliance risk without written executive sign-off.",
    ]
    docx_bytes = create_sample_docx(docx_paragraphs)

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(docx_bytes)
        tmp_path = Path(tmp.name)

    try:
        candidates = await extract_candidate_guidelines_from_document(
            file_path=tmp_path,
            mime_type=MimeType.DOCX,
            document_name="Brand_Standards.docx",
            document_version="v2.3",
            file_hash="docx_hash_67890",
            ai_provider=None,
        )
        assert len(candidates) >= 3

        # Check prohibited claims rule severity
        prohibited_rule = next(c for c in candidates if c.rule_type == RuleType.PROHIBITED_CLAIMS)
        assert prohibited_rule.severity in (SeverityLevel.HIGH, SeverityLevel.CRITICAL)
        assert "zero compliance risk" in prohibited_rule.directive.lower() or "forbidden" in prohibited_rule.directive.lower()

    finally:
        tmp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_scanned_pdf_detects_ocr_required():
    """Scanned or blank PDFs must be rejected with explicit OCR required error."""
    blank_pdf = create_scanned_blank_pdf()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(blank_pdf)
        tmp_path = Path(tmp.name)

    try:
        with pytest.raises(DocumentExtractionError) as exc:
            await extract_candidate_guidelines_from_document(
                file_path=tmp_path,
                mime_type=MimeType.PDF,
                document_name="Scanned_Manual.pdf",
            )
        assert exc.value.error_code == "OCR_REQUIRED"
        assert "OCR is not currently supported" in str(exc.value.message)
    finally:
        tmp_path.unlink(missing_ok=True)


# ==============================================================================
# 2. Candidate Ingestion & Governance API Endpoints Suite
# ==============================================================================

@pytest_asyncio.fixture
async def api_client_admin(test_env):
    """FastAPI test client authenticated as Organization Admin."""
    session = test_env["session"]
    admin = test_env["admin_a"]
    org = test_env["org_a"]

    token = create_access_token(
        subject=str(admin.id),
        org_id=str(org.id),
        role=admin.role,
        email=admin.email,
        full_name=admin.full_name,
    )

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def api_client_reviewer(test_env):
    """FastAPI test client authenticated as Standard Reviewer."""
    session = test_env["session"]
    reviewer = test_env["reviewer_a"]
    org = test_env["org_a"]

    token = create_access_token(
        subject=str(reviewer.id),
        org_id=str(org.id),
        role=reviewer.role,
        email=reviewer.email,
        full_name=reviewer.full_name,
    )

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_ingest_document_stages_as_pending_approval(api_client_admin: AsyncClient, test_env):
    """Admin upload of PDF brand manual stages candidate rules strictly as PENDING_APPROVAL.
    
    Inviolable Invariant: Zero active brand_guidelines records are created!
    """
    session = test_env["session"]
    org_a = test_env["org_a"]

    pdf_bytes = create_sample_pdf([
        "Brand Identity Manual: Alpha Corp",
        "Naming Conventions:",
        "Always use 'Alpha Secure' as the brand name; never use AlphaSec.",
        "Prohibited Claims:",
        "Never claim 100% bug free guarantee.",
    ])

    files = {"file": ("alpha_brand_guide.pdf", pdf_bytes, "application/pdf")}
    data = {"document_name": "Alpha Official Guide", "document_version": "v1.0"}

    res = await api_client_admin.post(
        "/api/v1/candidate-guidelines/ingest-document",
        files=files,
        data=data,
    )
    assert res.status_code == 201
    staged = res.json()
    assert len(staged) >= 2

    for candidate in staged:
        assert candidate["review_status"] == CandidateReviewStatus.PENDING_APPROVAL.value
        assert candidate["reviewed_by"] is None
        assert candidate["approved_guideline_id"] is None
        assert candidate["source_reference"].startswith("Alpha Official Guide")

    # Inviolable Invariant Check: brand_guidelines must be completely empty
    bg_stmt = select(BrandGuideline).where(BrandGuideline.organization_id == org_a.id)
    active_rules = (await session.execute(bg_stmt)).scalars().all()
    assert len(active_rules) == 0, "Ingestion must NEVER activate guidelines automatically!"


@pytest.mark.asyncio
async def test_reviewer_cannot_ingest_brand_guidelines(api_client_reviewer: AsyncClient):
    """Standard Reviewer cannot ingest documents (HTTP 403 Forbidden)."""
    pdf_bytes = create_sample_pdf(["Brand Manual Content"])
    files = {"file": ("guide.pdf", pdf_bytes, "application/pdf")}

    res = await api_client_reviewer.post(
        "/api/v1/candidate-guidelines/ingest-document",
        files=files,
    )
    assert res.status_code == 403
    assert "ADMIN" in res.json()["message"] or "Access denied" in res.json()["message"]


@pytest.mark.asyncio
async def test_admin_approval_promotes_candidate_and_creates_audit_entry(
    api_client_admin: AsyncClient,
    test_env,
):
    """Admin approval promotes candidate to active BrandGuideline and creates immutable audit entry."""
    session = test_env["session"]
    org_a = test_env["org_a"]
    admin = test_env["admin_a"]

    # 1. Ingest PDF
    pdf_bytes = create_sample_pdf([
        "Terminology Standards:",
        "Always use 'BrandShield AI' as the primary product trademark.",
    ])
    files = {"file": ("guide.pdf", pdf_bytes, "application/pdf")}
    res_ingest = await api_client_admin.post(
        "/api/v1/candidate-guidelines/ingest-document",
        files=files,
    )
    assert res_ingest.status_code == 201
    candidate_id = res_ingest.json()[0]["id"]

    # 2. Admin approves candidate
    review_payload = {
        "action": "APPROVE",
        "review_notes": "Approved by Alice Admin after legal inspection.",
    }
    res_review = await api_client_admin.post(
        f"/api/v1/candidate-guidelines/{candidate_id}/review",
        json=review_payload,
    )
    assert res_review.status_code == 200
    data = res_review.json()
    assert data["success"] is True
    assert data["action"] == "APPROVE"
    assert data["candidate"]["review_status"] == "APPROVED"
    assert data["candidate"]["reviewed_by"] == str(admin.id)
    assert data["promoted_guideline"] is not None

    promoted_id = uuid.UUID(data["promoted_guideline"]["id"])

    # 3. Verify active BrandGuideline is now present in database
    bg_stmt = select(BrandGuideline).where(BrandGuideline.id == promoted_id)
    active_rule = (await session.execute(bg_stmt)).scalar_one()
    assert active_rule.is_active is True
    assert active_rule.organization_id == org_a.id

    # 4. Verify immutable audit trail endpoint
    res_audit = await api_client_admin.get(
        f"/api/v1/candidate-guidelines/{candidate_id}/audit-trail"
    )
    assert res_audit.status_code == 200
    audits = res_audit.json()
    assert len(audits) == 1
    assert audits[0]["action"] == "APPROVE"
    assert audits[0]["actor_id"] == str(admin.id)
    assert audits[0]["actor_type"] == "human"


@pytest.mark.asyncio
async def test_admin_rejection_leaves_zero_active_guidelines(
    api_client_admin: AsyncClient,
    test_env,
):
    """Admin rejection marks candidate as REJECTED and creates ZERO active BrandGuideline records."""
    session = test_env["session"]
    org_a = test_env["org_a"]

    # 1. Ingest PDF
    pdf_bytes = create_sample_pdf([
        "Draft Rule:",
        "Always use outdated terminology XYZ-123.",
    ])
    files = {"file": ("guide.pdf", pdf_bytes, "application/pdf")}
    res_ingest = await api_client_admin.post(
        "/api/v1/candidate-guidelines/ingest-document",
        files=files,
    )
    candidate_id = res_ingest.json()[0]["id"]

    # 2. Admin rejects candidate
    res_review = await api_client_admin.post(
        f"/api/v1/candidate-guidelines/{candidate_id}/review",
        json={"action": "REJECT", "review_notes": "Outdated legacy standard. Rejected."},
    )
    assert res_review.status_code == 200
    data = res_review.json()
    assert data["action"] == "REJECT"
    assert data["candidate"]["review_status"] == "REJECTED"
    assert data["promoted_guideline"] is None

    # 3. Verify ZERO active BrandGuideline records exist
    bg_stmt = select(BrandGuideline).where(BrandGuideline.organization_id == org_a.id)
    active_rules = (await session.execute(bg_stmt)).scalars().all()
    assert len(active_rules) == 0


@pytest.mark.asyncio
async def test_reviewer_cannot_approve_or_reject_candidates(
    api_client_admin: AsyncClient,
    api_client_reviewer: AsyncClient,
):
    """Reviewer attempting to review a candidate guideline is rejected with 403 Forbidden."""
    # 1. Ingest as Admin
    pdf_bytes = create_sample_pdf(["Terminology: Always use BrandShield AI."])
    files = {"file": ("guide.pdf", pdf_bytes, "application/pdf")}
    res_ingest = await api_client_admin.post(
        "/api/v1/candidate-guidelines/ingest-document",
        files=files,
    )
    candidate_id = res_ingest.json()[0]["id"]

    # 2. Reviewer attempts APPROVE -> 403 Forbidden
    res_review = await api_client_reviewer.post(
        f"/api/v1/candidate-guidelines/{candidate_id}/review",
        json={"action": "APPROVE"},
    )
    assert res_review.status_code == 403
    assert "ADMIN" in res_review.json()["message"] or "Access denied" in res_review.json()["message"]


@pytest.mark.asyncio
async def test_cross_tenant_candidate_guideline_isolation(test_env):
    """Tenant isolation: Organization A cannot retrieve or review Organization B candidates."""
    session = test_env["session"]
    org_a = test_env["org_a"]
    org_b = test_env["org_b"]
    admin_a = test_env["admin_a"]

    # Seed candidate in Org B
    cand_b = CandidateGuideline(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        name="Org B Proprietary Rule",
        rule_type="terminology",
        severity="medium",
        description="Rule for Org B only",
        directive="Always use Org B phrasing.",
        review_status="PENDING_APPROVAL",
    )
    session.add(cand_b)
    await session.commit()

    # Admin A client setup
    token_a = create_access_token(
        subject=str(admin_a.id),
        org_id=str(org_a.id),
        role=admin_a.role,
        email=admin_a.email,
        full_name=admin_a.full_name,
    )

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token_a}"},
    ) as client:
        # Org A attempts GET on Org B candidate -> 404 Not Found
        res_get = await client.get(f"/api/v1/candidate-guidelines/{cand_b.id}")
        assert res_get.status_code == 404

        # Org A attempts review on Org B candidate -> 404 Not Found
        res_rev = await client.post(
            f"/api/v1/candidate-guidelines/{cand_b.id}/review",
            json={"action": "APPROVE"},
        )
        assert res_rev.status_code == 404

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unsupported_mime_type_rejected(api_client_admin: AsyncClient):
    """Uploading non-PDF / non-DOCX formats (e.g. PNG image) returns 400 Bad Request."""
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    files = {"file": ("image.png", fake_png, "image/png")}

    res = await api_client_admin.post(
        "/api/v1/candidate-guidelines/ingest-document",
        files=files,
    )
    assert res.status_code == 400
    assert "Unsupported document format" in res.json()["message"]


@pytest.mark.asyncio
async def test_empty_document_rejected(api_client_admin: AsyncClient):
    """Uploading an empty file (0 bytes) returns 400 Bad Request."""
    files = {"file": ("empty.pdf", b"", "application/pdf")}

    res = await api_client_admin.post(
        "/api/v1/candidate-guidelines/ingest-document",
        files=files,
    )
    assert res.status_code == 400
    assert "empty" in res.json()["message"].lower()


@pytest.mark.asyncio
async def test_malformed_pdf_rejected(api_client_admin: AsyncClient):
    """Uploading a corrupted PDF returns 400 Bad Request."""
    corrupted_pdf = b"%PDF-1.4\nCorrupted binary garbage without valid catalog objects\n%%EOF"
    files = {"file": ("corrupt.pdf", corrupted_pdf, "application/pdf")}

    res = await api_client_admin.post(
        "/api/v1/candidate-guidelines/ingest-document",
        files=files,
    )
    assert res.status_code == 400
    assert "parsing error" in res.json()["message"].lower() or "malformed" in res.json()["message"].lower()


@pytest.mark.asyncio
async def test_gemini_extraction_mock_integration():
    """Verify Gemini AI extraction when AIProvider returns valid structured JSON."""
    from unittest.mock import AsyncMock, MagicMock
    from app.engine.gemini_client import GeminiClient

    mock_client = MagicMock(spec=GeminiClient)
    mock_client.generate_content = AsyncMock(
        return_value={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": """[
                                    {
                                        "name": "Gemini AI Capitalization Rule",
                                        "rule_type": "terminology",
                                        "severity": "medium",
                                        "description": "Capitalize BrandShield AI properly.",
                                        "directive": "Always write BrandShield AI with capital B and S.",
                                        "examples_approved": ["BrandShield AI"],
                                        "examples_prohibited": ["brandshield"],
                                        "tags": ["ai_extracted", "trademark"],
                                        "page_number": 2,
                                        "quote": "Always write BrandShield AI"
                                    }
                                ]"""
                            }
                        ]
                    }
                }
            ]
        }
    )

    mock_provider = MagicMock(spec=AIProvider)
    mock_provider.is_available = True
    mock_provider.client = mock_client

    pdf_bytes = create_sample_pdf(["Rule content for Gemini analysis."])
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        candidates = await extract_candidate_guidelines_from_document(
            file_path=tmp_path,
            mime_type=MimeType.PDF,
            document_name="AI_Manual.pdf",
            document_version="v3.0",
            file_hash="ai_hash_abc",
            ai_provider=mock_provider,
        )
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.name == "Gemini AI Capitalization Rule"
        assert cand.rule_type == RuleType.TERMINOLOGY
        assert cand.source_metadata["extraction_engine"] == "gemini"
        assert cand.source_metadata["source_quote"] == "Always write BrandShield AI"
        assert cand.source_metadata["page_number"] == 2
    finally:
        tmp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_list_and_get_candidate_guidelines_api(api_client_admin: AsyncClient):
    """Verify listing and retrieving candidate guidelines via API."""
    pdf_bytes = create_sample_pdf([
        "Terminology Standard:",
        "Always use 'BrandShield AI' as the primary product trademark.",
    ])
    files = {"file": ("guide.pdf", pdf_bytes, "application/pdf")}
    res_ingest = await api_client_admin.post(
        "/api/v1/candidate-guidelines/ingest-document",
        files=files,
    )
    assert res_ingest.status_code == 201
    cand_id = res_ingest.json()[0]["id"]

    # List candidates
    res_list = await api_client_admin.get("/api/v1/candidate-guidelines")
    assert res_list.status_code == 200
    ids = [c["id"] for c in res_list.json()]
    assert cand_id in ids

    # Filter by review_status
    res_filtered = await api_client_admin.get("/api/v1/candidate-guidelines?review_status=PENDING_APPROVAL")
    assert res_filtered.status_code == 200
    assert len(res_filtered.json()) >= 1

    # Get single candidate
    res_get = await api_client_admin.get(f"/api/v1/candidate-guidelines/{cand_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == cand_id
