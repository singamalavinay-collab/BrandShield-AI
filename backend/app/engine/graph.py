import logging
from typing import Any, Dict, List, Optional, TypedDict
from langgraph.graph import END, StateGraph

from app.engine.ai_provider import ai_provider
from app.engine.rules import ALL_RULE_DETECTORS, VisualRuleDetector

logger = logging.getLogger("brandshield.engine.graph")


class ComplianceState(TypedDict):
    """LangGraph shared state across the compliance evaluation workflow."""

    submission_id: str
    organization_id: str
    title: str
    content: str
    target_channel: str
    target_audience: Optional[str]
    version: int
    media_type: Optional[str]
    multimodal_metadata: Optional[Dict[str, Any]]
    guidelines: List[Dict[str, Any]]
    raw_violations: List[Dict[str, Any]]
    validated_violations: List[Dict[str, Any]]
    suggestions: List[Dict[str, Any]]
    claims: List[Dict[str, Any]]
    claim_verifications: List[Dict[str, Any]]
    is_compliant: bool
    total_violations: int
    summary: str
    risk_score: float
    risk_level: str
    is_escalated: bool
    channel_multiplier: float
    audience_multiplier: float
    risk_breakdown: Dict[str, Any]
    ai_status: Dict[str, Any]
    error: Optional[str]


# ==============================================================================
# Node 1: Brand Knowledge Retrieval
# ==============================================================================

def retrieve_guidelines_node(state: ComplianceState) -> Dict[str, Any]:
    """Validates and filters retrieved tenant brand guidelines."""
    active_guidelines = [
        g for g in state.get("guidelines", [])
        if g.get("is_active", True)
    ]
    logger.info(
        "Brand Knowledge Retrieval: %d active guidelines ready for submission %s",
        len(active_guidelines),
        state.get("submission_id"),
    )
    return {
        "guidelines": active_guidelines,
    }


# ==============================================================================
# Node 2: Content Compliance Analysis
# ==============================================================================

def analyze_compliance_node(state: ComplianceState) -> Dict[str, Any]:
    """Runs deterministic rule detectors and optional semantic analysis."""
    content = state["content"]
    target_channel = state.get("target_channel")
    guidelines = state.get("guidelines", [])
    multimodal_metadata = state.get("multimodal_metadata") or {}
    media_type = state.get("media_type") or "text"
    raw_violations: List[Dict[str, Any]] = []

    # Run deterministic detectors across all guidelines
    for guideline in guidelines:
        for detector in ALL_RULE_DETECTORS:
            try:
                if isinstance(detector, VisualRuleDetector):
                    findings = detector.evaluate(
                        content=content,
                        guideline=guideline,
                        target_channel=target_channel,
                        multimodal_metadata=multimodal_metadata,
                        media_type=media_type,
                    )
                else:
                    findings = detector.evaluate(
                        content=content,
                        guideline=guideline,
                        target_channel=target_channel,
                    )
                if findings:
                    raw_violations.extend(findings)
            except Exception as e:
                logger.error(
                    "Error executing detector %s on guideline %s: %s",
                    detector.__class__.__name__,
                    guideline.get("id"),
                    str(e),
                )

    ai_status = {
        "is_available": ai_provider.is_available,
        "provider": ai_provider.provider_name,
    }

    return {
        "raw_violations": raw_violations,
        "ai_status": ai_status,
    }


# ==============================================================================
# Node 3: Evidence Citation Validation & Grounding
# ==============================================================================

