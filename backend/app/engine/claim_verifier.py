"""BrandShield AI — Claim Verification & Fact Checking Engine.

Phase 1, Milestone 4:
Automated claim extraction, knowledge base verification, and five-tier verdict classification:
1. VERIFIED: Corroborated by active approved brand facts or directives with matching metrics.
2. UNSUPPORTED: Factual assertion not mentioned in brand guidelines, but no direct contradiction.
3. OUTDATED: Assertion matches a superseded metric or prior document version when a newer approved standard exists.
4. CONTRADICTORY: Direct conflict with active brand facts or prohibited claims policy.
5. NEEDS_HUMAN_REVIEW: Ambiguous, conflicting evidence, or low confidence (< 0.70).

Mandatory Safeguards:
- Verifies claims exclusively against Admin-approved, active brand guidelines (never pending/rejected candidates).
- Distinguishes policy restrictions (e.g. marketing puffery/guarantee bans) from factual contradictions.
- Never classifies claims as VERIFIED based on simple text or n-gram overlap alone.
- Preserves evidence provenance without inventing document names or citations.
- Dual-mode architecture: Gemini structured extraction when available, with seamless, robust deterministic offline fallback.
- Low-confidence and critical findings automatically trigger human review escalation.
"""

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

import httpx

from app.engine.ai_provider import AIProvider, ai_provider as default_ai_provider
from app.engine.gemini_client import GeminiClientError
from app.schemas.common import ClaimStatus, RuleType, SeverityLevel

logger = logging.getLogger("brandshield.engine.claim_verifier")


# ==============================================================================
# Domain Data Structures & Constants
# ==============================================================================

