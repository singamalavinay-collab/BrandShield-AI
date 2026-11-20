"""BrandShield AI — Brand Guideline Extraction Agent & Parsing Pipeline.

Phase 1, Milestone 3:
Automated ingestion and extraction of brand guidelines from PDF and DOCX manuals.
Extracts:
1. Terminology (approved and prohibited terms, naming conventions)
2. Tone of Voice (prescribed style, brand personality)
3. Messaging Pillars (core value propositions, brand pillars)
4. Prohibited Claims & Restrictions (unsubstantiated claims, disclaimers)
5. Approved Facts (verified corporate facts, metrics)

Guarantees:
- Strict document lineage: document name, version, SHA-256 digest, page/paragraph provenance.
- Dual-mode extraction: Gemini LLM structured extraction when available; robust deterministic pattern parser fallback.
- Never activates extracted guidelines automatically (staged strictly as PENDING_APPROVAL).
- Safely rejects encrypted PDFs and flags scanned PDFs requiring OCR.
- Pure Python memory-safe execution with zero external paid binary dependencies.
"""

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import uuid

from app.engine.ai_provider import AIProvider
from app.engine.multimodal.extractor import (
    DocumentExtractionError,
    DocumentExtractionResult,
    extract_document_text,
)
from app.engine.multimodal.validator import MimeType
from app.schemas.candidate_guidelines import CandidateGuidelineCreate
from app.schemas.common import RuleType, SeverityLevel

logger = logging.getLogger("brandshield.engine.guideline_extractor")


# ==============================================================================
# Deterministic Pattern Rules & Keyword Dictionaries
# ==============================================================================

TERMINOLOGY_PATTERNS = [
    re.compile(r"(?:always\s+use|approved\s+terms?|preferred\s+terms?|naming\s+conventions?|capitalization)[\s:]+(.+)", re.IGNORECASE),
    re.compile(r"(?:never\s+use|prohibited\s+terms?|forbidden\s+terms?|avoid\s+using|do\s+not\s+say)[\s:]+(.+)", re.IGNORECASE),
    re.compile(r"(?:refer\s+to\s+(?:the\s+)?company\s+as|call\s+(?:the\s+)?product)[\s:]+(.+)", re.IGNORECASE),
]

TONE_PATTERNS = [
    re.compile(r"(?:tone\s+of\s+voice|brand\s+voice|writing\s+style|personality)[\s:]+(.+)", re.IGNORECASE),
    re.compile(r"(?:our\s+tone\s+is|we\s+sound|voice\s+should\s+be)[\s:]+(.+)", re.IGNORECASE),
]

MESSAGING_PATTERNS = [
    re.compile(r"(?:messaging\s+pillar|core\s+pillar|value\s+proposition|brand\s+pillar|mission)[\s:]+(.+)", re.IGNORECASE),
    re.compile(r"(?:our\s+mission\s+is|we\s+stand\s+for|key\s+message)[\s:]+(.+)", re.IGNORECASE),
]

RESTRICTION_PATTERNS = [
    re.compile(r"(?:prohibited\s+claims?|forbidden\s+claims?|never\s+claim|do\s+not\s+claim)[\s:]+(.+)", re.IGNORECASE),
    re.compile(r"(?:regulatory\s+restrictions?|legal\s+disclaimer|compliance\s+warning|mandatory\s+disclosure)[\s:]+(.+)", re.IGNORECASE),
    re.compile(r"(?:unsubstantiated|absolute\s+guarantees?)[\s:]+(.+)", re.IGNORECASE),
]

FACT_PATTERNS = [
    re.compile(r"(?:approved\s+facts?|verified\s+claims?|company\s+facts?|key\s+metrics?|by\s+the\s+numbers)[\s:]+(.+)", re.IGNORECASE),
    re.compile(r"(?:founded\s+in|headquartered|protects?\s+over|trusted\s+by|certified\s+for)[\s:]+(.+)", re.IGNORECASE),
]