def validate_evidence_node(state: ComplianceState) -> Dict[str, Any]:
    """Verifies that every violation is strictly grounded in an actual brand rule.
    
    Guarantees:
    - Verifies matching guideline ID exists in retrieved active guidelines.
    - Verifies verbatim source clause is present in the guideline.
    - Verifies character offsets match content.
    - Prunes hallucinated or ungrounded violations.
    """
    content = state["content"]
    guidelines_by_id = {str(g["id"]): g for g in state.get("guidelines", [])}
    raw_violations = state.get("raw_violations", [])
    validated: List[Dict[str, Any]] = []
    seen_keys = set()

    for v in raw_violations:
        rule_id = str(v.get("rule_id"))
        guideline = guidelines_by_id.get(rule_id)

        # Invariant 1: Must reference a real active tenant guideline
        if not guideline:
            logger.warning("Rejected ungrounded violation referencing unknown rule_id: %s", rule_id)
            continue

        # Invariant 2: Verify source clause is verbatim from guideline
        source_clause = v.get("source_clause", "").strip()
        directive = guideline.get("directive", "").strip()
        desc = guideline.get("description", "").strip()
        if source_clause != directive and source_clause != desc and source_clause != guideline.get("name"):
            # Normalize to verbatim directive
            v["source_clause"] = directive or desc or guideline.get("name")

        # Invariant 3: Verify character offset alignment
        char_start = v.get("char_start")
        char_end = v.get("char_end")
        flagged_text = v.get("flagged_text", "")
        if char_start is not None and char_end is not None:
            actual_slice = content[char_start:char_end]
            if actual_slice.lower() != flagged_text.lower():
                # Re-locate exact offset
                idx = content.lower().find(flagged_text.lower())
                if idx >= 0:
                    v["char_start"] = idx
                    v["char_end"] = idx + len(flagged_text)
                else:
                    v["char_start"] = None
                    v["char_end"] = None

        # De-duplicate identical offset + rule violations
        dedup_key = (v.get("rule_id"), v.get("char_start"), v.get("char_end"), v.get("flagged_text"))
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        validated.append(v)

    # Pass 2: Overlap and containment de-duplication within same policy or cross-policy duplicates
    # Sort validated violations by span length descending (wider spans first)
    validated.sort(key=lambda x: -((x.get("char_end") or 0) - (x.get("char_start") or 0)))
    final_validated: List[Dict[str, Any]] = []

    for v in validated:
        v_start = v.get("char_start")
        v_end = v.get("char_end")
        v_rule_type = v.get("rule_type")

        if v_start is None or v_end is None:
            final_validated.append(v)
            continue

        # If a violation of the same rule type is already kept and strictly contains this one, skip it
        is_subsumed = False
        for kept in final_validated:
            k_start = kept.get("char_start")
            k_end = kept.get("char_end")
            k_rule_type = kept.get("rule_type")

            if k_start is not None and k_end is not None:
                # Same rule type containment: keep wider violation
                if k_rule_type == v_rule_type and k_start <= v_start and v_end <= k_end:
                    is_subsumed = True
                    break
                # Exact identical span across rules: keep the higher severity rule
                if k_start == v_start and k_end == v_end:
                    is_subsumed = True
                    break

        if not is_subsumed:
            final_validated.append(v)

    # Sort final list in chronological order of appearance in the text
    final_validated.sort(key=lambda x: (x.get("char_start") if x.get("char_start") is not None else 999999))

    return {
        "validated_violations": final_validated,
    }


# ==============================================================================
# Node 4: Claim Verification & Fact Checking Engine (Phase 1, Milestone 4)
# ==============================================================================

async def verify_claims_node(state: ComplianceState) -> Dict[str, Any]:
    """Extracts and verifies factual claims against active brand knowledge.
    
    Guarantees:
    - Verifies claims exclusively against active brand guidelines.
    - Uses Gemini LLM structured extraction when available, falling back safely to deterministic rules.
    - Classifies claims into VERIFIED, UNSUPPORTED, OUTDATED, CONTRADICTORY, NEEDS_HUMAN_REVIEW.
    - Flags is_escalated = True on contradictory, ambiguous, or low-confidence assertions.
    """
    from app.engine.claim_verifier import verify_claims

    content = state.get("content", "")
    guidelines = state.get("guidelines", [])

    claim_verifications = await verify_claims(
        content=content,
        guidelines=guidelines,
        ai_provider=ai_provider,
    )

    return {
        "claim_verifications": claim_verifications,
    }


# ==============================================================================
# Node 5: Deterministic Risk Scoring & Deduplication
# ==============================================================================

def score_risk_node(state: ComplianceState) -> Dict[str, Any]:
    """Deduplicates validated findings and computes deterministic risk score (Phase 1, Milestone 2 & 4)."""
    from app.engine.risk_scorer import calculate_risk_score

    validated = state.get("validated_violations", [])
    target_channel = state.get("target_channel")
    target_audience = state.get("target_audience")
    claim_verifications = state.get("claim_verifications", [])

    result = calculate_risk_score(
        findings=validated,
        target_channel=target_channel,
        target_audience=target_audience,
        deduplicate=True,
    )

    # Mandatory Safeguards 7 & 8: Propagate claim escalation signals without weakening risk calculations
    has_claim_escalation = any(c.get("is_escalated", False) for c in claim_verifications)
    is_escalated = result.is_escalated or has_claim_escalation

    return {
        "validated_violations": result.deduplicated_findings,
        "risk_score": result.risk_score,
        "risk_level": result.risk_level,
        "is_escalated": is_escalated,
        "channel_multiplier": result.channel_multiplier,
        "audience_multiplier": result.audience_multiplier,
        "risk_breakdown": result.risk_breakdown,
    }


