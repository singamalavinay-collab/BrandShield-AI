"""BrandShield AI — Deterministic Risk Assessment and Finding Deduplication Engine.

Phase 1, Milestone 2:
Implements deterministic risk scoring, multi-modal finding deduplication,
channel/audience multipliers, clamping, risk banding, and escalation triggers.

Mathematical Model:
    Base Score = Sum(Severity Weight(v) * Finding Confidence(v)) for v in Deduped Findings
    Raw Risk Score = Base Score * Channel Multiplier * Audience Multiplier
    Clamped Risk Score = min(100.0, max(0.0, Raw Risk Score))
    Display Score = round(Clamped Risk Score, 1)

Severity Weights:
    CRITICAL: 40.0
    HIGH:     25.0
    MEDIUM:   12.0
    LOW:       4.0

Risk Bands:
    LOW:      0.0  to 29.9
    MEDIUM:  30.0  to 59.9
    HIGH:    60.0  to 79.9
    CRITICAL:80.0  to 100.0

Escalation Criteria:
    - Clamped Risk Score >= 60.0, OR
    - At least one CRITICAL severity finding exists.
"""

from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_HALF_UP
import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("brandshield.engine.risk_scorer")


def round_half_up(val: float, decimals: int = 1) -> float:
    """Standard commercial half-up rounding (eliminating Python banker's rounding discrepancies)."""
    try:
        d = Decimal(str(val))
        return float(d.quantize(Decimal(f"1e-{decimals}"), rounding=ROUND_HALF_UP))
    except Exception:
        return round(val, decimals)

# ==============================================================================
# Severity Weights & Ranks
# ==============================================================================

SEVERITY_WEIGHTS: Dict[str, float] = {
    "CRITICAL": 40.0,
    "HIGH": 25.0,
    "MEDIUM": 12.0,
    "LOW": 4.0,
}

SEVERITY_RANKS: Dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
}

# ==============================================================================
# Channel Multipliers
# ==============================================================================

CHANNEL_MULTIPLIERS: Dict[str, float] = {
    # Broadcast / Billboard: 1.30
    "broadcast": 1.30,
    "billboard": 1.30,
    "broadcast/billboard": 1.30,
    "billboard/national": 1.30,
    "national_broadcast": 1.30,
    "press_release": 1.30,
    "ad_copy": 1.30,
    "advertisement": 1.30,

    # Social: 1.15
    "social": 1.15,
    "twitter_x": 1.15,
    "twitter": 1.15,
    "instagram": 1.15,
    "facebook": 1.15,
    "tiktok": 1.15,
    "youtube": 1.15,

    # Web: 1.00
    "web": 1.00,
    "website": 1.00,
    "blog_post": 1.00,
    "blog": 1.00,
    "landing_page": 1.00,
    "linkedin": 1.00,  # Professional B2B network / web platform

    # Internal: 0.75
    "internal": 0.75,
    "email": 0.75,
    "email_newsletter": 0.75,
    "newsletter": 0.75,
    "memo": 0.75,
    "slack": 0.75,
}

# ==============================================================================
# Audience Multipliers
# ==============================================================================

AUDIENCE_MULTIPLIERS: Dict[str, float] = {
    # Regulated: 1.25
    "regulated": 1.25,
    "healthcare": 1.25,
    "pharma": 1.25,
    "pharmaceutical": 1.25,
    "financial": 1.25,
    "legal": 1.25,

    # General: 1.00
    "general": 1.00,
    "public": 1.00,
    "consumer": 1.00,
    "mass_market": 1.00,

    # B2B: 0.85
    "b2b": 0.85,
    "enterprise": 0.85,
    "professional": 0.85,
}


def get_channel_multiplier(channel: Optional[str], audience: Optional[str] = None) -> float:
    """Resolve channel risk multiplier with safe normalization and 1.00 fallback.
    
    Channel and audience multipliers are strictly independent orthogonal dimensions.
    """
    if not channel:
        return 1.00
    norm_ch = str(channel).strip().lower()
    return CHANNEL_MULTIPLIERS.get(norm_ch, 1.00)


def get_audience_multiplier(audience: Optional[str]) -> float:
    """Resolve audience risk multiplier with safe normalization and 1.00 fallback."""
    if not audience:
        return 1.00
    norm = str(audience).strip().lower()
    return AUDIENCE_MULTIPLIERS.get(norm, 1.00)


