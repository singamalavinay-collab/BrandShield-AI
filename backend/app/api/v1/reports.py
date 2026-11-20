from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_organization
from app.core.database import get_db
from app.engine.remediator import remediation_synthesizer
from app.models.compliance import ComplianceReport, RuleViolation
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.submission import ContentSubmission

router = APIRouter()


@router.get(
    "/submissions/{submission_id}/report",
    summary="Retrieve Compliance Report",
    description="Retrieves the automated brand compliance report for a submission. If the automated engine has not inspected this submission yet, accurately reports pending inspection status.",
)
async def get_submission_compliance_report(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    # Verify submission belongs to tenant
    sub_stmt = select(ContentSubmission).where(
        ContentSubmission.id == submission_id,
        ContentSubmission.organization_id == org.id,
    )
    sub_res = await session.execute(sub_stmt)
    submission = sub_res.scalar_one_or_none()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content submission with id '{submission_id}' not found.",
        )

    # Query latest compliance report
    rep_stmt = (
        select(ComplianceReport)
        .where(ComplianceReport.submission_id == submission_id)
        .options(
            selectinload(ComplianceReport.violations).selectinload(RuleViolation.evidence_citations),
            selectinload(ComplianceReport.violations).selectinload(RuleViolation.suggestions),
            selectinload(ComplianceReport.claim_verifications),
        )
        .order_by(ComplianceReport.analyzed_at.desc())
        .limit(1)
    )
    rep_res = await session.execute(rep_stmt)
    report = rep_res.scalar_one_or_none()

    if not report:
        # Honest representation: Do not fabricate AI inspection results
        return {
            "is_analyzed": False,
            "status": "pending_analysis",
            "submission_id": str(submission.id),
            "submission_title": submission.title,
            "submission_version": submission.version,
            "total_violations": 0,
            "violations": [],
            "risk_score": 0.0,
            "risk_level": "LOW",
            "is_escalated": False,
            "channel_multiplier": 1.0,
            "audience_multiplier": 1.0,
            "risk_breakdown": {},
            "claim_verifications": [],
            "summary": "Compliance inspection has not been executed yet. The automated agentic evaluation engine is pending Phase 4 implementation.",
            "analyzed_at": None,
        }

    # Format actual persisted violations and citations
    formatted_violations = []
    for v in report.violations:
        formatted_violations.append({
            "id": str(v.id),
            "rule_id": str(v.rule_id),
            "rule_name": v.rule_name or (v.rule.name if getattr(v, "rule", None) else v.rule_type),
            "rule_type": v.rule_type,
            "severity": v.severity,
            "flagged_text": v.flagged_text,
            "char_start": v.char_start,
            "char_end": v.char_end,
            "explanation": v.explanation,
            "evidence_citations": [
                {
                    "id": str(c.id),
                    "rule_id": str(c.rule_id),
                    "rule_name": c.rule_name,
                    "rule_type": c.rule_type,
                    "source_clause": c.source_clause,
                    "document_name": c.document_name,
                    "confidence_score": c.confidence_score,
                }
                for c in v.evidence_citations
            ],
            "suggestions": [
                {
                    "id": str(s.id),
                    "suggested_text": s.suggested_text,
                    "rationale": s.rationale,
                    "source": s.source,
                    "diff_summary": s.diff_summary,
                }
                for s in v.suggestions
            ],
        })

    # Retrieve active guidelines to synthesize and validate compliant draft
    gl_stmt = select(BrandGuideline).where(
        BrandGuideline.organization_id == org.id,
        BrandGuideline.is_active.is_(True),
    )
    gl_res = await session.execute(gl_stmt)
    active_guidelines = gl_res.scalars().all()
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
        for g in active_guidelines
    ]

    remediation_res = remediation_synthesizer.synthesize_remediated_draft(
        content=submission.content,
        violations=formatted_violations,
        guidelines=serialized_guidelines,
    )

    formatted_claims = [
        {
            "id": str(c.id),
            "organization_id": str(c.organization_id),
            "report_id": str(c.report_id),
            "claim_text": c.claim_text,
            "status": c.status,
            "evidence": c.evidence,
            "source_reference": c.source_reference,
            "document_name": c.document_name,
            "confidence_score": c.confidence_score,
            "uncertainty_notes": c.uncertainty_notes,
            "is_escalated": c.is_escalated,
            "created_at": c.created_at.isoformat() if hasattr(c.created_at, "isoformat") else str(c.created_at),
        }
        for c in (report.claim_verifications or [])
    ]

    return {
        "is_analyzed": True,
        "status": "completed",
        "id": str(report.id),
        "submission_id": str(report.submission_id),
        "submission_title": submission.title,
        "submission_version": report.submission_version,
        "is_compliant": report.is_compliant,
        "total_violations": report.total_violations,
        "risk_score": getattr(report, "risk_score", 0.0),
        "risk_level": getattr(report, "risk_level", "LOW"),
        "is_escalated": getattr(report, "is_escalated", False),
        "channel_multiplier": getattr(report, "channel_multiplier", 1.0),
        "audience_multiplier": getattr(report, "audience_multiplier", 1.0),
        "risk_breakdown": getattr(report, "risk_breakdown", {}) or {},
        "summary": report.summary,
        "analyzed_at": report.analyzed_at.isoformat(),
        "violations": formatted_violations,
        "claim_verifications": formatted_claims,
        "remediated_draft": remediation_res["remediated_draft"],
        "remediation_summary": {
            "total_violations": remediation_res["total_violations"],
            "remediated_violations": remediation_res["remediated_violations"],
            "unresolved_violations": remediation_res["unresolved_violations"],
            "is_fully_remediated": remediation_res["is_fully_remediated"],
            "resolved_violation_ids": remediation_res["resolved_violation_ids"],
            "unresolved_violation_ids": remediation_res["unresolved_violation_ids"],
            "corruptions": remediation_res.get("corruptions", []),
        },
    }


@router.get(
    "/submissions/{submission_id}/violations",
    summary="Retrieve Detected Violations",
    description="Retrieves the list of rule violations detected in the submission.",
)
async def get_submission_violations(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> List[Dict[str, Any]]:
    report_data = await get_submission_compliance_report(submission_id, session, org)
    return report_data.get("violations", [])


@router.get(
    "/submissions/{submission_id}/suggestions",
    summary="Retrieve Correction Suggestions",
    description="Retrieves AI-generated remediation suggestions for the submission.",
)
async def get_submission_suggestions(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> List[Dict[str, Any]]:
    report_data = await get_submission_compliance_report(submission_id, session, org)
    violations = report_data.get("violations", [])
    suggestions = []
    for v in violations:
        for s in v.get("suggestions", []):
            suggestions.append({
                "violation_id": v["id"],
                "rule_name": v["rule_name"],
                **s,
            })
    return suggestions


@router.get(
    "/submissions/{submission_id}/claims",
    summary="Retrieve Claim Verifications",
    description="Retrieves the list of factual claims extracted and verified for this submission.",
)
async def get_submission_claims(
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_organization),
) -> List[Dict[str, Any]]:
    report_data = await get_submission_compliance_report(submission_id, session, org)
    return report_data.get("claim_verifications", [])
