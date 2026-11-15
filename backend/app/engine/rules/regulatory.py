from typing import Any, Dict, List, Optional
from app.engine.rules.base import BaseRuleDetector


class RegulatoryRuleDetector(BaseRuleDetector):
    """Detects legal, regulatory, and disclosure non-compliance."""

    def evaluate(
        self,
        content: str,
        guideline: Dict[str, Any],
        target_channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rule_type = guideline.get("rule_type")
        if rule_type not in {"legal_regulatory", "regulatory_disclosure"}:
            return []

        violations: List[Dict[str, Any]] = []
        source_clause = self.extract_source_clause(guideline)
        prohibited_list = guideline.get("examples_prohibited") or []
        approved_list = guideline.get("examples_approved") or []

        # 1. Match explicit prohibited phrases
        for prohibited in prohibited_list:
            if not prohibited or not isinstance(prohibited, str):
                continue
            prohibited_clean = prohibited.strip()
            matches = self.find_occurrences(content, prohibited_clean, case_sensitive=False)
            for start, end, flagged in matches:
                replacement = approved_list[0] if approved_list else "regulatory compliant disclosure"
                violations.append({
                    "rule_id": str(guideline["id"]),
                    "rule_name": guideline.get("name", "Legal & Regulatory Policy"),
                    "rule_type": "legal_regulatory",
                    "severity": guideline.get("severity", "critical"),
                    "flagged_text": flagged,
                    "char_start": start,
                    "char_end": end,
                    "explanation": f"Prohibited regulatory statement '{flagged}' violates legal brand compliance standards.",
                    "source_clause": source_clause,
                    "confidence_score": 1.0,
                    "suggested_text": replacement,
                    "rationale": f"Corrected regulatory clause '{flagged}' to legally authorized copy.",
                })

        # 2. Check for required disclaimer if guideline mandates a disclosure
        directive_lower = guideline.get("directive", "").lower()
        if "must include" in directive_lower or "mandatory disclosure" in directive_lower or "required disclaimer" in directive_lower:
            # Check if any approved example or required phrase is present
            required_phrase = approved_list[0] if approved_list else ""
            if required_phrase and required_phrase.lower() not in content.lower():
                # Missing required disclaimer
                violations.append({
                    "rule_id": str(guideline["id"]),
                    "rule_name": guideline.get("name", "Mandatory Disclosure Policy"),
                    "rule_type": "legal_regulatory",
                    "severity": guideline.get("severity", "high"),
                    "flagged_text": content[-30:] if len(content) > 30 else content,
                    "char_start": len(content) - 1,
                    "char_end": len(content),
                    "explanation": f"Missing mandatory regulatory disclosure required by policy: '{required_phrase}'.",
                    "source_clause": source_clause,
                    "confidence_score": 0.90,
                    "suggested_text": f"{content.rstrip()} [{required_phrase}]",
                    "rationale": f"Appended mandatory legal disclosure '{required_phrase}' to ensure regulatory compliance.",
                })

        # 3. Governance / Human-in-the-loop policies
        if any(term in (guideline.get("name", "") + " " + source_clause).lower() for term in ["human", "governance", "approval", "oversight"]):
            import re
            gov_patterns = [
                (
                    r"\b(?:automatically\s+)?posts?\s+(?:directly\s+)?to\s+social\s*media\s+without\s+(?:any\s+)?human\s+(?:delay|checks?|oversight|intervention)\b",
                    "accelerates social media publishing with mandatory human review before distribution",
                    "Autonomous publishing claim violates mandatory human-in-the-loop governance policy.",
                ),
                (
                    r"\bwithout\s+(?:any\s+)?human\s+(?:delay|checks?|oversight|intervention)\b",
                    "with required human review and sign-off",
                    "Bypassing human approval violates mandatory governance rules.",
                ),
                (
                    r"\b(?:full\s+)?auto-?pilot\s+publishing\b",
                    "human-supervised publishing workflow",
                    "Unattended publishing claims violate brand safety controls.",
                ),
            ]
            for pat_str, suggested_repl, exp_note in gov_patterns:
                for m in re.finditer(pat_str, content, re.IGNORECASE):
                    start, end = m.start(), m.end()
                    flagged = m.group(0)

                    # Suppress nested sub-spans if already covered by an existing wider governance violation
                    if any(v.get("char_start") is not None and v["char_start"] <= start and end <= v["char_end"] for v in violations):
                        continue

                    # If this match strictly encompasses an existing narrower violation, remove the narrower one
                    violations = [
                        v for v in violations
                        if not (v.get("char_start") is not None and start <= v["char_start"] and v["char_end"] <= end)
                    ]

                    violations.append({
                        "rule_id": str(guideline["id"]),
                        "rule_name": guideline.get("name", "Human Governance Policy"),
                        "rule_type": "legal_regulatory",
                        "severity": guideline.get("severity", "critical"),
                        "flagged_text": flagged,
                        "char_start": start,
                        "char_end": end,
                        "explanation": f"{exp_note} Flagged: '{flagged}'.",
                        "source_clause": source_clause,
                        "confidence_score": 0.95,
                        "suggested_text": suggested_repl,
                        "rationale": f"Replaced autonomous publishing claim '{flagged}' with governance-compliant copy '{suggested_repl}'.",
                    })

        return violations
