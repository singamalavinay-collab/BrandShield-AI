from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.engine.graph import compliance_graph
from app.engine.semantic import semantic_retriever
from app.models.compliance import ComplianceReport, CorrectionSuggestion, EvidenceCitation, RuleViolation
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
            "guidelines": serialized_guidelines,
            "raw_violations": [],
            "validated_violations": [],
            "suggestions": [],
            "is_compliant": False,
            "total_violations": 0,
            "summary": "",
            "ai_status": {},
            "error": None,
        }

        # 3. Execute LangGraph compiled workflow
        logger.info("Executing LangGraph compliance graph for submission %s", submission.id)
        graph_result = compliance_graph.invoke(initial_state)

        validated_violations = graph_result.get("validated_violations", [])
        total_violations = len(validated_violations)
        is_compliant = graph_result.get("is_compliant", False)
        summary = graph_result.get("summary", "")

        # 4. Persist ComplianceReport entity
        report_id = uuid.uuid4()
        report = ComplianceReport(
            id=report_id,
            submission_id=submission.id,
            submission_version=submission.version,
            is_compliant=is_compliant,
            total_violations=total_violations,
            summary=summary,
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

        # 6. Advance Submission Workflow Status
        if not active_guidelines:
            # Cannot advance to PASSED_CHECKS if 0 rules exist
            submission.status = SubmissionStatus.SUBMITTED.value
        elif total_violations > 0:
            submission.status = SubmissionStatus.VIOLATIONS_FOUND.value
        else:
            submission.status = SubmissionStatus.PASSED_CHECKS.value

        await session.flush()

        # 7. Record Immutable Audit Ledger Entry
        if actor:
            actor_id = str(actor.id)
            actor_name = actor.full_name
            actor_type = "human"
            audit_notes = (
                f"Compliance inspection triggered by {actor.full_name}: {total_violations} violation(s) detected across {len(active_guidelines)} guideline(s). "
                f"Outcome: '{submission.status}'."
                if active_guidelines
                else f"Compliance inspection triggered by {actor.full_name}: 0 active brand guidelines configured. Content compliance cannot be evaluated."
            )
        else:
            actor_id = "compliance_engine"
            actor_name = "BrandShield Compliance Engine"
            actor_type = "system"
            audit_notes = (
                f"Automated compliance evaluation completed: {total_violations} violation(s) detected across {len(active_guidelines)} guideline(s). "
                f"Outcome: '{submission.status}'."
                if active_guidelines
                else "Automated compliance evaluation incomplete: 0 active brand guidelines configured. Content compliance cannot be evaluated."
            )

        audit = AuditEntry(
            id=uuid.uuid4(),
            organization_id=submission.organization_id,
            submission_id=submission.id,
            previous_status=previous_status,
            new_status=submission.status,
            action_type="automated_compliance_inspection",
            actor_id=actor_id,
            actor_type=actor_type,
            actor_name=actor_name,
            notes=audit_notes,
            details={
                "report_id": str(report.id),
                "total_violations": total_violations,
                "is_compliant": is_compliant,
                "rules_evaluated": len(active_guidelines),
                "triggered_by_id": str(actor.id) if actor else None,
                "triggered_by_name": actor.full_name if actor else None,
            },
        )
        session.add(audit)
        await session.flush()

        logger.info(
            "Completed inspection for submission %s: %d violations found, status '%s'",
            submission.id,
            total_violations,
            submission.status,
        )

        # Load report with relationships eagerly populated
        loaded_stmt = (
            select(ComplianceReport)
            .where(ComplianceReport.id == report.id)
            .options(
                selectinload(ComplianceReport.violations).selectinload(RuleViolation.evidence_citations),
                selectinload(ComplianceReport.violations).selectinload(RuleViolation.suggestions),
            )
        )
        loaded_res = await session.execute(loaded_stmt)
        return loaded_res.scalar_one()


compliance_engine = ComplianceEngine()
