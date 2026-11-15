from datetime import datetime, timezone
from uuid import UUID, uuid4
import pytest
from pydantic import ValidationError

from app.schemas import (
    AuditEntry,
    ComplianceReport,
    CorrectionSuggestion,
    EvidenceCitation,
    GuidelineCreate,
    GuidelineResponse,
    GuidelineUpdate,
    ReviewAction,
    ReviewDecision,
    RuleType,
    SeverityLevel,
    SubmissionCreate,
    SubmissionResponse,
    SubmissionStatus,
    TargetChannel,
    ViolationDetail,
)


# ==============================================================================
# 1. Brand Guidelines Schema Tests
# ==============================================================================

def test_valid_guideline_create_and_response() -> None:
    """Test valid GuidelineCreate instantiation and transformation to GuidelineResponse."""
    payload = {
        "name": "CamelCase Brand Terminology",
        "rule_type": RuleType.TERMINOLOGY,
        "severity": SeverityLevel.HIGH,
        "description": "Ensure the brand name is always typed as BrandShield AI.",
        "directive": "Always write 'BrandShield AI'. Never write 'brandshield' or 'BrandShield'.",
        "examples_approved": ["BrandShield AI provides autonomous brand protection."],
        "examples_prohibited": ["Use brandshield for audits."],
        "tags": ["core", "naming"],
        "is_active": True,
    }
    create_dto = GuidelineCreate(**payload)
    assert create_dto.name == "CamelCase Brand Terminology"
    assert create_dto.rule_type == RuleType.TERMINOLOGY
    assert create_dto.severity == SeverityLevel.HIGH

    # Convert to response representation
    response_dto = GuidelineResponse(
        id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        **create_dto.model_dump(),
    )
    assert isinstance(response_dto.id, UUID)
    assert isinstance(response_dto.created_at, datetime)
    assert response_dto.name == "CamelCase Brand Terminology"


def test_guideline_rejects_empty_and_whitespace_fields() -> None:
    """Test that GuidelineCreate rejects empty or whitespace-only strings."""
    with pytest.raises(ValidationError) as exc_info:
        GuidelineCreate(
            name="   ",
            rule_type=RuleType.TERMINOLOGY,
            description="Valid description text here",
            directive="Valid directive text here",
        )
    assert "cannot be empty or contain only whitespace" in str(exc_info.value)


def test_guideline_enum_validation() -> None:
    """Test that invalid rule types and severity levels are rejected."""
    with pytest.raises(ValidationError):
        GuidelineCreate(
            name="Valid Name",
            rule_type="non_existent_rule_type",  # Invalid enum
            description="Valid description here",
            directive="Valid directive text here",
        )

    with pytest.raises(ValidationError):
        GuidelineCreate(
            name="Valid Name",
            rule_type=RuleType.TERMINOLOGY,
            severity="extreme_critical",  # Invalid enum
            description="Valid description here",
            directive="Valid directive text here",
        )


# ==============================================================================
# 2. Content Submission Schema Tests
# ==============================================================================

def test_valid_submission_create_and_response() -> None:
    """Test valid SubmissionCreate and round-trip to SubmissionResponse."""
    create_dto = SubmissionCreate(
        title="Q4 Product Launch Announcement",
        content="Excited to announce our newest AI security capability for enterprises.",
        target_channel=TargetChannel.LINKEDIN,
        target_audience="Security & Compliance Directors",
        author_id="user_vkh_101",
    )
    assert create_dto.title == "Q4 Product Launch Announcement"
    assert create_dto.target_channel == TargetChannel.LINKEDIN

    response_dto = SubmissionResponse(
        id=uuid4(),
        status=SubmissionStatus.DRAFT,
        version=1,
        **create_dto.model_dump(),
    )
    assert response_dto.status == SubmissionStatus.DRAFT
    assert response_dto.version == 1
    assert response_dto.latest_review_id is None


def test_submission_rejects_empty_content() -> None:
    """Test that submission content cannot be empty or only spaces."""
    with pytest.raises(ValidationError) as exc_info:
        SubmissionCreate(
            title="Valid Title",
            content="   \n   ",
            target_channel=TargetChannel.TWITTER_X,
        )
    assert "cannot be empty or whitespace only" in str(exc_info.value)


def test_submission_approval_invariant_enforced() -> None:
    """Test that a submission cannot have APPROVED status without a latest_review_id."""
    with pytest.raises(ValidationError) as exc_info:
        SubmissionResponse(
            title="Approved Announcement",
            content="Compliant content ready for release.",
            target_channel=TargetChannel.LINKEDIN,
            status=SubmissionStatus.APPROVED,
            latest_review_id=None,  # Forbidden: No review reference
        )
    assert "without a corresponding human review record" in str(exc_info.value)


# ==============================================================================
# 3. Rule Violations & Evidence Citations Tests
# ==============================================================================

