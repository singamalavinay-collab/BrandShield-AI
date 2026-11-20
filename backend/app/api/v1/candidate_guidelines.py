"""API endpoints for Brand Guideline Document Ingestion and Candidate Rule Governance.

Phase 1, Milestone 3:
- Ingestion of PDF and DOCX brand manuals.
- Staging of extracted rules strictly as PENDING_APPROVAL.
- ADMIN-only governance review (APPROVE / REJECT).
- Immutable audit ledger tracking for all review decisions.
- Multi-tenant organization isolation.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_organization, get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_db
from app.engine.ai_provider import AIProvider
from app.engine.guideline_extractor import extract_candidate_guidelines_from_document
from app.engine.multimodal.extractor import (
    DocumentExtractionError,
    MalformedDocumentError,
)
from app.engine.multimodal.temp_manager import managed_temp_file
from app.engine.multimodal.validator import (
    MimeType,
    UploadValidationError,
    detect_mime_type_from_bytes,
)
from app.models.organization import Organization
from app.models.user import User
from app.schemas.candidate_guidelines import (
    CandidateGuidelineAuditEntryResponse,
    CandidateGuidelineResponse,
    CandidateGuidelineReviewAction,
    CandidateReviewStatus,
)
from app.schemas.guidelines import GuidelineResponse
from app.services.candidate_guideline_svc import (
    CandidateGuidelineGovernanceError,
    get_candidate_guideline,
    list_candidate_guideline_audit_entries,
    list_candidate_guidelines,
    review_candidate_guideline,
    stage_candidate_guidelines_batch,
)

logger = logging.getLogger("brandshield.api.candidate_guidelines")

router = APIRouter()


@router.post(
    "/ingest-document",
    response_model=List[CandidateGuidelineResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Brand Guideline Document for Candidate Rule Extraction",
    description=(
        "Uploads a PDF or DOCX brand guideline manual, extracts discrete brand governance rules, "
        "and stages them strictly as PENDING_APPROVAL candidate guidelines. "
        "Guarantees that newly extracted rules are NEVER automatically activated. "
        "Strictly restricted to organization ADMIN."
    ),
)
async def ingest_brand_guidelines_document(
    file: UploadFile = File(..., description="Brand guidelines manual (PDF or DOCX, max 10MB)"),
    document_name: Optional[str] = Form(None, description="Human-readable document title"),
    document_version: Optional[str] = Form(None, description="Document revision version (e.g., 'v2.1')"),
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_admin: User = Depends(require_roles("ADMIN")),
) -> List[Any]:
    clean_doc_name = (document_name or file.filename or "Brand_Guidelines.pdf").strip()
    clean_version = document_version.strip() if document_version else None

    # Derive temporary scratch file extension
    original_suffix = Path(file.filename or "").suffix.lower()
    suffix = original_suffix if original_suffix in (".pdf", ".docx") else ".tmp"

    async with managed_temp_file(suffix=suffix) as temp_path:
        # Stream file to disk enforcing 10MB ceiling and computing SHA-256
        hasher = hashlib.sha256()
        total_bytes = 0

        with open(temp_path, "wb") as f:
            while chunk := await file.read(65536):
                total_bytes += len(chunk)
                if total_bytes > settings.MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"File size exceeds maximum allowable limit of "
                            f"{settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB."
                        ),
                    )
                hasher.update(chunk)
                f.write(chunk)

        if total_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes).",
            )

        file_hash = hasher.hexdigest()

        # Sniff MIME magic bytes
        with open(temp_path, "rb") as f:
            header_bytes = f.read(8192)

        sniffed_mime = detect_mime_type_from_bytes(header_bytes)
        if sniffed_mime not in (MimeType.PDF, MimeType.DOCX):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unsupported document format. Detected type: '{sniffed_mime}'. "
                    "Only digital PDF (.pdf) and Word (.docx) brand manuals are supported."
                ),
            )

        # Execute extraction pipeline (AI or deterministic fallback)
        ai_provider = AIProvider()
        try:
            candidate_payloads = await extract_candidate_guidelines_from_document(
                file_path=temp_path,
                mime_type=sniffed_mime,
                document_name=clean_doc_name,
                document_version=clean_version,
                file_hash=file_hash,
                ai_provider=ai_provider,
            )
        except MalformedDocumentError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Malformed or invalid document: {e.message}",
            )
        except DocumentExtractionError as e:
            if e.error_code == "OCR_REQUIRED":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Document appears to be scanned or contains insufficient digital text. "
                        "Searchable digital PDF or DOCX is required. OCR is not currently supported."
                    ),
                )
            elif e.error_code == "ENCRYPTED_DOCUMENT":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password-protected or encrypted PDF cannot be parsed. Please provide an unencrypted document.",
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Document parsing error: {e.message}",
                )
        except Exception as e:
            logger.error("Unexpected failure during document extraction: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal document extraction error occurred while parsing brand guidelines.",
            )

        if not candidate_payloads:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No actionable brand governance rules could be extracted from the document.",
            )

        # Batch-stage extracted rules as PENDING_APPROVAL candidates in a single transaction
        try:
            staged_candidates = await stage_candidate_guidelines_batch(
                session=session,
                organization_id=org.id,
                payloads=candidate_payloads,
            )
            await session.commit()
            for cand in staged_candidates:
                await session.refresh(cand)
        except Exception as e:
            await session.rollback()
            logger.error("Failed to commit staged candidate guidelines: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to stage candidate guidelines in database.",
            )

        logger.info(
            "Admin %s staged %d candidate guidelines for organization %s from document '%s'",
            current_admin.id,
            len(staged_candidates),
            org.id,
            clean_doc_name,
        )
        return staged_candidates


@router.get(
    "",
    response_model=List[CandidateGuidelineResponse],
    summary="List Staged Candidate Brand Guidelines",
    description="Lists candidate guidelines staged for governance review within the active organization.",
)
async def list_candidates(
    review_status: Optional[CandidateReviewStatus] = Query(
        None,
        description="Filter by candidate review status: PENDING_APPROVAL, APPROVED, REJECTED",
    ),
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> List[Any]:
    status_filter = review_status.value if review_status else None
    return await list_candidate_guidelines(
        session=session,
        organization_id=org.id,
        review_status=status_filter,
    )


@router.get(
    "/{candidate_id}",
    response_model=CandidateGuidelineResponse,
    summary="Retrieve Discrete Candidate Brand Guideline",
    description="Retrieves a candidate guideline by ID, enforcing tenant boundaries.",
)
async def get_candidate(
    candidate_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> Any:
    candidate = await get_candidate_guideline(
        session=session,
        organization_id=org.id,
        candidate_id=candidate_id,
    )
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate guideline with ID '{candidate_id}' not found in your organization.",
        )
    return candidate


@router.post(
    "/{candidate_id}/review",
    summary="Admin Governance Review of Candidate Brand Guideline",
    description=(
        "Executes an authoritative Admin governance decision (APPROVE or REJECT) on a candidate rule. "
        "APPROVE activates the candidate into an official BrandGuideline and generates an immutable audit record. "
        "REJECT marks the candidate as permanently rejected with zero active rule creation. "
        "Strictly restricted to organization ADMIN."
    ),
)
async def review_candidate(
    candidate_id: uuid.UUID,
    payload: CandidateGuidelineReviewAction,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_admin: User = Depends(require_roles("ADMIN")),
) -> Dict[str, Any]:
    try:
        candidate, promoted_rule = await review_candidate_guideline(
            session=session,
            organization_id=org.id,
            candidate_id=candidate_id,
            actor=current_admin,
            review_payload=payload,
        )
        await session.commit()
        await session.refresh(candidate)
        if promoted_rule:
            await session.refresh(promoted_rule)
    except CandidateGuidelineGovernanceError as e:
        await session.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        await session.rollback()
        logger.error("Error executing candidate review: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record candidate guideline review decision.",
        )

    return {
        "success": True,
        "action": payload.action,
        "candidate": CandidateGuidelineResponse.model_validate(candidate),
        "promoted_guideline": GuidelineResponse.model_validate(promoted_rule) if promoted_rule else None,
    }


@router.get(
    "/{candidate_id}/audit-trail",
    response_model=List[CandidateGuidelineAuditEntryResponse],
    summary="Retrieve Immutable Audit Trail for Candidate Guideline",
    description="Retrieves the immutable governance audit history for a candidate guideline.",
)
async def get_candidate_audit_trail(
    candidate_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
) -> List[Any]:
    candidate = await get_candidate_guideline(
        session=session,
        organization_id=org.id,
        candidate_id=candidate_id,
    )
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate guideline with ID '{candidate_id}' not found in your organization.",
        )

    entries = await list_candidate_guideline_audit_entries(
        session=session,
        organization_id=org.id,
        candidate_id=candidate_id,
    )
    return list(entries)
