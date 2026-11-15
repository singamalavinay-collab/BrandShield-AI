import re
from typing import Any, Dict, List, Optional
from app.engine.rules.base import BaseRuleDetector


class TrademarkRuleDetector(BaseRuleDetector):
    """Detects brand trademark infractions, capitalization errors, and unauthorized product naming."""

    def evaluate(
        self,
        content: str,
        guideline: Dict[str, Any],
        target_channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if guideline.get("rule_type") != "trademark_usage":
            return []

        violations: List[Dict[str, Any]] = []
        source_clause = self.extract_source_clause(guideline)
        prohibited_list = guideline.get("examples_prohibited") or []
        approved_list = guideline.get("examples_approved") or []

        # 1. Evaluate explicit prohibited examples
        for prohibited in prohibited_list:
            if not prohibited or not isinstance(prohibited, str):
                continue
            prohibited_clean = prohibited.strip()
            # Match exact prohibited casing or variation
            matches = self.find_occurrences(content, prohibited_clean, case_sensitive=True)
            if not matches:
                # Also check case-insensitive if exact didn't match, unless approved text would be falsely matched
                raw_matches = self.find_occurrences(content, prohibited_clean, case_sensitive=False)
                # Filter out occurrences that actually form part of official BrandShield AI or approved text
                matches = []
                for m in raw_matches:
                    start, end, flagged_text = m
                    flagged_clean = flagged_text.strip()
                    following = content[end:end + 10]
                    # If match is 'BrandShield' followed by ' AI', it is the approved trademark
                    if flagged_clean == "BrandShield" and re.search(r"^\s+AI\b", following):
                        continue
                    if flagged_clean == "BrandShield AI":
                        continue
                    if any(flagged_clean == appr.strip() for appr in approved_list if appr):
                        continue
                    matches.append(m)

            for start, end, flagged in matches:
                # Determine best replacement from approved list or directive
                approved_replacement = approved_list[0] if approved_list else "BrandShield AI"
                # If approved example is a full sentence, try to extract product name
                if " " in approved_replacement and "BrandShield AI" in approved_replacement:
                    replacement_term = "BrandShield AI"
                else:
                    replacement_term = approved_replacement

                violations.append({
                    "rule_id": str(guideline["id"]),
                    "rule_name": guideline.get("name", "Trademark Usage Policy"),
                    "rule_type": "trademark_usage",
                    "severity": guideline.get("severity", "critical"),
                    "flagged_text": flagged,
                    "char_start": start,
                    "char_end": end,
                    "explanation": (
                        f"Improper brand name casing or unauthorized trademark variant '{flagged}'. "
                        f"Must be written strictly as '{replacement_term}'."
                    ),
                    "source_clause": source_clause,
                    "confidence_score": 1.0,
                    "suggested_text": replacement_term,
                    "rationale": f"Corrected '{flagged}' to official trademark '{replacement_term}' in compliance with brand capitalization policy.",
                })

        # 2. General BrandShield AI casing check if guideline mentions BrandShield
        if "brandshield" in guideline.get("name", "").lower() or "brandshield" in source_clause.lower():
            # Look for lowercase or incorrectly cased 'brandshield' variants
            pattern = re.compile(r"\b(brandshield(?:\s+ai)?|Brand\s+Shield(?:\s+AI)?|BrandshieldAI|BrandShield(?!\s+AI\b))\b", re.IGNORECASE)
            for m in pattern.finditer(content):
                flagged = m.group(0)
                if flagged != "BrandShield AI":
                    start, end = m.start(), m.end()
                    # Check if already added
                    if not any(v["char_start"] == start and v["char_end"] == end for v in violations):
                        violations.append({
                            "rule_id": str(guideline["id"]),
                            "rule_name": guideline.get("name", "Brand Capitalization Standard"),
                            "rule_type": "trademark_usage",
                            "severity": guideline.get("severity", "critical"),
                            "flagged_text": flagged,
                            "char_start": start,
                            "char_end": end,
                            "explanation": f"Brand trademark capitalization error: '{flagged}' violates the mandatory 'BrandShield AI' naming standard.",
                            "source_clause": source_clause,
                            "confidence_score": 1.0,
                            "suggested_text": "BrandShield AI",
                            "rationale": f"Replaced incorrect casing '{flagged}' with official trademark 'BrandShield AI'.",
                        })

        return violations
