"""Comprehensive test suite for Phase 2 Stage 2C: Visual Brand Compliance Engine.

Validates:
1. Approved versus unapproved/inactive visual rules.
2. Brand color palette comparison (matching, unapproved dominant deviation, and prohibited colors).
3. Logo presence, prohibited logo detection, and clear-space margin violations.
4. Distinguishing missing logo from undetected logo when vision is offline/unavailable.
5. Uncertain visual observations (< 0.70 confidence) with explicit transparency tagging.
6. Required on-screen disclaimer detection and missing disclaimer enforcement.
7. OCR text extraction in visual track and prohibited statement detection.
8. Bounding-box coordinate preservation and video timestamp formatting.
9. Multi-modal finding deduplication via bounding box IoU (> 0.70).
10. Full LangGraph end-to-end integration and risk score calculation.
11. Multi-tenant isolation (Tenant B never evaluates Tenant A's visual guidelines).
12. Resilience to empty, malformed, or offline visual metadata.
"""

import uuid
from typing import Any, Dict, List
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.engine.graph import compliance_graph
from app.engine.risk_scorer import (
    calculate_iou,
    calculate_risk_score,
    deduplicate_findings,
)
from app.engine.rules.visual import (
    VisualRuleDetector,
    color_distance,
    extract_hex_colors,
    format_video_timestamp,
    hex_to_rgb,
)
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.schemas.common import RuleType, SeverityLevel


# ==============================================================================
# 1. Pure Unit Tests: Color & Mathematical Helpers
# ==============================================================================

def test_hex_to_rgb_and_extraction():
    """Verify robust hex extraction and RGB conversion."""
    # 6-char hex
    assert hex_to_rgb("#0052CC") == (0, 82, 204)
    assert hex_to_rgb("#ffffff") == (255, 255, 255)
    assert hex_to_rgb("#000000") == (0, 0, 0)

    # 3-char shorthand expansion
    assert hex_to_rgb("#FFF") == (255, 255, 255)
    assert hex_to_rgb("#05C") == (0, 85, 204)

    # Invalid
    assert hex_to_rgb("not-a-color") is None
    assert hex_to_rgb("#12345") is None

    # Extraction from text and lists
    text = "Our palette uses #0052CC (Primary) and secondary #1E40AF with #FFFFFF background."
    extracted = extract_hex_colors(text)
    assert extracted == {"#0052CC", "#1E40AF", "#FFFFFF"}

    list_data = ["#FF0000", "Accent: #00FF00", "Invalid #ZZZ"]
    assert extract_hex_colors(list_data) == {"#FF0000", "#00FF00"}


def test_color_distance_metric():
    """Verify normalized Euclidean color distance calculation."""
    c_blue1 = (0, 82, 204)
    c_blue2 = (0, 82, 205)  # Compression delta (almost identical)
    c_red = (255, 0, 0)
    c_white = (255, 255, 255)
    c_black = (0, 0, 0)

    # Identical colors
    assert color_distance(c_blue1, c_blue1) == 0.0

    # Compression noise (< 5% distance)
    dist_noise = color_distance(c_blue1, c_blue2)
    assert dist_noise < 0.01

    # Completely different colors (> 15% distance)
    assert color_distance(c_blue1, c_red) > 0.40

    # Max distance (Black to White)
    assert pytest.approx(color_distance(c_black, c_white), 0.001) == 1.0


def test_format_video_timestamp():
    """Verify video timestamp formatting into MM:SS.mmm."""
    assert format_video_timestamp(0.0) == "00:00.000"
    assert format_video_timestamp(3.5) == "00:03.500"
    assert format_video_timestamp(65.25) == "01:05.250"
    assert format_video_timestamp(None) == "N/A"
    assert format_video_timestamp(-1.0) == "N/A"


# ==============================================================================
# 2. Detector Unit Tests: VisualRuleDetector
# ==============================================================================

@pytest.fixture
def visual_detector() -> VisualRuleDetector:
    return VisualRuleDetector()


