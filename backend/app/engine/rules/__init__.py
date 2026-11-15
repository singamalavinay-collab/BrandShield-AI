from typing import List
from app.engine.rules.base import BaseRuleDetector
from app.engine.rules.claims import ProhibitedClaimsDetector
from app.engine.rules.regulatory import RegulatoryRuleDetector
from app.engine.rules.terminology import TerminologyRuleDetector
from app.engine.rules.tone import ToneAndFormattingDetector
from app.engine.rules.trademark import TrademarkRuleDetector

ALL_RULE_DETECTORS: List[BaseRuleDetector] = [
    TrademarkRuleDetector(),
    ProhibitedClaimsDetector(),
    RegulatoryRuleDetector(),
    TerminologyRuleDetector(),
    ToneAndFormattingDetector(),
]

__all__ = [
    "BaseRuleDetector",
    "TrademarkRuleDetector",
    "ProhibitedClaimsDetector",
    "RegulatoryRuleDetector",
    "TerminologyRuleDetector",
    "ToneAndFormattingDetector",
    "ALL_RULE_DETECTORS",
]
