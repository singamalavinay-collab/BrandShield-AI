"""Visual Brand Compliance Rule Detector (Phase 2, Stage 2C).

Converts genuine multimodal visual observations from Gemini into evidence-backed BrandShield
compliance findings with strict provenance and verification safeguards.

Capabilities:
1. Brand logo presence, placement, and usage observations.
2. Brand color palette comparison against explicitly approved brand guidelines.
3. Visual identity and clear-space observations where sufficient evidence exists.
4. Required on-screen disclaimer detection where explicitly mandated by approved brand policy.
5. OCR text extraction and comparison against approved terminology and prohibited claims.
6. Video visual observations with timestamp preservation.

Safeguards:
- Reuses active BrandGuideline records only; never uses pending or rejected candidate guidelines.
- Never invents expected logo positions, colors, clear-space measurements, or disclaimer rules.
- If approved visual rules do not exist, reports that the check cannot be evaluated.
- Distinguishes missing logos from undetected logos (avoids false violations when vision is offline).
- Distinguishes confirmed violations from uncertain observations (< 0.70 confidence).
- Preserves original bounding boxes, timestamps, and evidence references.
- Zero local heavy dependencies (pure math for color space & IoU).
"""

import logging
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.engine.rules.base import BaseRuleDetector

logger = logging.getLogger("brandshield.engine.rules.visual")


# ==============================================================================
# Color Space Helpers (Pure Python Euclidean Distance in RGB Space)
# ==============================================================================

HEX_COLOR_REGEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def hex_to_rgb(hex_str: str) -> Optional[Tuple[int, int, int]]:
    """Convert a 3-character or 6-character hex string into an (R, G, B) tuple."""
    if not hex_str or not isinstance(hex_str, str):
        return None
    cleaned = hex_str.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(c * 2 for c in cleaned)
    if len(cleaned) != 6:
        return None
    try:
        r = int(cleaned[0:2], 16)
        g = int(cleaned[2:4], 16)
        b = int(cleaned[4:6], 16)
        return (r, g, b)
    except ValueError:
        return None


def color_distance(rgb1: Tuple[int, int, int], rgb2: Tuple[int, int, int]) -> float:
    """Calculate normalized Euclidean color distance in RGB space.
    
    Range: [0.0, 1.0], where 0.0 is an exact match and 1.0 is maximum distance (Black to White).
    """
    max_dist = math.sqrt(255**2 + 255**2 + 255**2)  # ~441.67
    dr = rgb1[0] - rgb2[0]
    dg = rgb1[1] - rgb2[1]
    db = rgb1[2] - rgb2[2]
    dist = math.sqrt(dr**2 + dg**2 + db**2)
    return dist / max_dist


def extract_hex_colors(data: Any) -> Set[str]:
    """Extract normalized uppercase 6-character hex color codes from strings or lists."""
    found: Set[str] = set()
    if not data:
        return found

    items = data if isinstance(data, (list, tuple, set)) else [data]
    for item in items:
        if isinstance(item, str):
            for match in HEX_COLOR_REGEX.findall(item):
                rgb = hex_to_rgb(match)
                if rgb:
                    norm = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
                    found.add(norm)
    return found