def test_approved_vs_unapproved_visual_rules(visual_detector: VisualRuleDetector):
    """Visual detector only evaluates active guidelines with visual/logo/color policies."""
    active_visual_gl = {
        "id": uuid.uuid4(),
        "name": "Corporate Logo Usage",
        "rule_type": "logo_usage",
        "directive": "All marketing assets must include the primary BrandShield AI logo.",
        "examples_approved": ["BrandShield AI Primary Logo"],
        "examples_prohibited": ["Competitor Logo"],
        "is_active": True,
    }

    inactive_gl = {
        **active_visual_gl,
        "is_active": False,
    }

    text_only_gl = {
        "id": uuid.uuid4(),
        "name": "Sentence Casing Standard",
        "rule_type": "tone_of_voice",
        "directive": "Never use all-caps sentences.",
        "examples_approved": ["Protect your brand."],
        "examples_prohibited": ["PROTECT YOUR BRAND."],
        "is_active": True,
    }

    meta = {
        "media_type": "image",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {
                "entity": "logo",
                "label": "Competitor Logo",
                "confidence": 0.95,
                "box_2d": [0.1, 0.1, 0.4, 0.4],
            }
        ],
    }

    # 1. Active visual guideline flags prohibited logo
    res_active = visual_detector.evaluate(content="", guideline=active_visual_gl, multimodal_metadata=meta)
    assert len(res_active) == 1
    assert res_active[0]["flagged_text"] == "Competitor Logo"

    # 2. Inactive visual guideline is ignored (zero violations)
    res_inactive = visual_detector.evaluate(content="", guideline=inactive_gl, multimodal_metadata=meta)
    assert len(res_inactive) == 0

    # 3. Non-visual guideline is skipped by visual detector
    res_text = visual_detector.evaluate(content="", guideline=text_only_gl, multimodal_metadata=meta)
    assert len(res_text) == 0


def test_color_palette_matching_and_violations(visual_detector: VisualRuleDetector):
    """Verify approved palette matching, unapproved color deviation, and prohibited color violations."""
    color_gl = {
        "id": uuid.uuid4(),
        "name": "Official Brand Color Palette",
        "rule_type": "color_palette",
        "severity": "high",
        "directive": "Official brand colors are strictly limited to #0052CC (Primary Blue) and #FFFFFF (White). Red (#FF0000) is strictly prohibited.",
        "examples_approved": ["#0052CC", "#FFFFFF"],
        "examples_prohibited": ["#FF0000"],
        "is_active": True,
    }

    # Case A: Approved color with slight compression noise (#0052CD vs #0052CC) -> 0 violations
    meta_approved = {
        "media_type": "image",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {"entity": "color", "label": "#0052CD", "confidence": 1.0, "details": {"percentage": 85}},
            {"entity": "color", "label": "#FFFFFF", "confidence": 1.0, "details": {"percentage": 15}},
        ],
    }
    res_appr = visual_detector.evaluate(content="", guideline=color_gl, multimodal_metadata=meta_approved)
    assert len(res_appr) == 0

    # Case B: Prohibited color detected (#FF0000) -> Prohibited color violation
    meta_prohibited = {
        "media_type": "image",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {"entity": "color", "label": "#FF0000", "confidence": 0.98, "details": {"percentage": 25}},
            {"entity": "color", "label": "#0052CC", "confidence": 1.0, "details": {"percentage": 75}},
        ],
    }
    res_proh = visual_detector.evaluate(content="", guideline=color_gl, multimodal_metadata=meta_prohibited)
    assert len(res_proh) == 1
    assert res_proh[0]["flagged_text"] == "#FF0000"
    assert "Prohibited brand color '#FF0000'" in res_proh[0]["explanation"]
    assert res_proh[0]["rule_type"] == "color_palette"

    # Case C: Unapproved dominant color deviation (#10B981, Emerald Green, 40%) -> Unapproved color violation
    meta_unapproved = {
        "media_type": "image",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {"entity": "color", "label": "#10B981", "confidence": 0.95, "details": {"percentage": 40}},
            {"entity": "color", "label": "#0052CC", "confidence": 1.0, "details": {"percentage": 60}},
        ],
    }
    res_unappr = visual_detector.evaluate(content="", guideline=color_gl, multimodal_metadata=meta_unapproved)
    assert len(res_unappr) == 1
    assert res_unappr[0]["flagged_text"] == "#10B981"
    assert "Unapproved brand color '#10B981'" in res_unappr[0]["explanation"]