def test_evidence_citation_and_violation_detail() -> None:
    """Test that ViolationDetail requires valid EvidenceCitation."""
    rule_id = uuid4()
    evidence = EvidenceCitation(
        rule_id=rule_id,
        rule_name="Forbidden Guarantee Claims",
        rule_type=RuleType.FORBIDDEN_CLAIM,
        source_clause="Never state '100% immune to all security vulnerabilities'.",
        document_name="Official Brand & Regulatory Guide v2",
        confidence_score=0.98,
    )
    assert evidence.confidence_score == 0.98

    suggestion = CorrectionSuggestion(
        suggested_text="Offers defense-in-depth protection for enterprise brand assets.",
        rationale="Eliminates absolute guarantee while emphasizing defense capabilities.",
    )
    assert suggestion.source == "ai_generated"

    violation = ViolationDetail(
        rule_id=rule_id,
        rule_name="Forbidden Guarantee Claims",
        rule_type=RuleType.FORBIDDEN_CLAIM,
        severity=SeverityLevel.CRITICAL,
        flagged_text="Guarantees 100% immunity from brand misuse",
        char_start=15,
        char_end=58,
        explanation="Claims of 100% immunity violate truth-in-advertising guidelines.",
        evidence=evidence,
        ai_suggestions=[suggestion],
    )
    assert violation.severity == SeverityLevel.CRITICAL
    assert violation.evidence.rule_name == "Forbidden Guarantee Claims"
    assert len(violation.ai_suggestions) == 1
    assert violation.ai_suggestions[0].source == "ai_generated"


def test_violation_requires_evidence_citation() -> None:
    """Test that a ViolationDetail cannot be constructed without an EvidenceCitation."""
    with pytest.raises(ValidationError):
        ViolationDetail(
            rule_id=uuid4(),
            rule_name="Tone Mismatch",
            rule_type=RuleType.TONE_OF_VOICE,
            severity=SeverityLevel.MEDIUM,
            flagged_text="Hey guys, look at this cool thing",
            explanation="Too informal for enterprise communications",
            evidence=None,  # Missing mandatory evidence
        )


def test_evidence_rejects_empty_clause_and_out_of_bounds_confidence() -> None:
    """Test that EvidenceCitation rejects empty source clause and invalid confidence."""
    with pytest.raises(ValidationError):
        EvidenceCitation(
            rule_id=uuid4(),
            rule_name="Rule Name",
            rule_type=RuleType.TERMINOLOGY,
            source_clause="   ",  # Invalid
            confidence_score=0.9,
        )

    with pytest.raises(ValidationError):
        EvidenceCitation(
            rule_id=uuid4(),
            rule_name="Rule Name",
            rule_type=RuleType.TERMINOLOGY,
            source_clause="Valid source clause",
            confidence_score=1.5,  # Out of range [0.0, 1.0]
        )


def test_compliance_report_synthesis() -> None:
    """Test full ComplianceReport validation and aggregation."""
    sub_id = uuid4()
    report = ComplianceReport(
        submission_id=sub_id,
        total_violations=0,
        violations=[],
        is_compliant=True,
        summary="Content conforms to all indexed brand guidelines.",
    )
    assert report.is_compliant is True
    assert report.total_violations == 0


# ==============================================================================
# 4. Human Review & Audit Governance Tests
# ==============================================================================

def test_human_approval_decision_valid() -> None:
    """Test that an authorized human reviewer can make a valid approval decision."""
    sub_id = uuid4()
    review = ReviewDecision(
        submission_id=sub_id,
        submission_version=1,
        reviewer_id="human_reviewer_44",
        reviewer_name="Sarah Jenkins (Brand Director)",
        action=ReviewAction.APPROVE,
        feedback="Approved for LinkedIn publication.",
    )
    assert review.action == ReviewAction.APPROVE
    assert review.reviewer_id == "human_reviewer_44"


def test_review_decision_rejects_automated_or_ai_reviewer() -> None:
    """Test that automated bots, AI, and system accounts are rejected as reviewers."""
    sub_id = uuid4()
    disallowed_identities = ["ai", "system", "bot", "auto_approver", "agent"]
    for bad_id in disallowed_identities:
        with pytest.raises(ValidationError) as exc_info:
            ReviewDecision(
                submission_id=sub_id,
                reviewer_id=bad_id,
                reviewer_name=f"{bad_id}_name",
                action=ReviewAction.APPROVE,
            )
        assert "not an authorized human reviewer" in str(exc_info.value)