def _clean_str(text: str) -> str:
    """Strip extraneous quotes and whitespace."""
    s = text.strip()
    s = re.sub(r"^[\"'\-•*]+\s*", "", s)
    s = re.sub(r"[\"'\s]+$", "", s)
    return s.strip()


# ==============================================================================
# Deterministic Rule Extractor (Offline / Fallback Engine)
# ==============================================================================

def _extract_deterministic_rules(
    extraction_res: DocumentExtractionResult,
    document_name: str,
    document_version: Optional[str],
    file_hash: str,
) -> List[CandidateGuidelineCreate]:
    """Parse document paragraphs using deterministic keyword and structural patterns."""
    candidates: List[CandidateGuidelineCreate] = []
    seen_titles = set()

    current_section = "General Brand Guidelines"

    # Iterate over pages and paragraphs to preserve exact page and paragraph provenance
    for page_num, page_text in extraction_res.page_texts.items():
        paragraphs = [p.strip() for p in page_text.splitlines() if p.strip()]

        for p_idx, para in enumerate(paragraphs, start=1):
            # Check for section header heuristic (short line, title-like)
            if len(para) < 60 and (para.endswith(":") or para.isupper() or not para.endswith(".")):
                current_section = _clean_str(para.rstrip(":"))
                continue

            lower_para = para.lower()

            # 1. Terminology Detection
            matched_term = False
            for pat in TERMINOLOGY_PATTERNS:
                m = pat.search(para)
                if m:
                    directive_text = para
                    extracted_text = _clean_str(m.group(1))
                    rule_title = f"{current_section}: Terminology Standard" if "terminol" not in current_section.lower() else current_section
                    if rule_title in seen_titles:
                        rule_title = f"{rule_title} ({len(candidates) + 1})"
                    seen_titles.add(rule_title)

                    examples_app = []
                    examples_pro = []
                    if "never" in lower_para or "prohibited" in lower_para or "do not" in lower_para:
                        examples_pro.append(extracted_text)
                    else:
                        examples_app.append(extracted_text)

                    candidates.append(
                        CandidateGuidelineCreate(
                            name=rule_title[:200],
                            rule_type=RuleType.TERMINOLOGY,
                            severity=SeverityLevel.MEDIUM,
                            description=f"Terminology rule identified in section '{current_section}'.",
                            directive=directive_text[:4000],
                            examples_approved=examples_app,
                            examples_prohibited=examples_pro,
                            tags=["terminology", "brand_language", "naming"],
                            source_reference=f"{document_name} (Page {page_num})",
                            source_metadata={
                                "document_name": document_name,
                                "document_version": document_version,
                                "file_hash_sha256": file_hash,
                                "page_number": page_num,
                                "paragraph_index": p_idx,
                                "section": current_section,
                                "extraction_engine": "deterministic_fallback",
                            },
                        )
                    )
                    matched_term = True
                    break

            if matched_term:
                continue

            # 2. Prohibited Claims & Restrictions
            matched_restrict = False
            for pat in RESTRICTION_PATTERNS:
                m = pat.search(para)
                if m:
                    rule_title = f"{current_section}: Prohibited Claims & Restrictions" if "prohibit" not in current_section.lower() else current_section
                    if rule_title in seen_titles:
                        rule_title = f"{rule_title} ({len(candidates) + 1})"
                    seen_titles.add(rule_title)

                    candidates.append(
                        CandidateGuidelineCreate(
                            name=rule_title[:200],
                            rule_type=RuleType.PROHIBITED_CLAIMS,
                            severity=SeverityLevel.CRITICAL if "never" in lower_para or "guarantee" in lower_para else SeverityLevel.HIGH,
                            description=f"Marketing or compliance restriction identified in section '{current_section}'.",
                            directive=para[:4000],
                            examples_approved=[],
                            examples_prohibited=[_clean_str(m.group(1))],
                            tags=["compliance", "prohibited_claims", "legal_restriction"],
                            source_reference=f"{document_name} (Page {page_num})",
                            source_metadata={
                                "document_name": document_name,
                                "document_version": document_version,
                                "file_hash_sha256": file_hash,
                                "page_number": page_num,
                                "paragraph_index": p_idx,
                                "section": current_section,
                                "extraction_engine": "deterministic_fallback",
                            },
                        )
                    )
                    matched_restrict = True
                    break

            if matched_restrict:
                continue

            # 3. Tone of Voice
            matched_tone = False
            for pat in TONE_PATTERNS:
                m = pat.search(para)
                if m:
                    rule_title = f"{current_section}: Tone & Voice Directive" if "tone" not in current_section.lower() else current_section
                    if rule_title in seen_titles:
                        rule_title = f"{rule_title} ({len(candidates) + 1})"
                    seen_titles.add(rule_title)

                    candidates.append(
                        CandidateGuidelineCreate(
                            name=rule_title[:200],
                            rule_type=RuleType.TONE_OF_VOICE,
                            severity=SeverityLevel.LOW,
                            description=f"Brand voice and tone requirement specified in section '{current_section}'.",
                            directive=para[:4000],
                            examples_approved=[_clean_str(m.group(1))],
                            examples_prohibited=[],
                            tags=["tone_of_voice", "brand_personality"],
                            source_reference=f"{document_name} (Page {page_num})",
                            source_metadata={
                                "document_name": document_name,
                                "document_version": document_version,
                                "file_hash_sha256": file_hash,
                                "page_number": page_num,
                                "paragraph_index": p_idx,
                                "section": current_section,
                                "extraction_engine": "deterministic_fallback",
                            },
                        )
                    )
                    matched_tone = True
                    break

            if matched_tone:
                continue

            # 4. Messaging Pillars
            matched_msg = False
            for pat in MESSAGING_PATTERNS:
                m = pat.search(para)
                if m:
                    rule_title = f"{current_section}: Core Brand Messaging Pillar" if "pillar" not in current_section.lower() else current_section
                    if rule_title in seen_titles:
                        rule_title = f"{rule_title} ({len(candidates) + 1})"
                    seen_titles.add(rule_title)

                    candidates.append(
                        CandidateGuidelineCreate(
                            name=rule_title[:200],
                            rule_type=RuleType.MESSAGING_PILLAR,
                            severity=SeverityLevel.MEDIUM,
                            description=f"Strategic messaging pillar identified in section '{current_section}'.",
                            directive=para[:4000],
                            examples_approved=[_clean_str(m.group(1))],
                            examples_prohibited=[],
                            tags=["messaging_pillar", "value_proposition"],
                            source_reference=f"{document_name} (Page {page_num})",
                            source_metadata={
                                "document_name": document_name,
                                "document_version": document_version,
                                "file_hash_sha256": file_hash,
                                "page_number": page_num,
                                "paragraph_index": p_idx,
                                "section": current_section,
                                "extraction_engine": "deterministic_fallback",
                            },
                        )
                    )
                    matched_msg = True
                    break

            if matched_msg:
                continue

            # 5. Approved Facts
            for pat in FACT_PATTERNS:
                m = pat.search(para)
                if m:
                    rule_title = f"{current_section}: Approved Corporate Fact" if "fact" not in current_section.lower() else current_section
                    if rule_title in seen_titles:
                        rule_title = f"{rule_title} ({len(candidates) + 1})"
                    seen_titles.add(rule_title)

                    candidates.append(
                        CandidateGuidelineCreate(
                            name=rule_title[:200],
                            rule_type=RuleType.FACTUAL_ACCURACY,
                            severity=SeverityLevel.MEDIUM,
                            description=f"Verified corporate claim or statistic in section '{current_section}'.",
                            directive=para[:4000],
                            examples_approved=[_clean_str(m.group(1))],
                            examples_prohibited=[],
                            tags=["factual_accuracy", "approved_facts", "metrics"],
                            source_reference=f"{document_name} (Page {page_num})",
                            source_metadata={
                                "document_name": document_name,
                                "document_version": document_version,
                                "file_hash_sha256": file_hash,
                                "page_number": page_num,
                                "paragraph_index": p_idx,
                                "section": current_section,
                                "extraction_engine": "deterministic_fallback",
                            },
                        )
                    )
                    break

    # If no specific patterns matched but valid text exists, synthesize a general guideline candidate
    if not candidates and extraction_res.text.strip():
        sample_directive = extraction_res.paragraphs[0] if extraction_res.paragraphs else extraction_res.text[:300]
        candidates.append(
            CandidateGuidelineCreate(
                name=f"{document_name}: Brand Standard Overview"[:200],
                rule_type=RuleType.TERMINOLOGY,
                severity=SeverityLevel.MEDIUM,
                description=f"General brand standard extracted from {document_name}.",
                directive=sample_directive[:4000],
                examples_approved=[],
                examples_prohibited=[],
                tags=["brand_overview", "general"],
                source_reference=f"{document_name} (Page 1)",
                source_metadata={
                    "document_name": document_name,
                    "document_version": document_version,
                    "file_hash_sha256": file_hash,
                    "page_number": 1,
                    "paragraph_index": 1,
                    "extraction_engine": "deterministic_fallback",
                },
            )
        )

    return candidates


