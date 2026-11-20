from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.engine.graph import compliance_graph
from app.engine.semantic import semantic_retriever
from app.models.compliance import (
    ClaimVerification,
    ComplianceReport,
    CorrectionSuggestion,
    EvidenceCitation,
    RuleViolation,
)
from app.models.guideline import BrandGuideline
from app.models.review import AuditEntry
from app.models.submission import ContentSubmission
from app.schemas.common import SubmissionStatus

logger = logging.getLogger("brandshield.engine.evaluator")


class ComplianceEngine:
    """Orchestrates end-to-end brand compliance inspection, LangGraph evaluation, and database persistence."""

    async def run_inspection(
        self,
        session: AsyncSession,
        submission: ContentSubmission,
        guidelines_override: Optional[List[BrandGuideline]] = None,
        actor: Optional[Any] = None,
    ) -> ComplianceReport:
        """Executes full compliance inspection for a content submission.
        
        Lifecycle Invariants:
        - Retrieves only active guidelines belonging to the submission's tenant organization.
        - Evaluates content via LangGraph deterministic and semantic nodes.
        - Persists reports, violations, citations, and suggestions.
        - Transitions submission to 'violations_found' or 'passed_checks'.
        - Records an immutable audit ledger entry.
        """
        previous_status = submission.status

        # 1. Retrieve active guidelines strictly scoped to tenant
        if guidelines_override is not None:
            active_guidelines = [g for g in guidelines_override if g.is_active]
        else:
            active_guidelines = await semantic_retriever.retrieve_relevant_guidelines(
                session=session,
                organization_id=submission.organization_id,
                content=submission.content,
                target_channel=submission.target_channel,
            )

        # Serialize guidelines for LangGraph state
        serialized_guidelines: List[Dict[str, Any]] = [
            {
                "id": str(g.id),
                "name": g.name,
                "rule_type": g.rule_type,
                "severity": g.severity,
                "description": g.description,
                "directive": g.directive,
                "examples_approved": g.examples_approved or [],
                "examples_prohibited": g.examples_prohibited or [],
                "tags": g.tags or [],
                "is_active": g.is_active,
            }
            for g in active_guidelines
        ]

        # 2. Prepare LangGraph state
        initial_state = {
            "submission_id": str(submission.id),
            "organization_id": str(submission.organization_id),
            "title": submission.title,
            "content": submission.content,
            "target_channel": submission.target_channel,
            "target_audience": submission.target_audience,
            "version": submission.version,
            "media_type": getattr(submission, "media_type", "text") or "text",
            "multimodal_metadata": getattr(submission, "multimodal_metadata", {}) or {},
            "guidelines": serialized_guidelines,
            "raw_violations": [],
            "validated_violations": [],
            "suggestions": [],
            "claims": [],
            "claim_verifications": [],
            "is_compliant": False,
            "total_violations": 0,
            "summary": "",
            "risk_score": 0.0,
            "risk_level": "LOW",
            "is_escalated": False,
            "channel_multiplier": 1.0,
            "audience_multiplier": 1.0,
            "risk_breakdown": {},
            "ai_status": {},
            "error": None,
        }

        # 3. Execute LangGraph compiled workflow
        logger.info("Executing LangGraph compliance graph for submission %s", submission.id)
        graph_result = await compliance_graph.ainvoke(initial_state)

        validated_violations = graph_result.get("validated_violations", [])
        total_violations = len(validated_violations)
        is_compliant = graph_result.get("is_compliant", False)
        summary = graph_result.get("summary", "")

        # 4. Remove any existing report for this submission version to prevent duplicate records
        await session.execute(
            delete(ComplianceReport).where(
                ComplianceReport.submission_id == submission.id,
                ComplianceReport.submission_version == submission.version,
            )
        )
        await session.flush()

        # 4b. Persist ComplianceReport entity (with deterministic risk assessment)
        report_id = uuid.uuid4()
        report = ComplianceReport(
            id=report_id,
            submission_id=submission.id,
            submission_version=submission.version,
            is_compliant=is_compliant,
            total_violations=total_violations,
            summary=summary,
            risk_score=graph_result.get("risk_score", 0.0),
            risk_level=graph_result.get("risk_level", "LOW"),
            is_escalated=graph_result.get("is_escalated", False),
            channel_multiplier=graph_result.get("channel_multiplier", 1.0),
            audience_multiplier=graph_result.get("audience_multiplier", 1.0),
            risk_breakdown=graph_result.get("risk_breakdown", {}) or {},
            analyzed_at=datetime.now(timezone.utc),
        )
        session.add(report)
        await session.flush()

        # 5. Persist RuleViolations, EvidenceCitations, and CorrectionSuggestions
        for v in validated_violations:
            viol_id = uuid.uuid4()
            violation = RuleViolation(
                id=viol_id,
                report_id=report.id,
                rule_id=uuid.UUID(v["rule_id"]),
                rule_name=v["rule_name"],
                rule_type=v["rule_type"],
                severity=v["severity"],
                flagged_text=v["flagged_text"],
                char_start=v.get("char_start"),
                char_end=v.get("char_end"),
                explanation=v["explanation"],
                created_at=datetime.now(timezone.utc),
            )
            session.add(violation)
            await session.flush()

            # Verifiable Evidence Citation
            citation = EvidenceCitation(
                id=uuid.uuid4(),
                violation_id=violation.id,
                rule_id=uuid.UUID(v["rule_id"]),
                rule_name=v["rule_name"],
                rule_type=v["rule_type"],
                source_clause=v.get("source_clause", "Official Brand Directive"),
                document_name="Official Brand Guidelines",
                confidence_score=v.get("confidence_score", 1.0),
                created_at=datetime.now(timezone.utc),
            )
            session.add(citation)

            # Grounded Correction Suggestion
            if v.get("suggested_text") and v.get("rationale"):
                suggestion = CorrectionSuggestion(
                    id=uuid.uuid4(),
                    violation_id=violation.id,
                    suggested_text=v["suggested_text"],
                    rationale=v["rationale"],
                    source="rule_derived",
                    diff_summary=f"Replace '{v['flagged_text']}' with '{v['suggested_text']}'",
                    created_at=datetime.now(timezone.utc),
                )
                session.add(suggestion)

        # 5b. Persist ClaimVerification entities (Phase 1, Milestone 4)
        claim_verifications = graph_result.get("claim_verifications", [])
        for c in claim_verifications:
            claim_rec = ClaimVerification(
                id=uuid.uuid4(),
                organization_id=submission.organization_id,
                report_id=report.id,
                claim_text=c["claim_text"],
                status=c["status"],
                evidence=c.get("evidence"),
                source_reference=c.get("source_reference"),
                document_name=c.get("document_name"),
                confidence_score=float(c.get("confidence_score", 1.0)),
                uncertainty_notes=c.get("uncertainty_notes"),
                is_escalated=bool(c.get("is_escalated", False)),
                created_at=datetime.now(timezone.utc),
            )
            session.add(claim_rec)

        # 6. Advance Submission Workflow Status
        has_contradictory_claims = any(c.get("status") == "CONTRADICTORY" for c in claim_verifications)
        if not active_guidelines:
            # Cannot advance to PASSED_CHECKS if 0 rules exist
            submission.status = SubmissionStatus.SUBMITTED.value
        elif total_violations > 0 or has_contradictory_claims:
            submission.status = SubmissionStatus.VIOLATIONS_FOUND.value
        else:
            submission.status = SubmissionStatus.PASSED_CHECKS.value

        await session.flush()

        # 7. Record Immutable Audit Ledger Entry
        claims_evaluated_count = len(claim_verifications)
        claims_escalated_count = sum(1 for c in claim_verifications if c.get("is_escalated", False))
        claims_note = f", {claims_evaluated_count} claim(s) evaluated ({claims_escalated_count} escalated)" if claims_evaluated_count else ""

        is_reinspection = (previous_status == submission.status)
        action_type = "compliance_reinspection" if is_reinspection else "automated_compliance_inspection"

        actor_id = "compliance_engine"
        actor_name = "BrandShield Compliance Engine"
        actor_type = "system"

        if is_reinspection:
            trigger_prefix = (
                f"Compliance re-inspection triggered by {actor.full_name} (status reaffirmed: '{submission.status}'): "
                if actor
                else f"Automated compliance re-inspection completed (status reaffirmed: '{submission.status}'): "
            )
        else:
            trigger_prefix = (
                f"Compliance inspection triggered by {actor.full_name}: "
                if actor
                else "Automated compliance evaluation completed: "
            )

        if active_guidelines:
            audit_notes = (
                f"{trigger_prefix}{total_violations} violation(s) detected across {len(active_guidelines)} guideline(s){claims_note}. "
                f"Risk score: {report.risk_score} ({report.risk_level}, escalated={report.is_escalated}). "
                f"Outcome: '{submission.status}'."
            )
        else:
            audit_notes = (
                f"{trigger_prefix}0 active brand guidelines configured. Content compliance cannot be evaluated."
            )

        audit = AuditEntry(
            id=uuid.uuid4(),
            organization_id=submission.organization_id,
            submission_id=submission.id,
            previous_status=previous_status,
            new_status=submission.status,
            action_type=action_type,
            actor_id=actor_id,
            actor_type=actor_type,
            actor_name=actor_name,
            notes=audit_notes,
            details={
                "report_id": str(report.id),
                "total_violations": total_violations,
                "is_compliant": is_compliant,
                "rules_evaluated": len(active_guidelines),
                "risk_score": report.risk_score,
                "risk_level": report.risk_level,
                "is_escalated": report.is_escalated,
                "is_reinspection": is_reinspection,
                "status_reaffirmed": is_reinspection,
                "channel_multiplier": report.channel_multiplier,
                "audience_multiplier": report.audience_multiplier,
                "media_type": getattr(submission, "media_type", "text") or "text",
                "file_hash_sha256": getattr(submission, "file_hash_sha256", None),
                "file_size_bytes": getattr(submission, "file_size_bytes", None),
                "claims_evaluated_count": claims_evaluated_count,
                "claims_verified_count": sum(1 for c in claim_verifications if c.get("status") == "VERIFIED"),
                "claims_unsupported_count": sum(1 for c in claim_verifications if c.get("status") == "UNSUPPORTED"),
                "claims_outdated_count": sum(1 for c in claim_verifications if c.get("status") == "OUTDATED"),
                "claims_contradictory_count": sum(1 for c in claim_verifications if c.get("status") == "CONTRADICTORY"),
                "claims_needs_review_count": sum(1 for c in claim_verifications if c.get("status") == "NEEDS_HUMAN_REVIEW"),
                "triggered_by_id": str(actor.id) if actor else None,
                "triggered_by_name": actor.full_name if actor else None,
                "triggered_by_email": getattr(actor, "email", None) if actor else None,
            },
        )
        session.add(audit)
        await session.flush()

        logger.info(
            "Completed inspection for submission %s: %d violations found, %d claims verified, status '%s'",
            submission.id,
            total_violations,
            claims_evaluated_count,
            submission.status,
        )

        # Load report with relationships eagerly populated
        loaded_stmt = (
            select(ComplianceReport)
            .where(ComplianceReport.id == report.id)
            .options(
                selectinload(ComplianceReport.violations).selectinload(RuleViolation.evidence_citations),
                selectinload(ComplianceReport.violations).selectinload(RuleViolation.suggestions),
                selectinload(ComplianceReport.claim_verifications),
            )
        )
        loaded_res = await session.execute(loaded_stmt)
        return loaded_res.scalar_one()


compliance_engine = ComplianceEngine()