def test_logo_clear_space_violation(visual_detector: VisualRuleDetector):
    """Verify clear-space margin violation detection."""
    clear_space_gl = {
        "id": uuid.uuid4(),
        "name": "Logo Clear Space Isolation Requirement",
        "rule_type": "visual_identity",
        "severity": "medium",
        "directive": "Maintain at least 10% clear space isolation margin around all brand logos.",
        "examples_approved": ["BrandShield AI Primary Logo"],
        "examples_prohibited": ["Zero margin logo placement"],
        "tags": ["logo", "clear_space"],
        "is_active": True,
    }

    # Bounding box touching extreme canvas edge (ymin = 0.01 < 0.03 margin ceiling)
    meta = {
        "media_type": "image",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {
                "entity": "logo",
                "label": "BrandShield AI Primary Logo",
                "confidence": 0.95,
                "box_2d": [0.01, 0.01, 0.25, 0.25],
                "details": {"notes": "Logo placed directly adjacent to top-left edge"},
            }
        ],
    }

    res = visual_detector.evaluate(content="", guideline=clear_space_gl, multimodal_metadata=meta)
    assert len(res) == 1
    assert "Logo Clear Space" in res[0]["flagged_text"]
    assert res[0]["bounding_box"] == [0.01, 0.01, 0.25, 0.25]
    assert "breaches required clear-space margin" in res[0]["explanation"]


def test_missing_logo_vs_offline_safeguard(visual_detector: VisualRuleDetector):
    """Safeguard: Distinguish confirmed missing logo from uninspected/offline vision."""
    mandatory_logo_gl = {
        "id": uuid.uuid4(),
        "name": "Mandatory Logo Presence",
        "rule_type": "logo_usage",
        "severity": "high",
        "directive": "Every marketing visual asset must include the official BrandShield AI Logo.",
        "examples_approved": ["BrandShield AI Logo"],
        "tags": ["logo", "mandatory"],
        "is_active": True,
    }

    # Case 1: Vision succeeded, 0 logos observed -> Confirmed missing logo violation
    meta_success_empty = {
        "media_type": "image",
        "processing_status": "SUCCESS",
        "visual_observations": [],
    }
    res_success = visual_detector.evaluate(content="", guideline=mandatory_logo_gl, multimodal_metadata=meta_success_empty)
    assert len(res_success) == 1
    assert "[Missing Brand Logo: BrandShield AI Logo]" in res_success[0]["flagged_text"]

    # Case 2: Vision was UNAVAILABLE (offline/rate-limited) -> Zero false violations!
    meta_offline = {
        "media_type": "image",
        "processing_status": "UNAVAILABLE",
        "fallback_reason": "Gemini API unavailable",
        "visual_observations": [],
    }
    res_offline = visual_detector.evaluate(content="", guideline=mandatory_logo_gl, multimodal_metadata=meta_offline)
    assert len(res_offline) == 0

    # Case 3: Vision FAILED -> Zero false violations
    meta_failed = {
        "media_type": "image",
        "processing_status": "FAILED",
        "fallback_reason": "Corrupted file",
        "visual_observations": [],
    }
    res_failed = visual_detector.evaluate(content="", guideline=mandatory_logo_gl, multimodal_metadata=meta_failed)
    assert len(res_failed) == 0


def test_uncertain_visual_observation_tagging(visual_detector: VisualRuleDetector):
    """Low-confidence visual findings (< 0.70) are explicitly flagged with transparency notice."""
    prohibited_logo_gl = {
        "id": uuid.uuid4(),
        "name": "Unauthorized Watermark Policy",
        "rule_type": "logo_usage",
        "severity": "high",
        "directive": "Third-party watermarks or stock photo logos are prohibited.",
        "examples_approved": ["Clean asset"],
        "examples_prohibited": ["StockPhoto Watermark"],
        "is_active": True,
    }

    meta_uncertain = {
        "media_type": "image",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {
                "entity": "logo",
                "label": "StockPhoto Watermark",
                "confidence": 0.52,  # Low confidence observation
                "box_2d": [0.8, 0.8, 0.95, 0.95],
            }
        ],
    }

    res = visual_detector.evaluate(content="", guideline=prohibited_logo_gl, multimodal_metadata=meta_uncertain)
    assert len(res) == 1
    assert "[UNCERTAIN OBSERVATION (confidence: 0.52)]" in res[0]["explanation"]
    assert res[0]["confidence_score"] == 0.52