# ==============================================================================
# Gemini Structured Extraction Prompt
# ==============================================================================

GEMINI_EXTRACTION_SYSTEM_PROMPT = """You are a Senior Brand Governance Intelligence Agent for BrandShield AI.
Your task is to analyze an official corporate brand guidelines manual and extract discrete, actionable compliance rules.

Categorize each extracted rule into one of the following exact rule_type values:
- terminology: naming rules, approved and prohibited terms, casing, spelling, capitalization.
- tone_of_voice: voice attributes, personality traits, style requirements.
- messaging_pillar: core value propositions, strategic brand pillars, mission commitments.
- prohibited_claims: forbidden marketing claims, unsubstantiated guarantees, compliance restrictions.
- factual_accuracy: approved company facts, statistics, historical milestones, corporate metrics.

For each rule, provide a JSON object with:
- "name": Concise, descriptive title (e.g., "BrandShield Capitalization Standard").
- "rule_type": One of [terminology, tone_of_voice, messaging_pillar, prohibited_claims, factual_accuracy].
- "severity": One of [low, medium, high, critical].
- "description": Contextual explanation of the rationale and importance.
- "directive": Normative instruction stating clearly what must or must not be done ("Always...", "Never...", "Must...").
- "examples_approved": Array of compliant phrases or strings.
- "examples_prohibited": Array of non-compliant phrases or strings.
- "tags": Array of keyword strings for indexing.
- "page_number": Integer page number where the rule was identified.
- "quote": Exact quote from the document text demonstrating the rule.

Respond ONLY with a valid JSON array of rule objects. Do not include markdown code fences or conversational text."""