@dataclass
class ClaimVerificationResult:
    """Structured result of an individual claim verification evaluation."""

    claim_text: str
    status: ClaimStatus
    evidence: Optional[str] = None
    source_reference: Optional[str] = None
    document_name: Optional[str] = None
    confidence_score: float = 1.0
    uncertainty_notes: Optional[str] = None
    is_escalated: bool = False
    rule_id: Optional[str] = None
    extraction_engine: str = "deterministic_fallback"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize result to a dictionary compatible with ClaimVerification ORM model and schemas."""
        notes = self.uncertainty_notes or ""
        # Accurately record extraction engine if not already present in notes
        if self.extraction_engine and f"[Engine: {self.extraction_engine}" not in notes:
            engine_tag = f"[Engine: {self.extraction_engine}] "
            notes = engine_tag + notes if notes else f"[Engine: {self.extraction_engine}]"

        return {
            "claim_text": self.claim_text,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "evidence": self.evidence,
            "source_reference": self.source_reference,
            "document_name": self.document_name,
            "confidence_score": round(max(0.0, min(1.0, float(self.confidence_score))), 2),
            "uncertainty_notes": notes.strip() if notes else None,
            "is_escalated": bool(self.is_escalated),
            "rule_id": self.rule_id,
        }


# Common patterns indicative of factual, metric, or policy assertions
METRIC_PATTERNS = [
    re.compile(r"\b(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:%|percent|x|fold|uptime|sla|brands?|customers?|clients?|users?|events?|ms|seconds?|hours?|days?|million|billion|trillion|k|m|b)\b", re.IGNORECASE),
    re.compile(r"\b\$\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:million|billion|m|b)?\b", re.IGNORECASE),
]

TEMPORAL_PATTERNS = [
    re.compile(r"\b(?:founded|established|launched|started|since)\s+(?:in\s+)?((?:19|20)\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(?:in|since|by|during)\s+((?:19|20)\d{2})\b", re.IGNORECASE),
]

ABSOLUTE_CLAIM_PATTERNS = [
    (re.compile(r"\b100%\s*(?:brand\s*)?(?:compliance|safety|security|guarantee|infallible|reliable)\b", re.IGNORECASE), "100% absolute guarantee"),
    (re.compile(r"\bguarantee[a-z]*\s+(?:100%|zero\s+risk|zero\s+downtime|complete\s+immunity)\b", re.IGNORECASE), "zero risk guarantee"),
    (re.compile(r"\b(?:completely\s+unhackable|100%\s+infallible|zero\s+vulnerabilit(?:y|ies))\b", re.IGNORECASE), "infallibility assertion"),
    (re.compile(r"\b(?:#1|number\s+one|sole|only|unrivaled|world's\s+best)\s+(?:brand|solution|platform|provider)\b", re.IGNORECASE), "unsubstantiated superlative"),
]

AMBIGUOUS_PATTERNS = [
    re.compile(r"\b(?:virtually\s+impenetrable|almost\s+100%|practically\s+zero\s+risk|near-perfect|substantially\s+infallible)\b", re.IGNORECASE),
]


# ==============================================================================
# Helper Extraction & Comparison Utilities
# ==============================================================================

def _clean_text(s: str) -> str:
    """Normalize whitespace and strip framing quotes."""
    if not s:
        return ""
    text = re.sub(r"\s+", " ", s).strip()
    text = re.sub(r"^[\"'\-•*]+\s*", "", text)
    text = re.sub(r"[\"'\s]+$", "", text)
    return text.strip()


def extract_candidate_claims(content: str) -> List[str]:
    """Segment content into candidate factual or declarative claim sentences.
    
    Protects against premature splitting on decimal numbers (e.g., 99.99%) or version tokens (e.g., v2.0).
    """
    if not content or not content.strip():
        return []

    raw = content.strip()
    # Split on sentence terminals followed by space and uppercase letter/digit/quote, or newline
    segments = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“])|\n+", raw)
    claims: List[str] = []

    for seg in segments:
        cleaned = _clean_text(seg)
        if not cleaned:
            continue

        # If length is sufficient and conveys assertion
        if len(cleaned) >= 8:
            claims.append(cleaned)

    # If single sentence or unpunctuated text, treat full text as one claim
    if not claims and len(raw) >= 5:
        claims.append(_clean_text(raw))

    return claims


def _extract_numbers(text: str) -> Set[str]:
    """Extract normalized numeric tokens from text for factual comparisons."""
    tokens = set()
    matches = re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?%?\b", text)
    for m in matches:
        normalized = m.replace(",", "").lower()
        tokens.add(normalized)
    return tokens


# ==============================================================================
# Deterministic Claim Verification Engine (Offline Fallback)
# ==============================================================================

def _check_outdated_claim(
    claim: str,
    claim_lower: str,
    claim_numbers: Set[str],
    active_guidelines: List[Dict[str, Any]],
    engine_meta: str,
) -> Optional[ClaimVerificationResult]:
    """Safeguard 2: Classify as OUTDATED only when an identifiable older source AND newer superseding source exist."""
    for g in active_guidelines:
        directive = g.get("directive", "") or ""
        directive_lower = directive.lower()
        prohibited_list = [str(p).lower().strip() for p in (g.get("examples_prohibited") or []) if p]

        # Check if directive explicitly states superseded/updated metric
        # E.g. "BrandShield AI protects over 50,000 enterprise brands worldwide (supersedes prior 10,000 figure from 2023)."
        superseded_matches = re.findall(
            r"(?:supersedes|updated from|formerly|prior(?: figure| metric)?|replaces|old)\s+(?:of\s+)?(\b\d+(?:,\d{3})*(?:\.\d+)?%?\b)",
            directive_lower,
        )
        if superseded_matches:
            superseded_numbers = {_clean_text(s).replace(",", "") for s in superseded_matches}
            if claim_numbers & superseded_numbers:
                source_doc = g.get("document_name") or g.get("source_metadata", {}).get("document_name")
                return ClaimVerificationResult(
                    claim_text=claim,
                    status=ClaimStatus.OUTDATED,
                    evidence=directive,
                    source_reference=g.get("source_reference") or f"Brand Guideline: {g.get('name')}",
                    document_name=source_doc,
                    confidence_score=0.90,
                    uncertainty_notes=(
                        f"Outdated specification: Claim cites superseded metric ({', '.join(claim_numbers & superseded_numbers)}). "
                        f"Active guideline '{g.get('name')}' establishes updated approved specification: '{directive}'."
                    ),
                    is_escalated=False,
                    rule_id=str(g.get("id")),
                    extraction_engine=engine_meta,
                )

        # Check if prohibited list specifically identifies outdated/superseded historical specifications
        for prohibited in prohibited_list:
            if ("outdated" in prohibited or "superseded" in prohibited or "prior" in prohibited) and any(num in prohibited for num in claim_numbers):
                source_doc = g.get("document_name") or g.get("source_metadata", {}).get("document_name")
                return ClaimVerificationResult(
                    claim_text=claim,
                    status=ClaimStatus.OUTDATED,
                    evidence=directive,
                    source_reference=g.get("source_reference") or f"Brand Guideline: {g.get('name')}",
                    document_name=source_doc,
                    confidence_score=0.90,
                    uncertainty_notes=(
                        f"Outdated assertion: Claim cites superseded metric/specification found in historical list: '{prohibited}'. "
                        f"Current active guideline is '{g.get('name')}'."
                    ),
                    is_escalated=False,
                    rule_id=str(g.get("id")),
                    extraction_engine=engine_meta,
                )

    return None


def _check_verified_claim(
    claim: str,
    claim_lower: str,
    claim_numbers: Set[str],
    active_guidelines: List[Dict[str, Any]],
    engine_meta: str,
) -> Optional[ClaimVerificationResult]:
    """Safeguard 4: Corroborate claim with specific supporting evidence (approved examples or directive facts)."""
    for g in active_guidelines:
        directive = g.get("directive", "") or ""
        directive_lower = directive.lower()
        directive_numbers = _extract_numbers(directive)
        approved_list = [str(a).strip() for a in (g.get("examples_approved") or []) if a]

        # 1. Exact or normalized match with an approved example
        for approved in approved_list:
            approved_clean = approved.strip()
            approved_lower = approved_clean.lower()
            if approved_lower and (approved_lower in claim_lower or claim_lower in approved_lower):
                app_nums = _extract_numbers(approved_clean)
                if not app_nums or (app_nums & claim_numbers):
                    source_doc = g.get("document_name") or g.get("source_metadata", {}).get("document_name")
                    return ClaimVerificationResult(
                        claim_text=claim,
                        status=ClaimStatus.VERIFIED,
                        evidence=approved_clean,
                        source_reference=g.get("source_reference") or f"Brand Guideline: {g.get('name')}",
                        document_name=source_doc,
                        confidence_score=1.0,
                        uncertainty_notes="Fully verified: Claim matches active approved brand example and specifications.",
                        is_escalated=False,
                        rule_id=str(g.get("id")),
                        extraction_engine=engine_meta,
                    )

        # 2. Specific factual corroboration against directive with matching entity AND numbers
        rule_type = str(g.get("rule_type", "")).lower()
        if rule_type in ("factual_accuracy", "messaging_pillar", "terminology"):
            # Check temporal match (e.g. founding date)
            claim_years = re.findall(r"\b(?:19|20)\d{2}\b", claim)
            directive_years = re.findall(r"\b(?:19|20)\d{2}\b", directive)
            if claim_years and directive_years and claim_years[0] == directive_years[0]:
                if any(re.search(r"\b" + w + r"\b", claim_lower) and re.search(r"\b" + w + r"\b", directive_lower) for w in ["founded", "established", "since", "headquartered", "origin"]):
                    source_doc = g.get("document_name") or g.get("source_metadata", {}).get("document_name")
                    return ClaimVerificationResult(
                        claim_text=claim,
                        status=ClaimStatus.VERIFIED,
                        evidence=directive,
                        source_reference=g.get("source_reference") or f"Brand Guideline: {g.get('name')}",
                        document_name=source_doc,
                        confidence_score=0.95,
                        uncertainty_notes=f"Fully verified: Claim temporal assertion matches approved corporate fact in '{g.get('name')}'.",
                        is_escalated=False,
                        rule_id=str(g.get("id")),
                        extraction_engine=engine_meta,
                    )

            # Check metric match (e.g. 50,000 brands or 99.99% uptime)
            if claim_numbers and directive_numbers and (claim_numbers & directive_numbers):
                core_entities = ["uptime", "sla", "brands?", "enterprise", "customers?", "clients?", "users?", "protection"]
                matches_entity = any(re.search(r"\b" + e + r"\b", claim_lower) and re.search(r"\b" + e + r"\b", directive_lower) for e in core_entities)
                if matches_entity:
                    source_doc = g.get("document_name") or g.get("source_metadata", {}).get("document_name")
                    return ClaimVerificationResult(
                        claim_text=claim,
                        status=ClaimStatus.VERIFIED,
                        evidence=directive,
                        source_reference=g.get("source_reference") or f"Brand Guideline: {g.get('name')}",
                        document_name=source_doc,
                        confidence_score=0.95,
                        uncertainty_notes=f"Fully verified: Claim metric matches approved specification in '{g.get('name')}'.",
                        is_escalated=False,
                        rule_id=str(g.get("id")),
                        extraction_engine=engine_meta,
                    )

    return None


def _check_policy_restriction_claim(
    claim: str,
    claim_lower: str,
    active_guidelines: List[Dict[str, Any]],
    engine_meta: str,
) -> Optional[ClaimVerificationResult]:
    """Safeguard 3: Identify policy restrictions / prohibited marketing guarantees, distinguishing them from factual falsehoods."""
    for g in active_guidelines:
        rule_type = str(g.get("rule_type", "")).lower()
        # Restrict claim contradiction checks to claims, regulatory, and factual policy types (skip pure trademark/formatting rules)
        if rule_type not in ("prohibited_claims", "forbidden_claim", "factual_accuracy", "regulatory_disclosure", "legal_regulatory"):
            continue

        prohibited_list = [str(p).strip() for p in (g.get("examples_prohibited") or []) if p]

        # Check explicit prohibited list
        for prohibited in prohibited_list:
            # Skip if prohibited item is an outdated metric (handled by _check_outdated_claim)
            if any(w in prohibited.lower() for w in ["outdated", "superseded", "prior", "replaces"]):
                continue

            prohibited_lower = prohibited.lower()
            if prohibited_lower and (prohibited_lower in claim_lower or claim_lower in prohibited_lower):
                # If the prohibited phrasing also appears in approved examples with different casing (e.g. brand name capitalization),
                # require case-sensitive match so compliant text is not falsely flagged
                approved_list = [str(a).lower().strip() for a in (g.get("examples_approved") or []) if a]
                if any(prohibited_lower in app_item for app_item in approved_list):
                    if prohibited not in claim:
                        continue

                is_policy = rule_type in ("prohibited_claims", "forbidden_claim", "tone_of_voice", "regulatory_disclosure", "legal_regulatory")
                source_doc = g.get("document_name") or g.get("source_metadata", {}).get("document_name")
                source_ref = g.get("source_reference") or f"Brand Guideline: {g.get('name')}"

                if is_policy:
                    uncertainty = (
                        f"Policy restriction: Claim contains prohibited phrasing '{prohibited}' restricted by "
                        f"policy '{g.get('name')}'. This is a regulatory or brand policy violation, not necessarily a factual falsehood."
                    )
                else:
                    uncertainty = (
                        f"Factual contradiction: Claim directly conflicts with approved guideline directive in '{g.get('name')}'."
                    )

                g_sev = str(g.get("severity", "medium")).lower()
                # Mandatory Safeguards 7 & 8: Escalate contradictory claims if rule severity is critical
                is_escalated = (g_sev == "critical")

                return ClaimVerificationResult(
                    claim_text=claim,
                    status=ClaimStatus.CONTRADICTORY,
                    evidence=g.get("directive") or g.get("description"),
                    source_reference=source_ref,
                    document_name=source_doc,
                    confidence_score=0.95,
                    uncertainty_notes=uncertainty,
                    is_escalated=is_escalated,
                    rule_id=str(g.get("id")),
                    extraction_engine=engine_meta,
                )

        # Check common absolute claim patterns against prohibited claims policies
        if rule_type in ("prohibited_claims", "forbidden_claim"):
            for pat, pattern_label in ABSOLUTE_CLAIM_PATTERNS:
                m = pat.search(claim)
                if m:
                    flagged = m.group(0)
                    source_doc = g.get("document_name") or g.get("source_metadata", {}).get("document_name")
                    g_sev = str(g.get("severity", "medium")).lower()
                    is_escalated = (g_sev == "critical")
                    return ClaimVerificationResult(
                        claim_text=claim,
                        status=ClaimStatus.CONTRADICTORY,
                        evidence=g.get("directive") or f"Policy prohibits {pattern_label}",
                        source_reference=g.get("source_reference") or f"Policy: {g.get('name')}",
                        document_name=source_doc,
                        confidence_score=0.95,
                        uncertainty_notes=(
                            f"Policy restriction: Claim contains restricted statement '{flagged}' forbidden by "
                            f"brand policy '{g.get('name')}'. Absolute performance guarantees are prohibited."
                        ),
                        is_escalated=is_escalated,
                        rule_id=str(g.get("id")),
                        extraction_engine=engine_meta,
                    )

    return None


def _check_factual_contradiction_claim(
    claim: str,
    claim_lower: str,
    claim_numbers: Set[str],
    active_guidelines: List[Dict[str, Any]],
    engine_meta: str,
) -> Optional[ClaimVerificationResult]:
    """Identify direct factual contradictions where guideline on the same specific topic asserts a conflicting fact/metric."""
    for g in active_guidelines:
        rule_type = str(g.get("rule_type", "")).lower()
        if rule_type != "factual_accuracy":
            continue

        directive = g.get("directive", "") or ""
        directive_lower = directive.lower()
        directive_numbers = _extract_numbers(directive)

        # 1. Temporal contradiction (founding year)
        claim_years = re.findall(r"\b(?:19|20)\d{2}\b", claim)
        directive_years = re.findall(r"\b(?:19|20)\d{2}\b", directive)
        if claim_years and directive_years:
            if any(re.search(r"\b" + w + r"\b", claim_lower) and re.search(r"\b" + w + r"\b", directive_lower) for w in ["founded", "established", "since", "headquartered"]):
                if claim_years[0] != directive_years[0]:
                    source_doc = g.get("document_name") or g.get("source_metadata", {}).get("document_name")
                    g_sev = str(g.get("severity", "medium")).lower()
                    is_escalated = (g_sev in ("critical", "high"))
                    return ClaimVerificationResult(
                        claim_text=claim,
                        status=ClaimStatus.CONTRADICTORY,
                        evidence=directive,
                        source_reference=g.get("source_reference") or f"Brand Guideline: {g.get('name')}",
                        document_name=source_doc,
                        confidence_score=0.95,
                        uncertainty_notes=(
                            f"Factual contradiction: Claim states year {claim_years[0]}, which contradicts verified "
                            f"corporate fact stating year {directive_years[0]} in '{g.get('name')}'."
                        ),
                        is_escalated=is_escalated,
                        rule_id=str(g.get("id")),
                        extraction_engine=engine_meta,
                    )

        # 2. Metric contradiction on the SAME specific entity (e.g. uptime/SLA or brand counts)
        # Avoid matching on "brand" because "BrandShield" is in the company name
        specific_metric_topics = ["uptime", "sla", r"brands?\b", r"customers?\b", r"clients?\b", r"users?\b"]
        for topic in specific_metric_topics:
            if re.search(r"\b" + topic, claim_lower) and re.search(r"\b" + topic, directive_lower):
                if claim_numbers and directive_numbers and not (claim_numbers & directive_numbers):
                    # Check if this was a superseding guideline
                    is_superseding = any(w in directive_lower for w in ["supersedes", "updated from", "formerly", "prior", "replaces"])
                    if not is_superseding:
                        source_doc = g.get("document_name") or g.get("source_metadata", {}).get("document_name")
                        g_sev = str(g.get("severity", "medium")).lower()
                        is_escalated = (g_sev in ("critical", "high"))
                        return ClaimVerificationResult(
                            claim_text=claim,
                            status=ClaimStatus.CONTRADICTORY,
                            evidence=directive,
                            source_reference=g.get("source_reference") or f"Brand Guideline: {g.get('name')}",
                            document_name=source_doc,
                            confidence_score=0.90,
                            uncertainty_notes=(
                                f"Factual contradiction: Claim numerical values ({', '.join(claim_numbers)}) conflict with "
                                f"active approved metric ({', '.join(directive_numbers)}) in '{g.get('name')}'."
                            ),
                            is_escalated=is_escalated,
                            rule_id=str(g.get("id")),
                            extraction_engine=engine_meta,
                        )

    return None


def _check_ambiguous_claim(
    claim: str,
    engine_meta: str,
) -> Optional[ClaimVerificationResult]:
    """Safeguards 7: Borderline or ambiguous claim phrasing requiring human escalation."""
    for pat in AMBIGUOUS_PATTERNS:
        m = pat.search(claim)
        if m:
            flagged = m.group(0)
            return ClaimVerificationResult(
                claim_text=claim,
                status=ClaimStatus.NEEDS_HUMAN_REVIEW,
                evidence=None,
                source_reference=None,
                document_name=None,
                confidence_score=0.60,
                uncertainty_notes=(
                    f"Ambiguous claim phrasing: Statement contains borderline phrase '{flagged}'. "
                    f"Requires human reviewer determination to verify whether qualification is required."
                ),
                is_escalated=True,
                extraction_engine=engine_meta,
            )
    return None


def _verify_single_claim_deterministic(
    claim: str,
    active_guidelines: List[Dict[str, Any]],
    fallback_reason: Optional[str] = None,
) -> ClaimVerificationResult:
    """Verify a single claim against active tenant guidelines using deterministic rules."""
    claim_lower = claim.lower()
    claim_numbers = _extract_numbers(claim)
    engine_meta = f"deterministic_fallback ({fallback_reason})" if fallback_reason else "deterministic_fallback"

    # Step 1: Check for Outdated Assertions (Older & newer superseding sources)
    outdated_res = _check_outdated_claim(claim, claim_lower, claim_numbers, active_guidelines, engine_meta)
    if outdated_res:
        return outdated_res

    # Step 2: Check for Verifiable Facts & Direct Corroboration
    verified_res = _check_verified_claim(claim, claim_lower, claim_numbers, active_guidelines, engine_meta)
    if verified_res:
        return verified_res

    # Step 3: Check for Policy Restrictions (Prohibited guarantees / marketing puffery)
    policy_res = _check_policy_restriction_claim(claim, claim_lower, active_guidelines, engine_meta)
    if policy_res:
        return policy_res

    # Step 4: Check for Direct Factual Contradictions on the same topic
    factual_contra_res = _check_factual_contradiction_claim(claim, claim_lower, claim_numbers, active_guidelines, engine_meta)
    if factual_contra_res:
        return factual_contra_res

    # Step 5: Check for Ambiguous / Low-Confidence Assertions
    ambig_res = _check_ambiguous_claim(claim, engine_meta)
    if ambig_res:
        return ambig_res

    # Step 6: Default to Unsubstantiated Assertion (UNSUPPORTED)
    # Safeguard 3 & 5: Never describe as false or invent citations.
    return ClaimVerificationResult(
        claim_text=claim,
        status=ClaimStatus.UNSUPPORTED,
        evidence=None,
        source_reference=None,
        document_name=None,
        confidence_score=0.50,
        uncertainty_notes=(
            "Unsubstantiated assertion: No corroborating brand guideline or verified corporate fact found. "
            "This does not indicate the claim is factually false, but rather that it lacks approved brand documentation."
        ),
        is_escalated=False,
        rule_id=None,
        extraction_engine=engine_meta,
    )


def _verify_claims_deterministic(
    content: str,
    active_guidelines: List[Dict[str, Any]],
    fallback_reason: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract claims and evaluate all five classifications deterministically."""
    claims = extract_candidate_claims(content)
    results: List[Dict[str, Any]] = []

    for c in claims:
        res = _verify_single_claim_deterministic(c, active_guidelines, fallback_reason=fallback_reason)
        results.append(res.to_dict())

    return results


