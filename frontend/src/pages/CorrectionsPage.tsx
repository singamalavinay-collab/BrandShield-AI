import React, { useState } from 'react';
import {
  Sparkles,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  FileCheck,
  Scale,
  Copy,
  Check,
} from 'lucide-react';
import {
  NavigationTab,
  ContentSubmission,
  ComplianceReport,
} from '../types';
import { AlertBanner } from '../components/common/AlertBanner';
import { EmptyState } from '../components/common/EmptyState';

interface CorrectionsPageProps {
  onNavigate: (tab: NavigationTab) => void;
  submissions: ContentSubmission[];
  selectedSubmissionId: string;
  reports: Record<string, ComplianceReport>;
  onStageRemediatedContent: (content: string) => void;
  onAdvanceToReview?: (submissionId: string, stagedContent?: string) => Promise<void> | void;
}

export const CorrectionsPage: React.FC<CorrectionsPageProps> = ({
  onNavigate,
  submissions,
  selectedSubmissionId,
  reports,
  onStageRemediatedContent,
  onAdvanceToReview,
}) => {
  const currentSubmission = submissions.find((s) => s.id === selectedSubmissionId) || submissions[0];
  const currentReport = currentSubmission ? reports[currentSubmission.id] : null;

  const [copied, setCopied] = useState(false);

  // Authoritative remediated draft strictly derived from backend compliance engine
  const remediatedDraft = currentReport?.remediated_draft ?? '';
  const isRemediationAvailable = Boolean(remediatedDraft);
  const remediationSummary = currentReport?.remediation_summary ?? null;

  // 1. Zero submissions in workspace empty state
  if (!currentSubmission || submissions.length === 0) {
    return (
      <EmptyState
        icon={Sparkles}
        title="No Content Submissions Available"
        description="There are currently no submissions ready for AI correction and remediation. Create a draft in the Content Submission workspace to begin."
        actionText="Create Content Submission"
        onAction={() => onNavigate('submission')}
      />
    );
  }

  // 2. Submission exists and is fully compliant (no violations detected)
  if (!currentReport || currentReport.violations.length === 0) {
    return (
      <EmptyState
        icon={CheckCircle2}
        title="No Corrections Needed"
        description="The selected submission has no detected violations. No AI remediation suggestions are required."
        actionText="Go to Review & Approval"
        onAction={() => onNavigate('review')}
      />
    );
  }

  const totalViolations = currentReport.violations.length;
  const remediatedCount = remediationSummary?.remediated_violations ?? 0;
  const unresolvedCount =
    remediationSummary?.unresolved_violations ??
    (isRemediationAvailable ? Math.max(0, totalViolations - remediatedCount) : totalViolations);
  const isFullyRemediated =
    isRemediationAvailable &&
    Boolean(remediationSummary?.is_fully_remediated) &&
    unresolvedCount === 0 &&
    remediatedCount === totalViolations &&
    totalViolations > 0;

  const handleStageForReview = async () => {
    if (!isRemediationAvailable) return;
    onStageRemediatedContent(remediatedDraft);
    if (onAdvanceToReview) {
      await onAdvanceToReview(currentSubmission.id, remediatedDraft);
    } else {
      onNavigate('review');
    }
  };

  const handleCopy = () => {
    if (!isRemediationAvailable) return;
    navigator.clipboard.writeText(remediatedDraft);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      {/* Governance Invariant Alert */}
      <AlertBanner type="governance" title="Advisory AI Suggestions (Non-Binding)">
        AI correction suggestions are evidence-backed proposals designed to assist human editors. The AI is strictly
        prohibited from modifying live content or authorizing publication independently.
      </AlertBanner>

      {/* Safety Interlock Alert if any corruptions detected by backend engine */}
      {remediationSummary?.corruptions && remediationSummary.corruptions.length > 0 && (
        <AlertBanner type="warning" title="Text Corruption Safety Interlock Triggered">
          Automated remediation detected character span collisions or word concatenations ({remediationSummary.corruptions.length} issues). This draft is blocked from auto-certification and requires manual human review.
        </AlertBanner>
      )}

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">
            Evidence-Backed Correction Studio
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Review side-by-side AI remediation suggestions grounded in verified brand guidelines.
          </p>
        </div>

        <button
          onClick={handleStageForReview}
          disabled={!isRemediationAvailable}
          className={`inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-lg transition shadow-sm self-start sm:self-center ${
            isRemediationAvailable
              ? 'text-white bg-blue-600 hover:bg-blue-700 cursor-pointer'
              : 'text-slate-400 bg-slate-100 border border-slate-200 cursor-not-allowed opacity-75'
          }`}
          title={isRemediationAvailable ? 'Stage remediated draft for review' : 'Backend remediation draft unavailable'}
        >
          <FileCheck className="w-4 h-4" />
          Stage Remediated Draft for Human Review
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Side-by-Side Comparison of Proposed Full Draft */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Original Draft Box */}
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-subtle p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-3">
              <span className="text-xs font-bold uppercase tracking-wider text-rose-700 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-rose-500"></span>
                Original Draft with Violations ({totalViolations})
              </span>
              <span className="text-[11px] text-slate-400">Target: Twitter / X</span>
            </div>
            <div className="p-3.5 rounded-lg bg-rose-50/40 border border-rose-100 text-xs text-slate-800 leading-relaxed font-normal">
              {currentSubmission.content}
            </div>
          </div>
          <div className="mt-3 text-[11px] text-slate-500 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 text-rose-500" />
            <span>
              Contains {totalViolations} brand rule breach{totalViolations === 1 ? '' : 'es'} requiring human remediation.
            </span>
          </div>
        </div>

        {/* Remediated Draft Box */}
        <div className="bg-white rounded-xl border border-blue-200 shadow-subtle p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-3">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-700 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-teal-600" />
                Proposed Remediated Draft
              </span>
              <button
                onClick={handleCopy}
                disabled={!isRemediationAvailable}
                className={`text-[11px] font-medium flex items-center gap-1 transition ${
                  isRemediationAvailable
                    ? 'text-slate-600 hover:text-blue-600 cursor-pointer'
                    : 'text-slate-300 cursor-not-allowed'
                }`}
                title={isRemediationAvailable ? 'Copy draft to clipboard' : 'No draft available'}
              >
                {copied ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>

            {isRemediationAvailable ? (
              <div className="p-3.5 rounded-lg bg-emerald-50/40 border border-emerald-100 text-xs text-slate-900 leading-relaxed font-normal">
                {remediatedDraft}
              </div>
            ) : (
              <div className="p-4 rounded-lg bg-amber-50/50 border border-amber-200/80 text-xs text-slate-800 leading-relaxed font-normal">
                <div className="flex items-start gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p className="font-semibold text-slate-900">Backend Remediation Unavailable</p>
                    <p className="text-slate-600 text-[11px]">
                      The authoritative backend compliance engine has not returned a verified remediated draft for this submission. The frontend strictly respects backend authority and cannot independently synthesize or substitute unverified drafts in the browser.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="mt-3 text-[11px] flex items-center gap-1.5">
            {!isRemediationAvailable ? (
              <>
                <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                <span className="text-amber-700 font-medium">
                  Remediation draft pending backend inspection (0 of {totalViolations} remediated).
                </span>
              </>
            ) : isFullyRemediated ? (
              <>
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                <span className="text-emerald-700 font-medium">
                  All {remediatedCount} violations remediated according to brand directives.
                </span>
              </>
            ) : (
              <>
                <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                <span className="text-amber-700 font-medium">
                  {remediatedCount} of {totalViolations} violations remediated ({unresolvedCount} unresolved).
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Discrete Suggestion Cards */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-900">
            Remediation Breakdown by Violation
          </h3>
          <span className="text-xs text-slate-500">
            {remediatedCount} of {totalViolations} addressed in draft
          </span>
        </div>

        <div className="grid grid-cols-1 gap-4">
          {currentReport.violations.map((violation, idx) => {
            const suggestion = violation.suggestions[0];
            const citation = violation.evidence_citations[0];

            // Strict backend authority: resolved status is determined solely by backend remediation summary
            const isResolved = Boolean(
              remediationSummary?.resolved_violation_ids?.includes(violation.id)
            );

            return (
              <div
                key={violation.id}
                className="bg-white rounded-xl border border-slate-200/80 shadow-subtle p-5 space-y-3"
              >
                {/* Header */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="w-5 h-5 rounded-full bg-blue-100 text-blue-700 font-bold text-[10px] flex items-center justify-center">
                      {idx + 1}
                    </span>
                    <h4 className="text-xs font-bold text-slate-900">{violation.rule_name}</h4>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-[10px] uppercase font-semibold px-2 py-0.5 rounded border ${
                        suggestion?.source === 'rule_derived'
                          ? 'bg-blue-50 text-blue-700 border-blue-200'
                          : suggestion?.source === 'human_edited'
                          ? 'bg-amber-50 text-amber-700 border-amber-200'
                          : 'bg-purple-50 text-purple-700 border-purple-200'
                      }`}
                    >
                      Source:{' '}
                      {suggestion?.source === 'rule_derived'
                        ? 'Rule-Derived'
                        : suggestion?.source === 'human_edited'
                        ? 'Human-Edited'
                        : 'AI Generated'}
                    </span>
                    <span
                      className={`text-[10px] font-semibold px-2 py-0.5 rounded border inline-flex items-center gap-1 ${
                        isResolved
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                          : 'bg-amber-50 text-amber-700 border-amber-200'
                      }`}
                    >
                      {isResolved ? (
                        <>
                          <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                          Remediated in Draft
                        </>
                      ) : (
                        <>
                          <AlertTriangle className="w-3 h-3 text-amber-600" />
                          Manual Attention Required
                        </>
                      )}
                    </span>
                  </div>
                </div>

                {/* Diff Box */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                  <div className="p-3 rounded-lg bg-rose-50/60 border border-rose-100">
                    <span className="text-[10px] font-semibold text-rose-700 block mb-1">
                      Flagged Original Text:
                    </span>
                    <span className="line-through text-rose-900 font-mono">
                      "{violation.flagged_text}"
                    </span>
                  </div>

                  <div className="p-3 rounded-lg bg-emerald-50/60 border border-emerald-100">
                    <span className="text-[10px] font-semibold text-emerald-700 block mb-1">
                      Suggested Correction:
                    </span>
                    <span className="font-semibold text-emerald-900 font-mono">
                      "{suggestion ? suggestion.suggested_text : 'N/A'}"
                    </span>
                  </div>
                </div>

                {/* Rationale and Evidence grounding */}
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-1.5 text-xs">
                  <div className="text-[11px] text-slate-700">
                    <strong className="text-slate-900">AI Rationale:</strong>{' '}
                    {suggestion ? suggestion.rationale : 'Resolves rule deviation.'}
                  </div>
                  {citation && (
                    <div className="text-[11px] text-slate-500 flex items-center gap-1.5 pt-1 border-t border-slate-200/60">
                      <Scale className="w-3 h-3 text-teal-600 flex-shrink-0" />
                      <span className="truncate">
                        Grounding Citation: <em>{citation.document_name}</em> ("{citation.source_clause}")
                      </span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