async def _extract_with_gemini(
    ai_provider: AIProvider,
    document_text: str,
    document_name: str,
    document_version: Optional[str],
    file_hash: str,
) -> Optional[List[CandidateGuidelineCreate]]:
    """Attempt structured extraction using Google Gemini API."""
    try:
        prompt_content = f"Document: {document_name}\n\nDocument Text:\n{document_text[:20000]}"
        contents = [
            {"role": "user", "parts": [{"text": f"{GEMINI_EXTRACTION_SYSTEM_PROMPT}\n\n{prompt_content}"}]}
        ]

        response = await ai_provider.client.generate_content(
            contents=contents,
            generation_config={"temperature": 0.1, "response_mime_type": "application/json"},
        )

        candidates_out = response.get("candidates", [])
        if not candidates_out:
            return None

        content_part = candidates_out[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if not content_part:
            return None

        clean_json = content_part.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()

        parsed = json.loads(clean_json)
        if not isinstance(parsed, list):
            return None

        results: List[CandidateGuidelineCreate] = []
        for item in parsed:
            rule_type_raw = str(item.get("rule_type", "terminology")).strip().lower()
            try:
                rule_type = RuleType(rule_type_raw)
            except ValueError:
                rule_type = RuleType.TERMINOLOGY

            sev_raw = str(item.get("severity", "medium")).strip().lower()
            try:
                severity = SeverityLevel(sev_raw)
            except ValueError:
                severity = SeverityLevel.MEDIUM

            page_num = item.get("page_number", 1)
            quote = item.get("quote", "")

            name = str(item.get("name", "Extracted Guideline"))[:200].strip()
            directive = str(item.get("directive", item.get("description", "")))[:4000].strip()
            description = str(item.get("description", directive))[:2000].strip()

            if len(name) < 2 or len(directive) < 5:
                continue

            results.append(
                CandidateGuidelineCreate(
                    name=name,
                    rule_type=rule_type,
                    severity=severity,
                    description=description,
                    directive=directive,
                    examples_approved=item.get("examples_approved", []) or [],
                    examples_prohibited=item.get("examples_prohibited", []) or [],
                    tags=item.get("tags", []) or ["ai_extracted"],
                    source_reference=f"{document_name} (Page {page_num})",
                    source_metadata={
                        "document_name": document_name,
                        "document_version": document_version,
                        "file_hash_sha256": file_hash,
                        "page_number": page_num,
                        "extraction_engine": "gemini",
                        "source_quote": quote,
                    },
                )
            )

        return results if results else None

    except Exception as e:
        logger.warning("Gemini AI extraction encountered an error; falling back to deterministic parser: %s", e)
        return None


# ==============================================================================
# Public Extraction Orchestrator
# ==============================================================================

async def extract_candidate_guidelines_from_document(
    file_path: Path,
    mime_type: MimeType,
    document_name: str,
    document_version: Optional[str] = None,
    file_hash: str = "",
    ai_provider: Optional[AIProvider] = None,
) -> List[CandidateGuidelineCreate]:
    """Orchestrate guideline extraction from PDF or DOCX brand manuals.
    
    Workflow:
    1. Pure-Python text extraction with encrypted/scanned PDF safety.
    2. Attempt Gemini structured extraction if AIProvider is available.
    3. Safe deterministic rule-based extraction fallback on AI unavailability or error.
    4. Attachment of exact document lineage (document_name, version, hash, page/paragraph).
    """
    # 1. Text & Structural Extraction
    extraction_res = extract_document_text(file_path, mime_type)

    if extraction_res.is_encrypted:
        raise DocumentExtractionError(
            "Password-protected or encrypted PDF cannot be parsed. Please provide an unencrypted document.",
            error_code="ENCRYPTED_DOCUMENT",
        )

    if extraction_res.is_scanned or extraction_res.requires_ocr:
        raise DocumentExtractionError(
            "Document appears to be scanned or contains insufficient digital text. "
            "Searchable digital PDF or DOCX is required. OCR is not currently supported.",
            error_code="OCR_REQUIRED",
        )

    if not extraction_res.text or len(extraction_res.text.strip()) < 20:
        raise DocumentExtractionError(
            "Document does not contain sufficient text for brand guideline extraction.",
            error_code="INSUFFICIENT_TEXT",
        )

    # 2. AI Extraction when configured
    candidates: Optional[List[CandidateGuidelineCreate]] = None
    if ai_provider and ai_provider.is_available:
        candidates = await _extract_with_gemini(
            ai_provider=ai_provider,
            document_text=extraction_res.text,
            document_name=document_name,
            document_version=document_version,
            file_hash=file_hash,
        )

    # 3. Deterministic Fallback if AI not available or failed
    if not candidates:
        logger.info(
            "Executing deterministic guideline extraction for '%s' (hash: %s...)",
            document_name,
            file_hash[:8] if file_hash else "none",
        )
        candidates = _extract_deterministic_rules(
            extraction_res=extraction_res,
            document_name=document_name,
            document_version=document_version,
            file_hash=file_hash,
        )

    return candidates
