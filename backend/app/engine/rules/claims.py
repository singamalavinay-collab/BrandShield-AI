import re
from typing import Any, Dict, List, Optional
from app.engine.rules.base import BaseRuleDetector


class ProhibitedClaimsDetector(BaseRuleDetector):
    """Detects unsubstantiated absolute claims, non-compliant performance promises, and false warranties."""

    def evaluate(
        self,
        content: str,
        guideline: Dict[str, Any],
        target_channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rule_type = guideline.get("rule_type")
        if rule_type not in {"prohibited_claims", "forbidden_claim"}:
            return []

        violations: List[Dict[str, Any]] = []
        source_clause = self.extract_source_clause(guideline)
        prohibited_list = guideline.get("examples_prohibited") or []
        approved_list = guideline.get("examples_approved") or []

        # 1. Evaluate explicit prohibited examples from guideline
        for prohibited in prohibited_list:
            if not prohibited or not isinstance(prohibited, str):
                continue
            prohibited_clean = prohibited.strip()
            matches = self.find_occurrences(content, prohibited_clean, case_sensitive=False)
            for start, end, flagged in matches:
                # Select a qualified replacement from approved examples if available
                replacement = approved_list[0] if approved_list else "industry-leading protection"

                violations.append({
                    "rule_id": str(guideline["id"]),
                    "rule_name": guideline.get("name", "Prohibited Claims Policy"),
                    "rule_type": "prohibited_claims",
                    "severity": guideline.get("severity", "critical"),
                    "flagged_text": flagged,
                    "char_start": start,
                    "char_end": end,
                    "explanation": (
                        f"Unsubstantiated absolute claim '{flagged}'. Regulatory standards and brand policy "
                        "strictly forbid unprovable or absolute guarantees."
                    ),
                    "source_clause": source_clause,
                    "confidence_score": 1.0,
                    "suggested_text": replacement,
                    "rationale": f"Replaced absolute claim '{flagged}' with legally qualified, substantiated phrasing.",
                })

        # 2. General common absolute claim phrases if guideline is about absolute/infallibility claims
        guideline_text = (guideline.get("name", "") + " " + source_clause).lower()
        if any(keyword in guideline_text for keyword in ["absolute", "infallible", "guarantee", "100%", "risk-free", "compliance"]):
            common_claim_patterns = [
                (r"\bguarantee[a-z]*\s+100%(?:\s*(?:brand\s*)?(?:compliance|safety|security))?(?:\s+(?:across\s+(?:every|all|modern)\s+channels?|everywhere))?\b", "substantially elevates brand compliance across modern channels", "Unsubstantiated absolute performance guarantee."),
                (r"\b100%\s*(?:brand\s*)?(?:compliance|safety)\b", "comprehensive brand protection", "Absolute compliance guarantee violates advertising standards."),
                (r"\b100%\s+infallible\b", "substantially reduces risk", "Absolute claim of infallibility cannot be legally verified."),
                (r"\b100%\s+guaranteed\b", "rigorously verified", "Absolute performance guarantee violates advertising standards."),
                (r"\bguarantee[a-z]*\s+zero\s+risk\b", "engineered for enterprise risk mitigation", "Zero-risk claims are legally prohibited."),
                (r"\bcompletely\s+unhackable\b", "hardened enterprise security architecture", "Unverifiable absolute security assertion."),
            ]
            for pattern_str, suggested_repl, explanation_note in common_claim_patterns:
                for m in re.finditer(pattern_str, content, re.IGNORECASE):
                    start, end = m.start(), m.end()
                    flagged = m.group(0)

                    # Suppress nested sub-spans if already covered by an existing wider claim violation
                    if any(v.get("char_start") is not None and v["char_start"] <= start and end <= v["char_end"] for v in violations):
                        continue

                    # If this match strictly encompasses an existing narrower violation, remove the narrower one
                    violations = [
                        v for v in violations
                        if not (v.get("char_start") is not None and start <= v["char_start"] and v["char_end"] <= end)
                    ]

                    violations.append({
                        "rule_id": str(guideline["id"]),
                        "rule_name": guideline.get("name", "Prohibited Claims Policy"),
                        "rule_type": "prohibited_claims",
                        "severity": guideline.get("severity", "critical"),
                        "flagged_text": flagged,
                        "char_start": start,
                        "char_end": end,
                        "explanation": f"{explanation_note} Flagged: '{flagged}'.",
                        "source_clause": source_clause,
                        "confidence_score": 0.95,
                        "suggested_text": suggested_repl,
                        "rationale": f"Replaced absolute claim '{flagged}' with substantiated copy '{suggested_repl}'.",
                    })

        return violations