def get_severity_weight(severity: Any) -> float:
    """Resolve numeric weight for violation severity category."""
    if not severity:
        return 0.0
    key = str(severity).strip().upper()
    return SEVERITY_WEIGHTS.get(key, 0.0)


def get_risk_level(score: float) -> str:
    """Map clamped risk score to categorical risk band.
    
    Bands:
        LOW:      0.0  to 29.9 (< 30.0)
        MEDIUM:  30.0  to 59.9 (>= 30.0 and < 60.0)
        HIGH:    60.0  to 79.9 (>= 60.0 and < 80.0)
        CRITICAL:80.0  to 100.0 (>= 80.0)
    """
    if score < 30.0:
        return "LOW"
    elif score < 60.0:
        return "MEDIUM"
    elif score < 80.0:
        return "HIGH"
    else:
        return "CRITICAL"


# ==============================================================================
# Visual Intersection-over-Union (IoU) Helper
# ==============================================================================

def calculate_iou(box1: Any, box2: Any) -> float:
    """Calculate Intersection-over-Union (IoU) between two bounding boxes.
    
    Supports:
    - [x1, y1, x2, y2] list/tuple
    - {"x1": ..., "y1": ..., "x2": ..., "y2": ...} dict
    - {"xmin": ..., "ymin": ..., "xmax": ..., "ymax": ...} dict
    - {"box_2d": [ymin, xmin, ymax, xmax]} (Gemini normalized coordinate format)
    
    Returns float in range [0.0, 1.0].
    """
    if not box1 or not box2:
        return 0.0

    def parse_box(b: Any) -> Optional[Tuple[float, float, float, float]]:
        if isinstance(b, dict):
            if "box_2d" in b and isinstance(b["box_2d"], (list, tuple)) and len(b["box_2d"]) == 4:
                # [ymin, xmin, ymax, xmax]
                ymin, xmin, ymax, xmax = b["box_2d"]
                return float(xmin), float(ymin), float(xmax), float(ymax)
            if "x1" in b and "y1" in b and "x2" in b and "y2" in b:
                return float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"])
            if "xmin" in b and "ymin" in b and "xmax" in b and "ymax" in b:
                return float(b["xmin"]), float(b["ymin"]), float(b["xmax"]), float(b["ymax"])
        elif isinstance(b, (list, tuple)) and len(b) == 4:
            return float(b[0]), float(b[1]), float(b[2]), float(b[3])
        return None

    coords1 = parse_box(box1)
    coords2 = parse_box(box2)
    if not coords1 or not coords2:
        return 0.0

    x1_a, y1_a, x2_a, y2_a = coords1
    x1_b, y1_b, x2_b, y2_b = coords2

    # Normalize coordinate ordering if necessary
    min_x_a, max_x_a = min(x1_a, x2_a), max(x1_a, x2_a)
    min_y_a, max_y_a = min(y1_a, y2_a), max(y1_a, y2_a)
    min_x_b, max_x_b = min(x1_b, x2_b), max(x1_b, x2_b)
    min_y_b, max_y_b = min(y1_b, y2_b), max(y1_b, y2_b)

    inter_x1 = max(min_x_a, min_x_b)
    inter_y1 = max(min_y_a, min_y_b)
    inter_x2 = min(max_x_a, max_x_b)
    inter_y2 = min(max_y_a, max_y_b)

    inter_width = max(0.0, inter_x2 - inter_x1)
    inter_height = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_width * inter_height

    area_a = (max_x_a - min_x_a) * (max_y_a - min_y_a)
    area_b = (max_x_b - min_x_b) * (max_y_b - min_y_b)

    union_area = area_a + area_b - inter_area
    if union_area <= 0.0:
        return 0.0

    return inter_area / union_area


# ==============================================================================
# Finding Deduplication Engine
# ==============================================================================