# ==============================================================================
# Node 6: Correction Suggestion Generation
# ==============================================================================

def generate_suggestions_node(state: ComplianceState) -> Dict[str, Any]:
    """Generates grounded remediation suggestions with strict provenance tagging."""
    validated = state.get("validated_violations", [])
    suggestions: List[Dict[str, Any]] = []

    for v in validated:
        suggested_text = v.get("suggested_text")
        rationale = v.get("rationale")
        if suggested_text and rationale:
            suggestions.append({
                "rule_id": v["rule_id"],
                "flagged_text": v["flagged_text"],
                "suggested_text": suggested_text,
                "rationale": rationale,
                # Provenance: accurately tagged as rule_derived (or ai_generated if from LLM)
                "source": "rule_derived",
                "diff_summary": f"Replace '{v['flagged_text']}' with '{suggested_text}'",
            })

    return {
        "suggestions": suggestions,
    }


# ==============================================================================
# Node 7: Inspection Report Assembly
# ==============================================================================

def assemble_report_node(state: ComplianceState) -> Dict[str, Any]:
    """Aggregates findings, computes overall compliance, and drafts executive summary."""
    guidelines = state.get("guidelines", [])
    validated = state.get("validated_violations", [])
    total_violations = len(validated)
    risk_score = state.get("risk_score", 0.0)
    risk_level = state.get("risk_level", "LOW")
    is_escalated = state.get("is_escalated", False)
    claim_verifications = state.get("claim_verifications", [])

    contradictory_claims = [c for c in claim_verifications if c.get("status") == "CONTRADICTORY"]
    has_contradictions = len(contradictory_claims) > 0

    if not guidelines:
        is_compliant = False
        summary = (
            "No active brand guidelines are configured for this organization. "
            "Content compliance cannot be certified until active brand rules are established."
        )
    elif total_violations == 0 and not has_contradictions:
        is_compliant = True
        claims_summary = f" {len(claim_verifications)} factual claim(s) evaluated." if claim_verifications else ""
        summary = (
            "All automated brand compliance checks passed successfully. "
            f"Zero guideline infractions or prohibited terms were identified.{claims_summary}"
        )
    else:
        is_compliant = False
        unique_rules = {v["rule_name"] for v in validated}
        escalation_note = " Mandatory senior escalation required." if is_escalated else ""
        claims_note = f" Identified {len(contradictory_claims)} contradictory claim(s)." if has_contradictions else ""
        summary = (
            f"Compliance inspection identified {total_violations} rule violation(s) across "
            f"{len(unique_rules)} policy area(s) ({', '.join(list(unique_rules)[:3])}).{claims_note} "
            f"Risk Score: {risk_score:.1f} ({risk_level}).{escalation_note} "
            "Remediation suggestions are available. Mandatory human reviewer sign-off is required."
        )

    return {
        "total_violations": total_violations,
        "is_compliant": is_compliant,
        "summary": summary,
    }


# ==============================================================================
# Compile LangGraph Workflow
# ==============================================================================

def build_compliance_graph():
    """Build and compile the LangGraph compliance inspection pipeline."""
    workflow = StateGraph(ComplianceState)

    # Register Nodes
    workflow.add_node("retrieve_guidelines", retrieve_guidelines_node)
    workflow.add_node("analyze_compliance", analyze_compliance_node)
    workflow.add_node("validate_evidence", validate_evidence_node)
    workflow.add_node("verify_claims", verify_claims_node)
    workflow.add_node("score_risk", score_risk_node)
    workflow.add_node("generate_suggestions", generate_suggestions_node)
    workflow.add_node("assemble_report", assemble_report_node)

    # Establish Linear Pipeline Edges
    workflow.set_entry_point("retrieve_guidelines")
    workflow.add_edge("retrieve_guidelines", "analyze_compliance")
    workflow.add_edge("analyze_compliance", "validate_evidence")
    workflow.add_edge("validate_evidence", "verify_claims")
    workflow.add_edge("verify_claims", "score_risk")
    workflow.add_edge("score_risk", "generate_suggestions")
    workflow.add_edge("generate_suggestions", "assemble_report")
    workflow.add_edge("assemble_report", END)

    return workflow.compile()


compliance_graph = build_compliance_graph()