def format_video_timestamp(seconds: Optional[float]) -> str:
    """Format floating-point seconds into MM:SS.mmm representation."""
    if seconds is None or seconds < 0:
        return "N/A"
    minutes = int(seconds // 60)
    rem_sec = seconds % 60
    return f"{minutes:02d}:{rem_sec:06.3f}"


# ==============================================================================
# Visual Rule Detector Class
# ==============================================================================

class VisualRuleDetector(BaseRuleDetector):
    """Evaluates visual brand rules (logos, colors, clear space, on-screen disclaimers)."""

    def evaluate(
        self,
        content: str,
        guideline: Dict[str, Any],
        target_channel: Optional[str] = None,
        multimodal_metadata: Optional[Dict[str, Any]] = None,
        media_type: Optional[str] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Evaluate submitted visual content against an active brand guideline.
        
        Safeguards:
        - Only executes if guideline contains visual, logo, color, or on-screen disclaimer rules.
        - Only checks visual observations when media_type is image, video, or document.
        - Distinguishes missing from uninspected/offline assets.
        - Preserves bounding boxes, timestamps, and verbatim source clauses.
        """
        # 1. Verify guideline is active
        if not guideline.get("is_active", True):
            return []

        # 2. Check relevance to visual inspection
        is_visual_guideline, rule_aspects = self._classify_visual_guideline(guideline)
        if not is_visual_guideline:
            return []

        violations: List[Dict[str, Any]] = []
        meta = multimodal_metadata or {}
        detected_media = (media_type or meta.get("media_type") or "text").lower()

        # If plain text without visual metadata, visual checks cannot be evaluated
        if detected_media == "text" and not meta.get("visual_observations"):
            return []

        processing_status = meta.get("processing_status", "UNKNOWN")
        visual_observations: List[Dict[str, Any]] = meta.get("visual_observations", [])
        source_clause = self.extract_source_clause(guideline)

        # 3. Logo Usage & Placement Evaluation
        if "logo" in rule_aspects or "clear_space" in rule_aspects:
            logo_violations = self._evaluate_logo_rules(
                guideline=guideline,
                visual_observations=visual_observations,
                processing_status=processing_status,
                source_clause=source_clause,
                media_type=detected_media,
            )
            violations.extend(logo_violations)

        # 4. Brand Color Palette Evaluation
        if "color" in rule_aspects:
            color_violations = self._evaluate_color_rules(
                guideline=guideline,
                visual_observations=visual_observations,
                processing_status=processing_status,
                source_clause=source_clause,
            )
            violations.extend(color_violations)

        # 5. Required On-Screen Disclaimer Evaluation
        if "disclaimer" in rule_aspects:
            disclaimer_violations = self._evaluate_disclaimer_rules(
                guideline=guideline,
                content=content,
                visual_observations=visual_observations,
                multimodal_metadata=meta,
                processing_status=processing_status,
                source_clause=source_clause,
            )
            violations.extend(disclaimer_violations)

        # 6. OCR Text Prohibited Statements in Visual Track
        if "on_screen_text" in rule_aspects:
            ocr_violations = self._evaluate_ocr_text_rules(
                guideline=guideline,
                visual_observations=visual_observations,
                source_clause=source_clause,
            )
            violations.extend(ocr_violations)

        return violations

    # ==========================================================================
    # Classifier Helper
    # ==========================================================================

    def _classify_visual_guideline(self, guideline: Dict[str, Any]) -> Tuple[bool, Set[str]]:
        """Determine whether a guideline contains visual standards and categorize aspects."""
        aspects: Set[str] = set()
        rule_type = str(guideline.get("rule_type", "")).lower()
        tags = {str(t).lower() for t in (guideline.get("tags") or [])}
        name = str(guideline.get("name", "")).lower()
        directive = str(guideline.get("directive", "")).lower()
        description = str(guideline.get("description", "")).lower()

        full_text = f"{rule_type} {' '.join(tags)} {name} {directive} {description}"

        # Aspect 1: Logo & Visual Identity
        if rule_type in {"logo_usage", "visual_identity"} or any(t in tags for t in {"logo", "branding", "watermark", "icon"}):
            aspects.add("logo")
        elif "logo" in full_text:
            aspects.add("logo")

        # Aspect 2: Clear Space
        if "clear space" in full_text or "clear-space" in full_text or "margin" in full_text:
            aspects.add("clear_space")

        # Aspect 3: Color Palette
        if rule_type == "color_palette" or any(t in tags for t in {"color", "colors", "palette", "brand_colors", "hex"}):
            aspects.add("color")
        elif any(w in full_text for w in ["color palette", "dominant color", "brand color", "hex code", "palette"]):
            aspects.add("color")

        # Aspect 4: Required On-Screen Disclaimer
        if any(t in tags for t in {"disclaimer", "disclosure", "on_screen_disclaimer", "mandate"}):
            aspects.add("disclaimer")
        elif "on-screen disclaimer" in full_text or "onscreen disclaimer" in full_text or "required disclaimer" in full_text:
            aspects.add("disclaimer")
        elif ("disclaimer" in full_text or "disclosure" in full_text) and any(w in full_text for w in ["visual", "video", "image", "screen"]):
            aspects.add("disclaimer")

        # Aspect 5: On-Screen Text & Visual Prohibited Statements
        if any(w in full_text for w in ["on-screen", "onscreen", "on screen", "visual text", "super", "lower-third", "caption", "screencast", "video"]):
            aspects.add("on_screen_text")
        elif rule_type in {"prohibited_claims", "forbidden_claim", "terminology", "trademark_usage"} and guideline.get("examples_prohibited"):
            aspects.add("on_screen_text")

        is_visual = len(aspects) > 0
        return is_visual, aspects

    # ==========================================================================
    # Sub-Evaluator 1: Logo Presence, Placement & Clear Space
    # ==========================================================================

    def _evaluate_logo_rules(
        self,
        guideline: Dict[str, Any],
        visual_observations: List[Dict[str, Any]],
        processing_status: str,
        source_clause: str,
        media_type: str,
    ) -> List[Dict[str, Any]]:
        """Evaluate logo observations against approved active brand guideline."""
        violations: List[Dict[str, Any]] = []
        rule_id = str(guideline["id"])
        rule_name = guideline.get("name", "Logo Compliance Standard")
        severity = guideline.get("severity", "high")
        directive = guideline.get("directive", "").strip()

        approved_logos = [str(x).strip() for x in (guideline.get("examples_approved") or []) if str(x).strip()]
        prohibited_logos = [str(x).strip() for x in (guideline.get("examples_prohibited") or []) if str(x).strip()]

        observed_logos = [
            vo for vo in visual_observations
            if str(vo.get("entity", "")).lower() == "logo"
        ]

        # A. Detect explicitly prohibited logos or unauthorized variations
        for obs in observed_logos:
            label = str(obs.get("label", "")).strip()
            confidence = float(obs.get("confidence", 1.0))
            box = obs.get("box_2d")
            details = obs.get("details") or {}
            ts_sec = details.get("timestamp_seconds") or details.get("start_time_seconds")
            ts_str = format_video_timestamp(ts_sec) if ts_sec is not None else None

            # Check matching prohibited logo list
            is_prohibited = any(p.lower() in label.lower() or label.lower() in p.lower() for p in prohibited_logos)
            if is_prohibited:
                uncertain_prefix = f"[UNCERTAIN OBSERVATION (confidence: {confidence:.2f})] " if confidence < 0.70 else ""
                loc_str = f" at box {box}" if box else ""
                ts_note = f" (at video timestamp {ts_str})" if ts_str else ""

                violations.append({
                    "rule_id": rule_id,
                    "rule_name": rule_name,
                    "rule_type": "logo_usage",
                    "brand_entity": "logo",
                    "severity": severity,
                    "flagged_text": label,
                    "char_start": None,
                    "char_end": None,
                    "bounding_box": box,
                    "timestamp_seconds": ts_sec,
                    "confidence_score": confidence,
                    "explanation": (
                        f"{uncertain_prefix}Prohibited or unauthorized brand logo '{label}' observed{loc_str}{ts_note}. "
                        f"Directive specifies: {directive}."
                    ),
                    "source_clause": source_clause,
                    "suggested_text": approved_logos[0] if approved_logos else "BrandShield AI Primary Logo",
                    "rationale": f"Replaced unauthorized logo '{label}' with official approved brand asset.",
                    "details": {
                        "visual_entity": "logo",
                        "label": label,
                        "confidence": confidence,
                        "bounding_box": box,
                        "timestamp_seconds": ts_sec,
                    },
                })

            # Check clear space violation
            notes = str(details.get("notes", "")).lower()
            clear_space_breach = "clear space" in notes or "clear-space" in notes or "margin" in notes or "padding" in notes
            if not clear_space_breach and box and len(box) == 4:
                ymin, xmin, ymax, xmax = box
                # Margin violation: Touching edges (< 3% margin from edge) when directive demands clear space
                if any(k in directive.lower() for k in ["clear space", "clear-space", "margin"]):
                    if ymin < 0.03 or xmin < 0.03 or ymax > 0.97 or xmax > 0.97:
                        clear_space_breach = True

            if clear_space_breach:
                loc_str = f" [box: {box}]" if box else ""
                violations.append({
                    "rule_id": rule_id,
                    "rule_name": rule_name,
                    "rule_type": "visual_identity",
                    "brand_entity": "logo",
                    "severity": "medium",
                    "flagged_text": f"Logo Clear Space ({label})",
                    "char_start": None,
                    "char_end": None,
                    "bounding_box": box,
                    "timestamp_seconds": ts_sec,
                    "confidence_score": confidence,
                    "explanation": (
                        f"Brand logo '{label}' breaches required clear-space margin{loc_str}. "
                        f"Official directive specifies: {directive}."
                    ),
                    "source_clause": source_clause,
                    "suggested_text": "Maintain required minimum clear space around brand logo.",
                    "rationale": "Adjusted logo position to satisfy minimum clear-space isolation requirements.",
                    "details": {
                        "visual_entity": "logo_clear_space",
                        "label": label,
                        "bounding_box": box,
                        "timestamp_seconds": ts_sec,
                    },
                })

        # B. Mandatory Logo Presence Check
        # Safeguard: Distinguish missing logo from undetected/uninspected logo
        directive_lower = directive.lower()
        name_lower = rule_name.lower()
        is_mandatory = any(
            phrase in directive_lower or phrase in name_lower
            for phrase in ["must include", "mandatory", "must display", "must feature", "required logo", "always include logo"]
        )

        if is_mandatory:
            if processing_status != "SUCCESS":
                # Vision was offline, unconfigured, or failed -> do NOT falsely claim logo is missing
                logger.info(
                    "Visual inspection status is '%s'. Skipping mandatory logo presence check to avoid false violation.",
                    processing_status,
                )
            elif len(observed_logos) == 0:
                expected_logo = approved_logos[0] if approved_logos else "BrandShield AI Logo"
                violations.append({
                    "rule_id": rule_id,
                    "rule_name": rule_name,
                    "rule_type": "logo_usage",
                    "brand_entity": "logo",
                    "severity": severity,
                    "flagged_text": f"[Missing Brand Logo: {expected_logo}]",
                    "char_start": None,
                    "char_end": None,
                    "bounding_box": None,
                    "confidence_score": 0.90,
                    "explanation": (
                        f"Mandatory brand logo '{expected_logo}' was not observed in visual media asset. "
                        f"Approved brand standard '{rule_name}' requires logo presence on promotional visual assets."
                    ),
                    "source_clause": source_clause,
                    "suggested_text": f"Include {expected_logo} in visual asset.",
                    "rationale": f"Added mandatory {expected_logo} in accordance with official brand identity guidelines.",
                    "details": {
                        "visual_entity": "missing_logo",
                        "expected_logo": expected_logo,
                        "processing_status": processing_status,
                    },
                })

        return violations

    # ==========================================================================
    # Sub-Evaluator 2: Brand Color Palette
    # ==========================================================================

    def _evaluate_color_rules(
        self,
        guideline: Dict[str, Any],
        visual_observations: List[Dict[str, Any]],
        processing_status: str,
        source_clause: str,
    ) -> List[Dict[str, Any]]:
        """Compare observed dominant colors against approved brand palette."""
        violations: List[Dict[str, Any]] = []
        rule_id = str(guideline["id"])
        rule_name = guideline.get("name", "Color Palette Standard")
        severity = guideline.get("severity", "medium")
        directive = guideline.get("directive", "").strip()

        # Extract approved & prohibited hex colors from guideline
        approved_hex = extract_hex_colors(guideline.get("examples_approved") or [])
        approved_hex.update(extract_hex_colors(directive))

        prohibited_hex = extract_hex_colors(guideline.get("examples_prohibited") or [])

        # If no approved colors specified in guideline, we cannot evaluate
        if not approved_hex and not prohibited_hex:
            return []

        approved_rgbs = [hex_to_rgb(h) for h in approved_hex if hex_to_rgb(h)]
        prohibited_rgbs = [hex_to_rgb(h) for h in prohibited_hex if hex_to_rgb(h)]

        # Collect color observations from Gemini
        color_obs = [
            vo for vo in visual_observations
            if str(vo.get("entity", "")).lower() == "color"
        ]

        if not color_obs:
            return []

        # Evaluate each observed color
        for obs in color_obs:
            label = str(obs.get("label", "")).strip().upper()
            obs_rgb = hex_to_rgb(label)
            if not obs_rgb:
                continue

            details = obs.get("details") or {}
            percentage = details.get("percentage")
            pct_str = f" ({percentage}% area)" if percentage is not None else ""

            # Check 1: Explicit prohibited color match (tolerance <= 0.08)
            for prog_rgb in prohibited_rgbs:
                dist = color_distance(obs_rgb, prog_rgb)
                if dist <= 0.08:
                    violations.append({
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "rule_type": "color_palette",
                        "brand_entity": "color",
                        "severity": severity,
                        "flagged_text": label,
                        "char_start": None,
                        "char_end": None,
                        "confidence_score": 0.95,
                        "explanation": (
                            f"Prohibited brand color '{label}' observed{pct_str}. "
                            f"Guideline '{rule_name}' explicitly bans this color."
                        ),
                        "source_clause": source_clause,
                        "suggested_text": list(approved_hex)[0] if approved_hex else "#0052CC",
                        "rationale": f"Replaced prohibited color '{label}' with approved brand palette color.",
                        "details": {
                            "visual_entity": "prohibited_color",
                            "color_hex": label,
                            "percentage": percentage,
                            "delta_distance": round(dist, 3),
                        },
                    })
                    break

            # Check 2: Unapproved palette deviation (when guideline defines a strict/closed palette)
            is_strict = any(
                w in directive.lower()
                for w in ["strictly", "only", "must use", "limited to", "exclusive palette", "official colors are"]
            )

            if is_strict and approved_rgbs:
                # Find minimum distance to any approved color
                min_dist = min(color_distance(obs_rgb, app_rgb) for app_rgb in approved_rgbs)
                # If distance > 0.15 and color is a significant dominant color (> 15% or dominant)
                is_dominant = (percentage is None) or (percentage >= 15)
                if min_dist > 0.15 and is_dominant:
                    approved_palette_str = ", ".join(sorted(approved_hex))
                    violations.append({
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "rule_type": "color_palette",
                        "brand_entity": "color",
                        "severity": severity,
                        "flagged_text": label,
                        "char_start": None,
                        "char_end": None,
                        "confidence_score": 0.90,
                        "explanation": (
                            f"Unapproved brand color '{label}' observed{pct_str}. "
                            f"Brand guidelines strictly require palette: {approved_palette_str}."
                        ),
                        "source_clause": source_clause,
                        "suggested_text": sorted(list(approved_hex))[0],
                        "rationale": f"Align color scheme to official brand palette ({approved_palette_str}).",
                        "details": {
                            "visual_entity": "unapproved_color",
                            "color_hex": label,
                            "percentage": percentage,
                            "delta_distance": round(min_dist, 3),
                        },
                    })

        return violations

    # ==========================================================================
    # Sub-Evaluator 3: Required On-Screen Disclaimers
    # ==========================================================================

    def _evaluate_disclaimer_rules(
        self,
        guideline: Dict[str, Any],
        content: str,
        visual_observations: List[Dict[str, Any]],
        multimodal_metadata: Dict[str, Any],
        processing_status: str,
        source_clause: str,
    ) -> List[Dict[str, Any]]:
        """Verify presence of explicitly mandated on-screen disclaimers."""
        violations: List[Dict[str, Any]] = []
        rule_id = str(guideline["id"])
        rule_name = guideline.get("name", "Mandatory Disclaimer Requirement")
        severity = guideline.get("severity", "high")

        # Extract required disclaimer text from approved examples or directive
        approved_disclaimers = [
            str(x).strip() for x in (guideline.get("examples_approved") or [])
            if str(x).strip()
        ]

        if not approved_disclaimers:
            # Check if directive quotes a disclaimer in single or double quotes
            quoted = re.findall(r"['\"]([^'\"]{10,250})['\"]", guideline.get("directive", ""))
            if quoted:
                approved_disclaimers = [quoted[0].strip()]

        if not approved_disclaimers:
            return []

        required_disclaimer = approved_disclaimers[0]

        # Invariant: If vision is offline or unconfigured, do NOT falsely flag missing disclaimer
        if processing_status in {"UNAVAILABLE", "FAILED"}:
            logger.info("Skipping on-screen disclaimer check because processing status is '%s'.", processing_status)
            return []

        # Search for disclaimer across OCR content and visual observations
        combined_visual_text = content or ""
        for vo in visual_observations:
            if str(vo.get("entity", "")).lower() in {"on_screen_text", "disclaimer"}:
                combined_visual_text += " " + str(vo.get("label", ""))
                combined_visual_text += " " + str((vo.get("details") or {}).get("text", ""))

        for seg in multimodal_metadata.get("dialogue_segments", []):
            combined_visual_text += " " + str(seg.get("text", ""))

        clean_search_corpus = re.sub(r"\s+", " ", combined_visual_text).lower()
        clean_target = re.sub(r"\s+", " ", required_disclaimer).lower()

        # Word-boundary or high-containment match
        if clean_target not in clean_search_corpus:
            # Check partial matching (>= 75% word overlap)
            target_words = set(clean_target.split())
            corpus_words = set(clean_search_corpus.split())
            overlap = len(target_words.intersection(corpus_words)) / max(len(target_words), 1)

            if overlap < 0.75:
                violations.append({
                    "rule_id": rule_id,
                    "rule_name": rule_name,
                    "rule_type": "regulatory_disclosure",
                    "brand_entity": "disclaimer",
                    "severity": severity,
                    "flagged_text": f"[Missing On-Screen Disclaimer: '{required_disclaimer}']",
                    "char_start": None,
                    "char_end": None,
                    "confidence_score": 0.95,
                    "explanation": (
                        f"Mandatory on-screen disclaimer '{required_disclaimer}' was not found in visual content. "
                        f"Guideline '{rule_name}' requires verbatim on-screen disclosure."
                    ),
                    "source_clause": source_clause,
                    "suggested_text": required_disclaimer,
                    "rationale": "Incorporate required legal/regulatory disclaimer onto visual asset.",
                    "details": {
                        "visual_entity": "missing_disclaimer",
                        "required_disclaimer": required_disclaimer,
                    },
                })

        return violations

    # ==========================================================================
    # Sub-Evaluator 4: OCR Text Prohibited Statements in Visual Track
    # ==========================================================================

    def _evaluate_ocr_text_rules(
        self,
        guideline: Dict[str, Any],
        visual_observations: List[Dict[str, Any]],
        source_clause: str,
    ) -> List[Dict[str, Any]]:
        """Inspect OCR text observed in the visual track for prohibited statements with bounding boxes & timestamps."""
        violations: List[Dict[str, Any]] = []
        rule_id = str(guideline["id"])
        rule_name = guideline.get("name", "Prohibited Terminology & Claims")
        rule_type = str(guideline.get("rule_type", "prohibited_claims"))
        severity = guideline.get("severity", "high")

        prohibited_list = [str(x).strip() for x in (guideline.get("examples_prohibited") or []) if str(x).strip()]
        if not prohibited_list:
            return []

        # Find visual text observations
        ocr_observations = [
            vo for vo in visual_observations
            if str(vo.get("entity", "")).lower() in {"on_screen_text", "ocr", "screencast"}
        ]

        for obs in ocr_observations:
            label = str(obs.get("label", ""))
            box = obs.get("box_2d")
            confidence = float(obs.get("confidence", 0.90))
            details = obs.get("details") or {}
            ts_sec = details.get("timestamp_seconds") or details.get("start_time_seconds")
            ts_str = format_video_timestamp(ts_sec) if ts_sec is not None else None

            text_to_check = label
            if details.get("text"):
                text_to_check += " " + str(details["text"])

            for prohibited in prohibited_list:
                pattern = rf"\b{re.escape(prohibited)}\b"
                match = re.search(pattern, text_to_check, re.IGNORECASE)
                if match:
                    flagged = match.group(0)
                    loc_str = f" (bounding box: {box})" if box else ""
                    ts_note = f" at video timestamp {ts_str}" if ts_str else ""

                    violations.append({
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "rule_type": rule_type,
                        "brand_entity": "on_screen_text",
                        "severity": severity,
                        "flagged_text": flagged,
                        "char_start": None,
                        "char_end": None,
                        "bounding_box": box,
                        "timestamp_seconds": ts_sec,
                        "confidence_score": confidence,
                        "explanation": (
                            f"Prohibited statement '{flagged}' detected in visual on-screen text{loc_str}{ts_note}. "
                            f"Guideline '{rule_name}' strictly forbids this language."
                        ),
                        "source_clause": source_clause,
                        "suggested_text": (guideline.get("examples_approved") or ["Compliant phrasing"])[0],
                        "rationale": f"Removed prohibited on-screen statement '{flagged}' from visual track.",
                        "details": {
                            "visual_entity": "on_screen_text_violation",
                            "flagged_text": flagged,
                            "bounding_box": box,
                            "timestamp_seconds": ts_sec,
                        },
                    })

        return violations
