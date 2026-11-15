from typing import Any, Dict, List, Optional
from app.engine.rules.base import BaseRuleDetector


class TerminologyRuleDetector(BaseRuleDetector):
    """Detects deprecated terminology, competitor references, and unauthorized jargon."""

    def evaluate(
        self,
        content: str,
        guideline: Dict[str, Any],
        target_channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rule_type = guideline.get("rule_type")
        if rule_type not in {"terminology", "competitor_reference"}:
            return []

        violations: List[Dict[str, Any]] = []
        source_clause = self.extract_source_clause(guideline)
        prohibited_list = guideline.get("examples_prohibited") or []
        approved_list = guideline.get("examples_approved") or []

        for prohibited in prohibited_list:
            if not prohibited or not isinstance(prohibited, str):
                continue
            prohibited_clean = prohibited.strip()
            matches = self.find_occurrences(content, prohibited_clean, case_sensitive=False)
            for start, end, flagged in matches:
                replacement = approved_list[0] if approved_list else "approved terminology"
                is_competitor = rule_type == "competitor_reference"
                explanation = (
                    f"Direct competitor reference '{flagged}' is forbidden under comparative advertising rules."
                    if is_competitor
                    else f"Deprecated or unapproved terminology '{flagged}'. Brand guidelines require using '{replacement}'."
                )

                violations.append({
                    "rule_id": str(guideline["id"]),
                    "rule_name": guideline.get("name", "Brand Terminology Policy"),
                    "rule_type": rule_type,
                    "severity": guideline.get("severity", "medium"),
                    "flagged_text": flagged,
                    "char_start": start,
                    "char_end": end,
                    "explanation": explanation,
                    "source_clause": source_clause,
                    "confidence_score": 1.0,
                    "suggested_text": replacement,
                    "rationale": f"Replaced '{flagged}' with brand-approved terminology '{replacement}'.",
                })

        return violations