def test_required_on_screen_disclaimer(visual_detector: VisualRuleDetector):
    """Verify detection of missing required on-screen disclaimers on visual media."""
    disclaimer_gl = {
        "id": uuid.uuid4(),
        "name": "Financial Services On-Screen Disclaimer Mandate",
        "rule_type": "regulatory_disclosure",
        "severity": "critical",
        "directive": "All visual and video advertisements must include the on-screen disclaimer: 'Past performance does not guarantee future results.'",
        "examples_approved": ["Past performance does not guarantee future results."],
        "tags": ["disclaimer", "disclosure", "on_screen"],
        "is_active": True,
    }

    # Case A: Disclaimer missing from visual OCR and dialogue -> Violation
    meta_missing = {
        "media_type": "video",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {"entity": "on_screen_text", "label": "BrandShield AI Demo", "box_2d": [0.1, 0.1, 0.3, 0.9]}
        ],
        "dialogue_segments": [
            {"speaker": "Speaker 1", "text": "Invest with confidence today."}
        ],
    }
    res_missing = visual_detector.evaluate(content="Invest with confidence today.", guideline=disclaimer_gl, multimodal_metadata=meta_missing)
    assert len(res_missing) == 1
    assert "[Missing On-Screen Disclaimer: 'Past performance does not guarantee future results.']" in res_missing[0]["flagged_text"]
    assert res_missing[0]["rule_type"] == "regulatory_disclosure"

    # Case B: Disclaimer present in visual OCR text -> 0 violations
    meta_present = {
        "media_type": "video",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {
                "entity": "on_screen_text",
                "label": "Super: Past performance does not guarantee future results.",
                "box_2d": [0.85, 0.05, 0.95, 0.95],
            }
        ],
    }
    res_present = visual_detector.evaluate(content="Demo video", guideline=disclaimer_gl, multimodal_metadata=meta_present)
    assert len(res_present) == 0


def test_ocr_text_prohibited_claims_with_box_and_timestamp(visual_detector: VisualRuleDetector):
    """OCR on-screen text matching prohibited claims preserves bounding box and timestamp."""
    claims_gl = {
        "id": uuid.uuid4(),
        "name": "Absolute Performance Claims Prohibition",
        "rule_type": "prohibited_claims",
        "severity": "critical",
        "directive": "Never state or display on-screen '100% guaranteed compliance'.",
        "examples_approved": ["Highly reliable brand governance"],
        "examples_prohibited": ["100% guaranteed compliance"],
        "is_active": True,
    }

    meta_video = {
        "media_type": "video",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {
                "entity": "on_screen_text",
                "label": "Title card: BrandShield delivers 100% guaranteed compliance across all channels.",
                "confidence": 0.96,
                "box_2d": [0.2, 0.1, 0.4, 0.9],
                "details": {"timestamp_seconds": 5.25},
            }
        ],
    }

    res = visual_detector.evaluate(content="", guideline=claims_gl, multimodal_metadata=meta_video)
    assert len(res) == 1
    assert res[0]["flagged_text"].lower() == "100% guaranteed compliance"
    assert res[0]["bounding_box"] == [0.2, 0.1, 0.4, 0.9]
    assert res[0]["timestamp_seconds"] == 5.25
    assert "video timestamp 00:05.250" in res[0]["explanation"]


# ==============================================================================
# 3. Deduplication & Risk Scorer Integration Tests
# ==============================================================================

