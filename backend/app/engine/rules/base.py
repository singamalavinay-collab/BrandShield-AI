from abc import ABC, abstractmethod
import re
from typing import Any, Dict, List, Optional, Tuple


class BaseRuleDetector(ABC):
    """Abstract base class for brand rule compliance detectors."""

    @abstractmethod
    def evaluate(
        self,
        content: str,
        guideline: Dict[str, Any],
        target_channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Evaluate submitted copy against a specific brand guideline.
        
        Returns a list of candidate violations containing exact offsets,
        flagged excerpts, explanations, verbatim evidence clauses, and suggestions.
        """
        pass

    @staticmethod
    def find_occurrences(
        content: str,
        pattern_or_phrase: str,
        case_sensitive: bool = False,
        require_word_boundary: bool = True,
    ) -> List[Tuple[int, int, str]]:
        """Locate all occurrences of a phrase or regex with exact start and end offsets."""
        flags = 0 if case_sensitive else re.IGNORECASE
        escaped = re.escape(pattern_or_phrase)
        if require_word_boundary:
            regex_str = rf"\b{escaped}\b"
        else:
            regex_str = escaped

        matches: List[Tuple[int, int, str]] = []
        for m in re.finditer(regex_str, content, flags):
            matches.append((m.start(), m.end(), m.group(0)))
        return matches

    @staticmethod
    def extract_source_clause(guideline: Dict[str, Any]) -> str:
        """Extract the authoritative verbatim source clause from the brand guideline."""
        directive = guideline.get("directive", "").strip()
        if directive:
            return directive
        desc = guideline.get("description", "").strip()
        if desc:
            return desc
        return guideline.get("name", "Official Brand Standard")
