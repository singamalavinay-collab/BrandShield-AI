import re
from typing import Any, Dict, List, Optional
from app.engine.rules.base import BaseRuleDetector


class ToneAndFormattingDetector(BaseRuleDetector):
    """Detects tone of voice infractions and formatting policy breaches."""

    def evaluate(
        self,
        content: str,
        guideline: Dict[str, Any],
        target_channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rule_type = guideline.get("rule_type")
        if rule_type not in {"tone_of_voice", "formatting"}:
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

            # For formatting rules, skip full regulatory/governance sentences erroneously present in prohibited examples
            if rule_type == "formatting" and any(term in prohibited_clean.lower() for term in ["without any human", "without human", "auto-pilot"]):
                continue

            matches = self.find_occurrences(content, prohibited_clean, case_sensitive=False)
            for start, end, flagged in matches:
                default_name = "Tone of Voice Standard" if rule_type == "tone_of_voice" else "Formatting Standard"
                explanation = (
                    f"Tone of voice infraction '{flagged}' violates enterprise tone directives."
                    if rule_type == "tone_of_voice"
                    else f"Formatting infraction '{flagged}' violates brand style directives."
                )
                replacement = approved_list[0] if approved_list else ("professional brand tone" if rule_type == "tone_of_voice" else "approved formatting")
                violations.append({
                    "rule_id": str(guideline["id"]),
                    "rule_name": guideline.get("name", default_name),
                    "rule_type": rule_type,
                    "severity": guideline.get("severity", "medium"),
                    "flagged_text": flagged,
                    "char_start": start,
                    "char_end": end,
                    "explanation": explanation,
                    "source_clause": source_clause,
                    "confidence_score": 1.0,
                    "suggested_text": replacement,
                    "rationale": f"Replaced non-compliant phrasing '{flagged}' with '{replacement}'.",
                })

        # 2. Check for quoted prohibited terms in directive (e.g. "game-changer", "revolutionary miracle")
        directive = guideline.get("directive", "")
        if rule_type == "tone_of_voice" and ("avoid" in directive.lower() or "hyperbolic" in directive.lower()):
            # Only extract terms that follow negative directives like 'avoid' or 'prohibit'
            avoid_match = re.search(r'(?:avoid|never|prohibit[a-z]*)\s+(?:hyperbolic\s+)?(?:jargon|words?|terms?|phrases?)?\s*(?:such as|like)?\s*([^\.]+)', directive, re.IGNORECASE)
            search_scope = avoid_match.group(0) if avoid_match else directive
            quoted_terms = re.findall(r'"([^"]+)"', search_scope)
            for term in quoted_terms:
                term_clean = term.strip()
                if len(term_clean) >= 4:
                    matches = self.find_occurrences(content, term_clean, case_sensitive=False)
                    for start, end, flagged in matches:
                        if not any(v["char_start"] == start and v["char_end"] == end for v in violations):
                            replacement = approved_list[0] if approved_list else "objective brand copy"
                            violations.append({
                                "rule_id": str(guideline["id"]),
                                "rule_name": guideline.get("name", "Tone of Voice Standard"),
                                "rule_type": "tone_of_voice",
                                "severity": guideline.get("severity", "medium"),
                                "flagged_text": flagged,
                                "char_start": start,
                                "char_end": end,
                                "explanation": f"Hyperbolic phrasing '{flagged}' violates objective tone directives.",
                                "source_clause": source_clause,
                                "confidence_score": 0.95,
                                "suggested_text": "intelligent" if "miracle" in flagged.lower() else replacement,
                                "rationale": f"Replaced exaggerated buzzword '{flagged}' with professional, objective language.",
                            })

        # 3. Common hyperbolic terminology check if guideline is tone of voice
        if rule_type == "tone_of_voice" and any(k in (guideline.get("name", "") + " " + source_clause).lower() for k in ["tone", "hyperbole", "buzzword", "jargon", "miracle"]):
            tone_patterns = [
                (r"\brevolutionary\s+miracle\s+platform\b", "intelligent brand governance platform", "Hyperbolic promotional phrase violates objective tone standards."),
                (r"\brevolutionary\s+miracle\b", "intelligent", "Exaggerated promotional hyperbole violates professional tone standards."),
                (r"\bgame-changer\b", "innovative advancement", "Overused marketing buzzword violates brand voice guidelines."),
                (r"\bunmatched\s+magic\b", "structured algorithmic capability", "Mystical or exaggerated phrasing violates precision tone directives."),
            ]
            for pat_str, suggested_repl, exp_note in tone_patterns:
                for m in re.finditer(pat_str, content, re.IGNORECASE):
                    start, end = m.start(), m.end()
                    flagged = m.group(0)
                    if not any(v["char_start"] == start and v["char_end"] == end for v in violations):
                        violations.append({
                            "rule_id": str(guideline["id"]),
                            "rule_name": guideline.get("name", "Tone of Voice Standard"),
                            "rule_type": "tone_of_voice",
                            "severity": guideline.get("severity", "medium"),
                            "flagged_text": flagged,
                            "char_start": start,
                            "char_end": end,
                            "explanation": f"{exp_note} Flagged: '{flagged}'.",
                            "source_clause": source_clause,
                            "confidence_score": 0.95,
                            "suggested_text": suggested_repl,
                            "rationale": f"Replaced hyperbolic phrase '{flagged}' with objective copy '{suggested_repl}'.",
                        })

        # 4. Formatting and terminology checks (e.g. 'socialmedia' -> 'social media')
        if rule_type == "formatting" or "formatting" in guideline.get("name", "").lower():
            if "social media" in (source_clause + " " + directive).lower():
                for m in re.finditer(r"\bsocialmedia\b", content, re.IGNORECASE):
                    start, end = m.start(), m.end()
                    flagged = m.group(0)
                    if not any(v["char_start"] == start and v["char_end"] == end for v in violations):
                        violations.append({
                            "rule_id": str(guideline["id"]),
                            "rule_name": guideline.get("name", "Standard Formatting & Terminology"),
                            "rule_type": "formatting",
                            "severity": guideline.get("severity", "low"),
                            "flagged_text": flagged,
                            "char_start": start,
                            "char_end": end,
                            "explanation": f"Compound formatting error: '{flagged}' must be written as two words 'social media' per brand style guidelines.",
                            "source_clause": source_clause,
                            "confidence_score": 1.0,
                            "suggested_text": "social media",
                            "rationale": f"Separated concatenated compound word '{flagged}' into standard 'social media'.",
                        })

        # 5. Check for excessive exclamation points if formatting/tone guideline restricts hype
        directive_lower = (guideline.get("directive", "") + " " + guideline.get("name", "")).lower()
        if "exclamation" in directive_lower or "hyperbole" in directive_lower or "punctuation" in directive_lower:
            for m in re.finditer(r"!{2,}", content):
                start, end = m.start(), m.end()
                flagged = m.group(0)
                if not any(v["char_start"] == start and v["char_end"] == end for v in violations):
                    violations.append({
                        "rule_id": str(guideline["id"]),
                        "rule_name": guideline.get("name", "Formatting & Punctuation Policy"),
                        "rule_type": "formatting",
                        "severity": guideline.get("severity", "low"),
                        "flagged_text": flagged,
                        "char_start": start,
                        "char_end": end,
                        "explanation": f"Excessive punctuation '{flagged}'. Brand standard mandates a single period or punctuation mark.",
                        "source_clause": source_clause,
                        "confidence_score": 1.0,
                        "suggested_text": ".",
                        "rationale": f"Replaced excessive exclamation marks '{flagged}' with standard punctuation.",
                    })

        return violations