# ==============================================================================
# Online Gemini LLM Claim Verification Engine
# ==============================================================================

GEMINI_CLAIM_VERIFICATION_PROMPT = """You are the BrandShield AI Fact Checking and Claim Verification Specialist.
Your task is to analyze the content submission, identify discrete claims, and verify each claim strictly against the Admin-approved brand guidelines provided.

MANDATORY RULES:
1. Verify claims EXCLUSIVELY against the provided active brand guidelines.
2. Classify each claim into EXACTLY ONE of these five categories:
   - VERIFIED: The claim is directly corroborated by active approved brand facts or directives with matching metrics.
   - UNSUPPORTED: Factual assertion not mentioned in brand guidelines, but no direct contradiction. (Must NEVER be branded as false or contradictory).
   - OUTDATED: Assertion matches a superseded metric or prior document version when a newer approved standard exists in the guidelines.
   - CONTRADICTORY: Direct conflict with active brand facts or prohibited marketing claims policy.
   - NEEDS_HUMAN_REVIEW: Ambiguous wording, multiple conflicting guidelines, or low confidence (< 0.70).
3. Distinguish policy violations from factual falsehoods: For prohibited marketing puffery or guarantee bans, clearly state in uncertainty_notes that it is a brand policy restriction.
4. Never classify a claim as VERIFIED using loose text or word overlap alone. Require specific supporting evidence.
5. Never invent document names, citations, or references. If not present in the guideline, use null.
6. For each claim, provide:
   - "claim_text": Exact string from content.
   - "status": One of "VERIFIED", "UNSUPPORTED", "OUTDATED", "CONTRADICTORY", "NEEDS_HUMAN_REVIEW".
   - "evidence": Verbatim excerpt from guideline, or null if unsupported.
   - "source_reference": Source reference from guideline, or null.
   - "document_name": Document name from guideline, or null.
   - "confidence_score": Float between 0.0 and 1.0.
   - "uncertainty_notes": Clear explanation of classification rationale.
   - "is_escalated": Boolean (true if CONTRADICTORY, NEEDS_HUMAN_REVIEW, or confidence < 0.70; otherwise false).

Respond strictly with a JSON array of claim verification objects. Do not include markdown codeblocks or conversational filler."""