def are_findings_duplicate(f1: Dict[str, Any], f2: Dict[str, Any]) -> bool:
    """Determine if two findings represent duplicate detections of the same infraction.
    
    STRICT RULES:
    1. NEVER merge different violation types just because their spans overlap.
    2. Text Modality: Same rule_type and overlapping character spans.
    3. Document Modality: Same page and overlapping text/paragraph spans.
    4. Image Modality: Same brand entity with bounding box IoU > 0.70.
    """
    # Invariant: Never merge different rule types
    t1 = str(f1.get("rule_type", "")).strip().lower()
    t2 = str(f2.get("rule_type", "")).strip().lower()
    if t1 != t2:
        return False

    # Check Visual / Image Modality
    box1 = f1.get("bounding_box") or f1.get("box") or f1.get("bbox")
    box2 = f2.get("bounding_box") or f2.get("box") or f2.get("bbox")
    if box1 is not None and box2 is not None:
        e1 = str(f1.get("brand_entity") or f1.get("entity") or t1).strip().lower()
        e2 = str(f2.get("brand_entity") or f2.get("entity") or t2).strip().lower()
        if e1 == e2:
            iou = calculate_iou(box1, box2)
            if iou > 0.70:
                return True

    # Check Document Modality (page + span)
    p1 = f1.get("page") or f1.get("page_number") or (f1.get("metadata") or {}).get("page")
    p2 = f2.get("page") or f2.get("page_number") or (f2.get("metadata") or {}).get("page")
    if p1 is not None and p2 is not None:
        if p1 == p2:
            s1, e1 = f1.get("char_start"), f1.get("char_end")
            s2, e2 = f2.get("char_start"), f2.get("char_end")
            if s1 is not None and e1 is not None and s2 is not None and e2 is not None:
                if max(s1, s2) < min(e1, e2):
                    return True
            else:
                # Same page and identical flagged text
                txt1 = str(f1.get("flagged_text", "")).strip().lower()
                txt2 = str(f2.get("flagged_text", "")).strip().lower()
                if txt1 and txt1 == txt2:
                    return True
        else:
            # Different pages are never duplicates
            return False

    # Check Text Modality (span overlap)
    s1, e1 = f1.get("char_start"), f1.get("char_end")
    s2, e2 = f2.get("char_start"), f2.get("char_end")
    if s1 is not None and e1 is not None and s2 is not None and e2 is not None:
        # Non-empty interval intersection: max(s1, s2) < min(e1, e2)
        if max(s1, s2) < min(e1, e2):
            return True
    elif s1 is None and s2 is None:
        # Fallback when character spans are unindexed: compare normalized flagged text
        txt1 = str(f1.get("flagged_text", "")).strip().lower()
        txt2 = str(f2.get("flagged_text", "")).strip().lower()
        if txt1 and txt1 == txt2:
            return True

    return False