def test_visual_finding_deduplication_via_iou():
    """Verify that multiple detector passes on the same visual entity with IoU > 0.70 are deduplicated."""
    box_a = [0.10, 0.10, 0.50, 0.50]
    box_b = [0.11, 0.10, 0.51, 0.50]  # Overlapping box with IoU > 0.90
    box_c = [0.70, 0.70, 0.95, 0.95]  # Separate box in bottom-right corner (IoU == 0.0)

    assert calculate_iou(box_a, box_b) > 0.85
    assert calculate_iou(box_a, box_c) == 0.0

    finding1 = {
        "rule_id": str(uuid.uuid4()),
        "rule_name": "Logo Check A",
        "rule_type": "logo_usage",
        "brand_entity": "logo",
        "severity": "HIGH",
        "confidence_score": 0.95,
        "bounding_box": box_a,
        "flagged_text": "Unapproved Logo",
    }

    finding2 = {
        "rule_id": str(uuid.uuid4()),
        "rule_name": "Logo Check B",
        "rule_type": "logo_usage",
        "brand_entity": "logo",
        "severity": "MEDIUM",  # Lower severity
        "confidence_score": 0.90,
        "bounding_box": box_b,
        "flagged_text": "Unapproved Logo",
    }

    finding3 = {
        "rule_id": str(uuid.uuid4()),
        "rule_name": "Logo Check C",
        "rule_type": "logo_usage",
        "brand_entity": "logo",
        "severity": "LOW",
        "confidence_score": 0.85,
        "bounding_box": box_c,
        "flagged_text": "Secondary Watermark",
    }

    # Deduplication should collapse finding1 and finding2 into 1 finding (retaining HIGH severity)
    deduped = deduplicate_findings([finding1, finding2, finding3])
    assert len(deduped) == 2
    assert any(f["severity"] == "HIGH" for f in deduped)
    assert not any(f["severity"] == "MEDIUM" for f in deduped)
    assert any(f["severity"] == "LOW" for f in deduped)

    # Risk scoring calculation verifies mathematical score
    # HIGH (25.0 * 0.95 = 23.75) + LOW (4.0 * 0.85 = 3.4) = 27.15
    # Social multiplier 1.15 -> 27.15 * 1.15 = 31.2225 -> clamped 31.2
    score_res = calculate_risk_score(
        findings=[finding1, finding2, finding3],
        target_channel="twitter_x",
        deduplicate=True,
    )
    assert score_res.display_score == 31.2
    assert pytest.approx(score_res.risk_score, 0.001) == 31.2225
    assert score_res.risk_level == "MEDIUM"


# ==============================================================================
# 4. End-to-End LangGraph Compliance Graph Test with Visual Standards
# ==============================================================================

@pytest.mark.asyncio
async def test_end_to_end_langgraph_visual_inspection():
    """Verify LangGraph full pipeline execution with visual logo and color rules."""
    gl_logo_id = uuid.uuid4()
    gl_color_id = uuid.uuid4()

    guidelines = [
        {
            "id": str(gl_logo_id),
            "name": "Mandatory Brand Logo",
            "rule_type": "logo_usage",
            "severity": "high",
            "description": "All brand visual assets must feature the official primary logo.",
            "directive": "All marketing image and video assets must include the primary BrandShield AI logo.",
            "examples_approved": ["BrandShield AI Primary Logo"],
            "examples_prohibited": ["Unauthorized Competitor Logo"],
            "is_active": True,
        },
        {
            "id": str(gl_color_id),
            "name": "Corporate Palette Mandate",
            "rule_type": "color_palette",
            "severity": "medium",
            "description": "Colors are strictly restricted to official palette.",
            "directive": "Official brand colors are strictly limited to #0052CC and #FFFFFF.",
            "examples_approved": ["#0052CC", "#FFFFFF"],
            "examples_prohibited": ["#FF0000"],
            "is_active": True,
        },
    ]

    initial_state = {
        "submission_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "title": "Summer Campaign Visual Asset",
        "content": "[Image asset: summer_hero.png]",
        "target_channel": "linkedin",
        "target_audience": "Enterprise Buyers",
        "version": 1,
        "media_type": "image",
        "multimodal_metadata": {
            "media_type": "image",
            "processing_status": "SUCCESS",
            "visual_observations": [
                {
                    "entity": "logo",
                    "label": "Unauthorized Competitor Logo",
                    "confidence": 0.95,
                    "box_2d": [0.1, 0.1, 0.4, 0.4],
                },
                {
                    "entity": "color",
                    "label": "#FF0000",
                    "confidence": 0.98,
                    "details": {"percentage": 30},
                },
            ],
        },
        "guidelines": guidelines,
        "raw_violations": [],
        "validated_violations": [],
        "suggestions": [],
        "claims": [],
        "claim_verifications": [],
        "is_compliant": False,
        "total_violations": 0,
        "summary": "",
        "risk_score": 0.0,
        "risk_level": "LOW",
        "is_escalated": False,
        "channel_multiplier": 1.0,
        "audience_multiplier": 1.0,
        "risk_breakdown": {},
        "ai_status": {},
        "error": None,
    }

    result = await compliance_graph.ainvoke(initial_state)

    assert result["is_compliant"] is False
    assert result["total_violations"] == 2
    assert len(result["validated_violations"]) == 2

    # Check evidence citations and suggestions generated
    assert len(result["suggestions"]) == 2
    assert result["risk_score"] > 0.0
    assert "Mandatory human reviewer sign-off is required" in result["summary"]