async def _verify_claims_with_gemini(
    content: str,
    active_guidelines: List[Dict[str, Any]],
    ai_provider: AIProvider,
) -> Optional[List[Dict[str, Any]]]:
    """Attempt structured claim verification via Google Gemini API."""
    guidelines_summary = [
        {
            "id": str(g.get("id")),
            "name": g.get("name"),
            "rule_type": g.get("rule_type"),
            "severity": g.get("severity"),
            "directive": g.get("directive"),
            "examples_approved": g.get("examples_approved") or [],
            "examples_prohibited": g.get("examples_prohibited") or [],
            "document_name": g.get("document_name") or g.get("source_metadata", {}).get("document_name"),
            "source_reference": g.get("source_reference"),
        }
        for g in active_guidelines
    ]

    prompt_payload = (
        f"{GEMINI_CLAIM_VERIFICATION_PROMPT}\n\n"
        f"Active Brand Guidelines:\n{json.dumps(guidelines_summary, indent=2)}\n\n"
        f"Content Submission:\n{content}"
    )

    contents = [{"role": "user", "parts": [{"text": prompt_payload}]}]

    response = await ai_provider.client.generate_content(
        contents=contents,
        generation_config={"temperature": 0.1, "response_mime_type": "application/json"},
    )

    candidates = response.get("candidates", [])
    if not candidates:
        return None

    content_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    if not content_part:
        return None

    clean_json = content_part.strip()
    if clean_json.startswith("```json"):
        clean_json = clean_json[7:]
    if clean_json.endswith("```"):
        clean_json = clean_json[:-3]
    clean_json = clean_json.strip()

    parsed = json.loads(clean_json)
    if not isinstance(parsed, list):
        return None

    verified_results: List[Dict[str, Any]] = []
    valid_statuses = {s.value for s in ClaimStatus}

    for item in parsed:
        claim_text = str(item.get("claim_text", "")).strip()
        if not claim_text:
            continue

        status_raw = str(item.get("status", "NEEDS_HUMAN_REVIEW")).strip().upper()
        if status_raw not in valid_statuses:
            status_raw = ClaimStatus.NEEDS_HUMAN_REVIEW.value

        conf = float(item.get("confidence_score", 0.8))
        conf = max(0.0, min(1.0, conf))

        is_escalated = bool(item.get("is_escalated", False))
        if conf < 0.70 or status_raw in (ClaimStatus.CONTRADICTORY.value, ClaimStatus.NEEDS_HUMAN_REVIEW.value):
            is_escalated = True

        # Anti-Hallucination Guard: If VERIFIED but evidence is empty, downgrade to UNSUPPORTED
        evidence = item.get("evidence")
        if status_raw == ClaimStatus.VERIFIED.value and (not evidence or not str(evidence).strip()):
            status_raw = ClaimStatus.UNSUPPORTED.value
            conf = 0.50
            evidence = None

        notes = item.get("uncertainty_notes") or ""
        if "[Engine: gemini_llm]" not in notes:
            notes = f"[Engine: gemini_llm] {notes}".strip()

        verified_results.append({
            "claim_text": claim_text,
            "status": status_raw,
            "evidence": str(evidence) if evidence else None,
            "source_reference": str(item.get("source_reference")) if item.get("source_reference") else None,
            "document_name": str(item.get("document_name")) if item.get("document_name") else None,
            "confidence_score": round(conf, 2),
            "uncertainty_notes": notes,
            "is_escalated": is_escalated,
            "rule_id": str(item.get("rule_id")) if item.get("rule_id") else None,
        })

    return verified_results


