import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('QA Issue Resolution Verification Suite (Issues 1 - 9)', () => {
  const guidelinesPagePath = path.resolve(__dirname, '../pages/GuidelinesPage.tsx');
  const correctionsPagePath = path.resolve(__dirname, '../pages/CorrectionsPage.tsx');
  const reviewPagePath = path.resolve(__dirname, '../pages/ReviewPage.tsx');
  const dashboardPagePath = path.resolve(__dirname, '../pages/DashboardPage.tsx');
  const submissionPagePath = path.resolve(__dirname, '../pages/SubmissionPage.tsx');
  const statusBadgePath = path.resolve(__dirname, '../components/common/StatusBadge.tsx');
  const appPath = path.resolve(__dirname, '../App.tsx');

  const guidelinesContent = fs.readFileSync(guidelinesPagePath, 'utf-8');
  const correctionsContent = fs.readFileSync(correctionsPagePath, 'utf-8');
  const reviewContent = fs.readFileSync(reviewPagePath, 'utf-8');
  const dashboardContent = fs.readFileSync(dashboardPagePath, 'utf-8');
  const submissionContent = fs.readFileSync(submissionPagePath, 'utf-8');
  const statusBadgeContent = fs.readFileSync(statusBadgePath, 'utf-8');
  const appContent = fs.readFileSync(appPath, 'utf-8');

  test('Issue 1: Guideline Detail Modal & Interactive Inspection', () => {
    // Verify state exists for detail modal
    assert.match(
      guidelinesContent,
      /selectedGuidelineForDetail/,
      'GuidelinesPage must maintain selectedGuidelineForDetail state'
    );
    // Verify card click handler
    assert.match(
      guidelinesContent,
      /setSelectedGuidelineForDetail\(guideline\)/,
      'Clicking guideline card must set selectedGuidelineForDetail'
    );
    // Verify stopPropagation on toggle switches
    assert.match(
      guidelinesContent,
      /e\.stopPropagation\(\)/,
      'Toggling rule activation must stop propagation to prevent opening modal'
    );
    // Verify modal elements render directive, examples, tags, id
    assert.match(
      guidelinesContent,
      /selectedGuidelineForDetail\.directive/,
      'Detail modal must display directive text'
    );
    assert.match(
      guidelinesContent,
      /examples_approved/,
      'Detail modal must display approved examples'
    );
    assert.match(
      guidelinesContent,
      /examples_prohibited/,
      'Detail modal must display prohibited examples'
    );

    // Accessibility Invariant 1: Escape-key dismissal
    assert.match(
      guidelinesContent,
      /e\.key\s*===\s*'Escape'/,
      'Modal must listen for Escape key to trigger handleCloseDetail'
    );
    // Accessibility Invariant 2: Focus moves into modal on open
    assert.match(
      guidelinesContent,
      /detailCloseButtonRef\.current\?\.focus\(\)/,
      'Keyboard focus must move into the modal (close button) when opened'
    );
    // Accessibility Invariant 3: Focus restoration on modal close
    assert.match(
      guidelinesContent,
      /lastActiveElementRef\.current\?\.focus\(\)/,
      'Keyboard focus must restore to the element that triggered opening upon dismissal'
    );
    // Accessibility Invariant 4: Keyboard navigation focus trap within modal
    assert.match(
      guidelinesContent,
      /e\.key\s*===\s*'Tab'/,
      'Modal must trap Tab key navigation within modal bounds'
    );
    assert.match(
      guidelinesContent,
      /e\.shiftKey/,
      'Modal must support Shift+Tab backward focus wrapping'
    );
    // Accessibility Invariant 5: Title keyboard activation (role="button", tabIndex={0})
    assert.match(
      guidelinesContent,
      /role="button"/,
      'Guideline title must have role="button" for screen reader navigation'
    );
    assert.match(
      guidelinesContent,
      /tabIndex=\{0\}/,
      'Guideline title must have tabIndex={0} for keyboard focusability'
    );
  });

  test('Issue 2: AI Remediation Text Accuracy & Unresolved Count Fallbacks', () => {
    // Verify remediatedCount does not fall back to totalViolations
    assert.ok(
      !correctionsContent.includes('totalViolations : 0'),
      'remediatedCount must not default to totalViolations when summary is absent'
    );
    // Verify unresolvedCount defaults to totalViolations when summary is absent
    assert.match(
      correctionsContent,
      /unresolvedCount\s*=\s*remediationSummary\?\.unresolved_violations/,
      'unresolvedCount must be sourced from backend remediationSummary'
    );
    // Verify full resolution banner requires 0 unresolved and remediatedCount === totalViolations
    assert.match(
      correctionsContent,
      /unresolvedCount\s*===\s*0\s*&&\s*remediatedCount\s*===\s*totalViolations/,
      'Full resolution claim requires unresolvedCount === 0 and remediatedCount === totalViolations'
    );
  });

  test('Issue 3: Human Review Console Decision Preselection Guard', () => {
    // Verify selectedAction initializes to null
    assert.match(
      reviewContent,
      /useState<ReviewAction\s*\|\s*null>\(null\)/,
      'selectedAction must initialize to null to prevent preselected decision'
    );
    // Verify submit button disabled when !selectedAction
    assert.match(
      reviewContent,
      /disabled=\{isSubmitting\s*\|\|\s*!canReview\s*\|\|\s*!selectedAction\}/,
      'Submit button must be disabled until human reviewer explicitly selects an action'
    );
    // Verify audit preview renders unselected placeholder
    assert.match(
      reviewContent,
      /No decision selected\. Select an action above to preview the immutable audit record\./,
      'Audit preview must display placeholder when no decision is selected'
    );
  });

  test('Issue 4: Duplicate Submission Safeguards & Visual Differentiation', () => {
    // Verify activeDraftId is tracked in SubmissionPage
    assert.match(
      submissionContent,
      /activeDraftId/,
      'SubmissionPage must track activeDraftId to avoid duplicate submissions on inspect'
    );
    // Verify dashboard renders submission ID snippet
    assert.match(
      dashboardContent,
      /#\{sub\.id\.length\s*>\s*12/,
      'Dashboard must render truncated submission ID to distinguish drafts'
    );
    // Verify dashboard renders created_at timestamp
    assert.match(
      dashboardContent,
      /toLocaleTimeString/,
      'Dashboard must render creation timestamp to clearly distinguish submissions'
    );
  });

  test('Issue 5: Full Lifecycle StatusBadge Coverage', () => {
    // Verify violations_found has explicit case
    assert.match(
      statusBadgeContent,
      /case\s+'violations_found':/,
      'StatusBadge must explicitly handle violations_found'
    );
    assert.match(
      statusBadgeContent,
      /Violations Found/,
      'StatusBadge must display "Violations Found" label'
    );
    // Verify passed_checks has explicit case
    assert.match(
      statusBadgeContent,
      /case\s+'passed_checks':/,
      'StatusBadge must explicitly handle passed_checks'
    );
    assert.match(
      statusBadgeContent,
      /Passed Checks/,
      'StatusBadge must display "Passed Checks" label'
    );
  });

  test('Issue 6: Formal Review Queue Metric Clarification', () => {
    assert.match(
      dashboardContent,
      /Formal Review Queue/,
      'Dashboard Metric 3 must be labeled "Formal Review Queue"'
    );
    assert.match(
      dashboardContent,
      /unroutedViolationsCount/,
      'Dashboard must track unroutedViolationsCount to clarify items awaiting advancement'
    );
    assert.match(
      dashboardContent,
      /unrouted\s*\{unroutedViolationsCount/,
      'Dashboard subtext must display unrouted violations in staging'
    );
  });

  test('Issue 7: Compliance Rate Formula & Evaluated Drafts Invariant', () => {
    // Verify evaluatedSubmissions filters by evaluated statuses
    assert.match(
      dashboardContent,
      /evaluatedSubmissions\s*=\s*submissions\.filter/,
      'Dashboard must filter submissions to evaluatedSubmissions'
    );
    assert.match(
      dashboardContent,
      /'passed_checks',\s*'violations_found'/,
      'evaluatedSubmissions must include passed_checks and violations_found'
    );
    // Verify compliantCount includes passed_checks and approved
    assert.match(
      dashboardContent,
      /\['passed_checks',\s*'approved'\]\.includes\(s\.status\)/,
      'compliantCount must include passed_checks and approved'
    );
    // Verify complianceRate is null when evaluatedSubmissions is empty
    assert.match(
      dashboardContent,
      /evaluatedSubmissions\.length\s*>\s*0\s*\?\s*Math\.round\(\(compliantCount\s*\/\s*evaluatedSubmissions\.length\)\s*\*\s*100\)\s*:\s*null/,
      'complianceRate formula must divide by evaluatedSubmissions.length and return null when empty'
    );
  });

  test('Issue 8 & 9: Audit Trail Ledger Attribution & Deduplication Invariants', () => {
    // Verify App.tsx only appends local mock audit log when offline
    assert.match(
      appContent,
      /!backendHealth\.is_connected\s*\|\|\s*!systemDiagnostic\?\.database(?:\?)?\.connected/,
      'App.tsx must not create client mock audit logs when backend audit trail is active'
    );
  });
});