# ==============================================================================
# 5. Multi-Tenant Isolation Tests for Visual Rules
# ==============================================================================

@pytest_asyncio.fixture
async def visual_multi_session():
    """Isolated SQLite database session testing tenant boundary enforcement."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with test_engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON;")
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_maker() as session:
        # Tenant A: has visual logo guideline
        org_a = Organization(id=uuid.uuid4(), name="Tenant A", slug="tenant-a", is_active=True)
        session.add(org_a)
        await session.flush()

        gl_a = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            name="Tenant A Logo Standard",
            rule_type="logo_usage",
            severity="critical",
            description="Tenant A logo required.",
            directive="Tenant A assets must feature the Tenant A Crest.",
            examples_approved=["Tenant A Crest"],
            examples_prohibited=["Old Crest"],
            is_active=True,
        )
        session.add(gl_a)

        # Tenant B: has zero visual guidelines (only tone)
        org_b = Organization(id=uuid.uuid4(), name="Tenant B", slug="tenant-b", is_active=True)
        session.add(org_b)
        await session.flush()

        gl_b = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org_b.id,
            name="Tenant B Professional Tone",
            rule_type="tone_of_voice",
            severity="low",
            description="Tenant B tone standard.",
            directive="Use respectful phrasing.",
            examples_approved=["Thank you for your business."],
            examples_prohibited=["Hey buddy"],
            is_active=True,
        )
        session.add(gl_b)
        await session.commit()

        yield session, org_a.id, org_b.id

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_tenant_isolation_visual_guidelines(
    visual_detector: VisualRuleDetector,
    visual_multi_session,
):
    """Verify Tenant B's media evaluation never runs against Tenant A's visual guidelines."""
    session, org_a_id, org_b_id = visual_multi_session

    # Query active guidelines for Tenant B
    stmt_b = select(BrandGuideline).where(
        BrandGuideline.organization_id == org_b_id,
        BrandGuideline.is_active == True,  # noqa: E712
    )
    guidelines_b = (await session.execute(stmt_b)).scalars().all()
    serialized_b = [
        {
            "id": str(g.id),
            "name": g.name,
            "rule_type": g.rule_type,
            "severity": g.severity,
            "directive": g.directive,
            "examples_approved": g.examples_approved or [],
            "examples_prohibited": g.examples_prohibited or [],
            "is_active": g.is_active,
        }
        for g in guidelines_b
    ]

    meta_b = {
        "media_type": "image",
        "processing_status": "SUCCESS",
        "visual_observations": [
            {"entity": "logo", "label": "Old Crest", "confidence": 0.95}
        ],
    }

    # Running Tenant B's visual upload against Tenant B's active guidelines produces 0 violations
    # because Tenant A's logo rule is strictly segregated and inaccessible to Tenant B
    all_violations = []
    for gl in serialized_b:
        v = visual_detector.evaluate(content="", guideline=gl, multimodal_metadata=meta_b)
        all_violations.extend(v)

    assert len(all_violations) == 0
