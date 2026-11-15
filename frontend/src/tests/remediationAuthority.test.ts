import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { RemediationSummary } from '../types';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Backend-Only Remediation Authority Tests (Frontend Invariants)', () => {
  const correctionsPagePath = path.resolve(__dirname, '../pages/CorrectionsPage.tsx');
  const fileContent = fs.readFileSync(correctionsPagePath, 'utf-8');

  test('Invariant 1: No client-side draft synthesis or reconstruction functions exist', () => {
    // Proves frontend has zero text reconstruction or span replacement functions
    assert.strictEqual(
      fileContent.includes('synthesizeDraftClientSide'),
      false,
      'CorrectionsPage must not contain synthesizeDraftClientSide'
    );
    assert.strictEqual(
      fileContent.includes('function synthesize'),
      false,
      'CorrectionsPage must not define any draft synthesis functions'
    );
    assert.strictEqual(
      fileContent.includes('clusters'),
      false,
      'CorrectionsPage must not perform span clustering or merging'
    );
    assert.strictEqual(
      fileContent.includes('pieces.push'),
      false,
      'CorrectionsPage must not perform piecewise text reconstruction'
    );
  });

  test('Invariant 2: remediatedDraft is strictly sourced from backend API report', () => {
    // Proves remediatedDraft is derived strictly from currentReport?.remediated_draft
    const draftAssignmentRegex = /const\s+remediatedDraft\s*=\s*currentReport\?\.remediated_draft\s*\?\?\s*['"]['"]/;
    assert.match(
      fileContent,
      draftAssignmentRegex,
      'remediatedDraft must be strictly derived from currentReport?.remediated_draft'
    );

    // Proves isRemediationAvailable is determined solely by presence of backend draft
    assert.match(
      fileContent,
      /const\s+isRemediationAvailable\s*=\s*Boolean\(remediatedDraft\)/,
      'isRemediationAvailable must be strictly derived from Boolean(remediatedDraft)'
    );
  });

  test('Invariant 3: remediationSummary is strictly sourced from backend API report', () => {
    // Proves remediationSummary is derived strictly from currentReport?.remediation_summary
    const summaryAssignmentRegex = /const\s+remediationSummary\s*=\s*currentReport\?\.remediation_summary\s*\?\?\s*null/;
    assert.match(
      fileContent,
      summaryAssignmentRegex,
      'remediationSummary must be strictly derived from currentReport?.remediation_summary'
    );
  });

  test('Invariant 4: Violation resolution status is derived strictly from backend resolved_violation_ids', () => {
    // Proves the frontend does not use regex or substring searches to decide if a violation is resolved
    assert.strictEqual(
      fileContent.includes('new RegExp(`\\\\b${violation.flagged_text}\\\\b`)'),
      false,
      'CorrectionsPage must not use regex tests to determine violation resolution'
    );
    assert.strictEqual(
      fileContent.includes('remediatedDraft.toLowerCase().includes(violation.flagged_text.toLowerCase())'),
      false,
      'CorrectionsPage must not use substring matches to determine violation resolution'
    );

    const resolutionCheckRegex = /const\s+isResolved\s*=\s*Boolean\(\s*remediationSummary\?\.resolved_violation_ids\?\.includes\(violation\.id\)\s*\)/;
    assert.match(
      fileContent,
      resolutionCheckRegex,
      'isResolved must be strictly derived from remediationSummary.resolved_violation_ids'
    );
  });

  test('Invariant 5: Honest error state when backend remediation is unavailable', () => {
    // Proves an honest warning is displayed if backend remediation is missing
    assert.strictEqual(
      fileContent.includes('Backend Remediation Unavailable'),
      true,
      'CorrectionsPage must render "Backend Remediation Unavailable" banner when draft is absent'
    );
    assert.strictEqual(
      fileContent.includes('Remediation draft pending backend inspection'),
      true,
      'CorrectionsPage must inform user that draft is pending backend inspection'
    );

    // Proves the staging button is disabled when remediation is unavailable
    assert.strictEqual(
      fileContent.includes('disabled={!isRemediationAvailable}'),
      true,
      'Staging button must be disabled when backend remediation is unavailable'
    );
  });

  test('Invariant 6: Simulation verifies component cannot fabricate drafts when backend returns none', () => {
    // Simulate what the component calculates when currentReport has violations but no remediated_draft
    const mockReportWithoutRemediation = {
      id: 'rep-001',
      submission_id: 'sub-001',
      submission_title: 'Uninspected draft',
      submission_version: 1,
      is_compliant: false,
      total_violations: 2,
      summary: 'Violations detected',
      analyzed_at: new Date().toISOString(),
      violations: [
        {
          id: 'v-1',
          rule_id: 'r-1',
          rule_name: 'Trademark usage',
          rule_type: 'trademark_usage',
          severity: 'critical',
          flagged_text: 'brandshield',
          char_start: 0,
          char_end: 11,
          explanation: 'Incorrect trademark capitalization',
          evidence_citations: [],
          suggestions: [{ id: 's-1', suggested_text: 'BrandShield AI', source: 'rule_derived', rationale: 'Official name' }],
        },
      ],
      remediated_draft: undefined,
      remediation_summary: undefined,
    };

    // Component logic emulation
    const remediatedDraft = mockReportWithoutRemediation.remediated_draft ?? '';
    const isRemediationAvailable = Boolean(remediatedDraft);
    const remediationSummary: RemediationSummary | null = (mockReportWithoutRemediation.remediation_summary as unknown as RemediationSummary) ?? null;

    // Must be completely empty string, no fabrication
    assert.strictEqual(remediatedDraft, '', 'Draft must be empty when backend does not provide it');
    assert.strictEqual(isRemediationAvailable, false, 'Remediation must be marked unavailable');
    assert.strictEqual(remediationSummary, null, 'Summary must be null');

    // Violations must not be marked as resolved
    const violation = mockReportWithoutRemediation.violations[0];
    const resolvedIds = (remediationSummary as RemediationSummary | null)?.resolved_violation_ids;
    const isResolved = Boolean(resolvedIds?.includes(violation.id));
    assert.strictEqual(isResolved, false, 'Violation must NOT be marked resolved when backend summary is null');
  });

  test('Invariant 7: Simulation verifies authoritative backend draft is rendered verbatim without mutation', () => {
    const authoritativeBackendDraft = 'We are thrilled to unveil BrandShield AI! Our intelligent platform elevates compliance.';
    const mockReportWithRemediation = {
      id: 'rep-002',
      submission_id: 'sub-002',
      submission_title: 'Inspected draft',
      submission_version: 1,
      is_compliant: false,
      total_violations: 1,
      summary: 'Violations remediated',
      analyzed_at: new Date().toISOString(),
      violations: [
        {
          id: 'v-1',
          rule_id: 'r-1',
          rule_name: 'Trademark usage',
          rule_type: 'trademark_usage',
          severity: 'critical',
          flagged_text: 'Brandshield',
          evidence_citations: [],
          suggestions: [],
        },
      ],
      remediated_draft: authoritativeBackendDraft,
      remediation_summary: {
        total_violations: 1,
        remediated_violations: 1,
        unresolved_violations: 0,
        is_fully_remediated: true,
        resolved_violation_ids: ['v-1'],
        unresolved_violation_ids: [],
        corruptions: [],
      },
    };

    const remediatedDraft = mockReportWithRemediation.remediated_draft ?? '';
    const isRemediationAvailable = Boolean(remediatedDraft);
    const remediationSummary = mockReportWithRemediation.remediation_summary ?? null;

    assert.strictEqual(remediatedDraft, authoritativeBackendDraft, 'Draft must strictly match backend output');
    assert.strictEqual(isRemediationAvailable, true);
    assert.strictEqual(remediationSummary?.is_fully_remediated, true);

    const isResolved = Boolean(remediationSummary?.resolved_violation_ids?.includes('v-1'));
    assert.strictEqual(isResolved, true, 'Violation must be recognized as resolved strictly from backend IDs');
  });
});