def deduplicate_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate findings before scoring.
    
    Retention Invariant:
    When duplicate findings are detected, retain the finding with:
    1. Higher severity (CRITICAL > HIGH > MEDIUM > LOW).
    2. Higher confidence score (if severities match).
    3. First occurrence index (if confidence matches).
    """
    if not findings or len(findings) <= 1:
        return list(findings)

    n = len(findings)
    # Priority key for selecting the best finding in a duplicate cluster
    def priority_key(idx: int) -> Tuple[int, float, int]:
        f = findings[idx]
        sev = str(f.get("severity", "LOW")).strip().upper()
        rank = SEVERITY_RANKS.get(sev, 1)
        conf = float(f.get("confidence_score") if f.get("confidence_score") is not None else (f.get("confidence") or 1.0))
        return (rank, conf, -idx)

    # Disjoint Set Union (DSU) to group duplicate findings
    parent = list(range(n))

    def find(i: int) -> int:
        if parent[i] == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    # Pairwise check
    for i in range(n):
        for j in range(i + 1, n):
            if are_findings_duplicate(findings[i], findings[j]):
                union(i, j)

    # Group by cluster root
    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(i)

    # In each cluster, pick the highest-priority finding
    selected_indices: Set[int] = set()
    for root, member_indices in clusters.items():
        best_idx = max(member_indices, key=priority_key)
        selected_indices.add(best_idx)

    # Preserve original order of presentation
    deduped = [findings[i] for i in range(n) if i in selected_indices]
    return deduped


# ==============================================================================
# Risk Assessment Calculation & Serialization
# ==============================================================================

@dataclass
class RiskAssessmentResult:
    """Complete structured output of the deterministic risk scoring engine."""

    risk_score: float
    display_score: float
    risk_level: str
    is_escalated: bool
    escalation_reasons: List[str]
    channel_multiplier: float
    audience_multiplier: float
    base_score: float
    raw_score: float
    deduplicated_findings: List[Dict[str, Any]] = field(default_factory=list)
    risk_breakdown: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calculate_risk_score(
    findings: List[Dict[str, Any]],
    target_channel: Optional[str] = None,
    target_audience: Optional[str] = None,
    deduplicate: bool = True,
) -> RiskAssessmentResult:
    """Calculates deterministic risk score, risk level, and escalation decision.
    
    Formula:
        Risk Score = Sum(Severity Weight * Confidence) * Channel Multiplier * Audience Multiplier
        Clamped to [0.0, 100.0]
    
    Escalation triggers:
        - Risk score >= 60.0
        - Presence of at least one CRITICAL severity finding
    """
    raw_findings = findings or []
    deduped_findings = deduplicate_findings(raw_findings) if deduplicate else list(raw_findings)

    # 1. Resolve Multipliers
    channel_mult = get_channel_multiplier(target_channel, target_audience)
    audience_mult = get_audience_multiplier(target_audience)

    # 2. Compute Base Score across deduplicated findings
    base_score = 0.0
    findings_breakdown: List[Dict[str, Any]] = []
    has_critical_violation = False

    for f in deduped_findings:
        sev = str(f.get("severity", "LOW")).strip().upper()
        if sev == "CRITICAL":
            has_critical_violation = True
        weight = SEVERITY_WEIGHTS.get(sev, 0.0)
        conf = float(f.get("confidence_score") if f.get("confidence_score") is not None else (f.get("confidence") or 1.0))
        # Ensure confidence is clamped between 0.0 and 1.0
        conf = max(0.0, min(1.0, conf))
        weighted_val = weight * conf
        base_score += weighted_val

        findings_breakdown.append({
            "rule_name": f.get("rule_name") or f.get("rule_type", "Unknown Rule"),
            "rule_type": f.get("rule_type"),
            "severity": sev,
            "severity_weight": weight,
            "confidence": conf,
            "weighted_score": round(weighted_val, 4),
            "flagged_text": f.get("flagged_text"),
            "char_start": f.get("char_start"),
            "char_end": f.get("char_end"),
        })

    # 3. Apply Multipliers and Clamping
    raw_score = base_score * channel_mult * audience_mult
    clamped_score = min(100.0, max(0.0, raw_score))
    display_score = round_half_up(clamped_score, 1)

    # 4. Resolve Categorical Risk Band
    risk_level = get_risk_level(clamped_score)

    # 5. Evaluate Escalation Criteria
    escalation_reasons: List[str] = []
    if clamped_score >= 60.0:
        escalation_reasons.append(f"Risk score {display_score} is in high-risk band (>= 60.0).")
    if has_critical_violation:
        escalation_reasons.append("Contains at least one CRITICAL severity brand rule violation.")

    is_escalated = len(escalation_reasons) > 0

    # 6. Synthesize Transparent Risk Breakdown
    risk_breakdown: Dict[str, Any] = {
        "base_score": round(base_score, 4),
        "channel": target_channel or "default",
        "channel_multiplier": channel_mult,
        "audience": target_audience or "default",
        "audience_multiplier": audience_mult,
        "raw_score": round(raw_score, 4),
        "clamped_score": round(clamped_score, 4),
        "display_score": display_score,
        "risk_level": risk_level,
        "is_escalated": is_escalated,
        "escalation_reasons": escalation_reasons,
        "raw_findings_count": len(raw_findings),
        "deduped_findings_count": len(deduped_findings),
        "deduplicated_count": len(raw_findings) - len(deduped_findings),
        "findings_breakdown": findings_breakdown,
    }

    return RiskAssessmentResult(
        risk_score=round(clamped_score, 4),
        display_score=display_score,
        risk_level=risk_level,
        is_escalated=is_escalated,
        escalation_reasons=escalation_reasons,
        channel_multiplier=channel_mult,
        audience_multiplier=audience_mult,
        base_score=round(base_score, 4),
        raw_score=round(raw_score, 4),
        deduplicated_findings=deduped_findings,
        risk_breakdown=risk_breakdown,
    )