def test_edit_and_approve_requires_edited_content() -> None:
    """Test that EDIT_AND_APPROVE action strictly requires non-empty edited_content."""
    sub_id = uuid4()
    with pytest.raises(ValidationError) as exc_info:
        ReviewDecision(
            submission_id=sub_id,
            reviewer_id="human_editor_01",
            reviewer_name="Editor John",
            action=ReviewAction.EDIT_AND_APPROVE,
            edited_content="   ",  # Missing actual replacement copy
        )
    assert "edited_content must be provided and non-empty" in str(exc_info.value)

    # Valid edit_and_approve
    valid_review = ReviewDecision(
        submission_id=sub_id,
        reviewer_id="human_editor_01",
        reviewer_name="Editor John",
        action=ReviewAction.EDIT_AND_APPROVE,
        edited_content="Corrected BrandShield AI copy.",
    )
    assert valid_review.edited_content == "Corrected BrandShield AI copy."


def test_reject_and_request_revision_require_feedback() -> None:
    """Test that REJECT and REQUEST_REVISION strictly require feedback."""
    sub_id = uuid4()
    with pytest.raises(ValidationError) as exc_info:
        ReviewDecision(
            submission_id=sub_id,
            reviewer_id="human_reviewer_02",
            reviewer_name="Reviewer Alex",
            action=ReviewAction.REJECT,
            feedback=None,  # Missing mandatory rejection feedback
        )
    assert "feedback is mandatory when action is 'reject'" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        ReviewDecision(
            submission_id=sub_id,
            reviewer_id="human_reviewer_02",
            reviewer_name="Reviewer Alex",
            action=ReviewAction.REQUEST_REVISION,
            feedback="   ",  # Blank
        )
    assert "feedback is mandatory when action is 'request_revision'" in str(exc_info.value)


def test_audit_entry_enforces_human_only_approval_invariant() -> None:
    """Test that AuditEntry forbids non-human actors from approving content."""
    sub_id = uuid4()

    # Human approval succeeds
    human_audit = AuditEntry(
        submission_id=sub_id,
        previous_status=SubmissionStatus.UNDER_HUMAN_REVIEW,
        new_status=SubmissionStatus.APPROVED,
        action_type="human_approval",
        actor_id="user_lead_01",
        actor_type="human",
        actor_name="Brand Lead",
    )
    assert human_audit.new_status == SubmissionStatus.APPROVED

    # System or AI agent attempting approval fails
    with pytest.raises(ValidationError) as exc_info:
        AuditEntry(
            submission_id=sub_id,
            previous_status=SubmissionStatus.ANALYZING,
            new_status=SubmissionStatus.APPROVED,  # Forbidden transition for non-human
            action_type="auto_check",
            actor_id="ai_evaluator_agent",
            actor_type="ai_agent",
            actor_name="LangGraph Evaluator",
        )
    assert "Only human reviewers can approve content" in str(exc_info.value)


# ==============================================================================
# 5. Serialization and Deserialization (JSON Round-Trip)
# ==============================================================================

def test_json_round_trip_serialization() -> None:
    """Test that schemas serialize to JSON and deserialize back with complete fidelity."""
    rule_id = uuid4()
    sub_id = uuid4()

    original_violation = ViolationDetail(
        rule_id=rule_id,
        rule_name="Negative Competitor Mentions",
        rule_type=RuleType.COMPETITOR_REFERENCE,
        severity=SeverityLevel.HIGH,
        flagged_text="CompetitorX is horribly slow and outdated",
        char_start=0,
        char_end=41,
        explanation="Direct disparagement of named competitor violates fair advertising policy.",
        evidence=EvidenceCitation(
            rule_id=rule_id,
            rule_name="Negative Competitor Mentions",
            rule_type=RuleType.COMPETITOR_REFERENCE,
            source_clause="Do not reference named competitors pejoratively.",
            confidence_score=0.99,
        ),
        ai_suggestions=[
            CorrectionSuggestion(
                suggested_text="BrandShield AI delivers modern, high-speed compliance audits.",
                rationale="Focuses on our unique value proposition without referencing competitors.",
            )
        ],
    )

    # Dump to JSON string
    json_str = original_violation.model_dump_json()
    assert '"source":"ai_generated"' in json_str

    # Validate deserialization
    reconstructed = ViolationDetail.model_validate_json(json_str)
    assert reconstructed.id == original_violation.id
    assert reconstructed.evidence.rule_id == rule_id
    assert reconstructed.ai_suggestions[0].source == "ai_generated"
    assert reconstructed.severity == SeverityLevel.HIGH


def test_ai_suggestions_strictly_segregated_from_human_decisions() -> None:
    """Test that AI suggestions carry distinct provenance and cannot substitute human decision."""
    ai_suggestion = CorrectionSuggestion(
        suggested_text="Compliant brand text.",
        rationale="Matches approved guidelines.",
    )
    assert ai_suggestion.source == "ai_generated"

    # A human review decision is a completely separate structure with human identity
    human_decision = ReviewDecision(
        submission_id=uuid4(),
        reviewer_id="human_approver_1",
        reviewer_name="Elena Rostova",
        action=ReviewAction.APPROVE,
    )
    assert human_decision.action == ReviewAction.APPROVE
    assert not hasattr(human_decision, "source")
    assert human_decision.reviewer_id == "human_approver_1"