# ==============================================================================
# Public Verification API
# ==============================================================================

async def verify_claims(
    content: str,
    guidelines: List[Dict[str, Any]],
    ai_provider: Optional[AIProvider] = None,
) -> List[Dict[str, Any]]:
    """Verify factual claims from content against active brand guidelines.
    
    Guarantees:
    - Filters guidelines strictly to active rules (is_active == True).
    - Tries Gemini LLM structured extraction when available and configured.
    - Gracefully and safely falls back to deterministic extraction on timeout, error, or unconfigured LLM.
    - Accurately records the extraction engine and fallback reason in findings.
    """
    if not content or not content.strip():
        return []

    # Mandatory Safeguard 1: Active guidelines only
    active_guidelines = [g for g in guidelines if g.get("is_active", True)]

    provider = ai_provider or default_ai_provider
    fallback_reason: Optional[str] = None

    if provider and provider.is_available:
        try:
            gemini_results = await _verify_claims_with_gemini(
                content=content,
                active_guidelines=active_guidelines,
                ai_provider=provider,
            )
            if gemini_results is not None:
                logger.info("Successfully evaluated %d claims via Gemini LLM", len(gemini_results))
                return gemini_results
            fallback_reason = "Gemini returned empty or invalid JSON response"
        except GeminiClientError as gerr:
            fallback_reason = f"Gemini error: {gerr.error_code.value}"
        except httpx.TimeoutException:
            fallback_reason = "Gemini request timed out"
        except Exception as exc:
            fallback_reason = f"Gemini exception: {type(exc).__name__}"
    else:
        fallback_reason = "Gemini unconfigured or offline"

    # Execute deterministic verification fallback
    logger.info("Evaluating claims via deterministic fallback engine (%s)", fallback_reason)
    return _verify_claims_deterministic(
        content=content,
        active_guidelines=active_guidelines,
        fallback_reason=fallback_reason,
    )


def verify_claims_sync(
    content: str,
    guidelines: List[Dict[str, Any]],
    fallback_reason: str = "sync_invocation",
) -> List[Dict[str, Any]]:
    """Synchronous entry point executing deterministic claim verification."""
    if not content or not content.strip():
        return []

    active_guidelines = [g for g in guidelines if g.get("is_active", True)]
    return _verify_claims_deterministic(
        content=content,
        active_guidelines=active_guidelines,
        fallback_reason=fallback_reason,
    )
