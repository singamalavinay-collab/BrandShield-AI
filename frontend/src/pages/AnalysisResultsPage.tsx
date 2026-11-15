import React, { useState } from 'react';
import {
  SearchCheck,
  AlertTriangle,
  CheckCircle2,
  FileText,
  ArrowRight,
  Scale,
  Sparkles,
} from 'lucide-react';
import {
  NavigationTab,
  ContentSubmission,
  ComplianceReport,
} from '../types';
import { StatusBadge } from '../components/common/StatusBadge';
import { EmptyState } from '../components/common/EmptyState';

interface AnalysisResultsPageProps {
  onNavigate: (tab: NavigationTab) => void;
  submissions: ContentSubmission[];
  selectedSubmissionId: string;
  onSelectSubmission: (id: string) => void;
  reports: Record<string, ComplianceReport>;
  onTriggerAnalysis?: (submissionId: string) => Promise<void> | void;
  isAnalyzing?: boolean;
  inspectionError?: string | null;
  dbOffline?: boolean;
  onAdvanceToReview?: (submissionId: string) => Promise<void> | void;
}

export const AnalysisResultsPage: React.FC<AnalysisResultsPageProps> = ({
  onNavigate,
  submissions,
  selectedSubmissionId,
  onSelectSubmission,
  reports,
  onTriggerAnalysis,
  isAnalyzing = false,
  inspectionError = null,
  dbOffline = false,
  onAdvanceToReview,
}) => {
  const currentSubmission = submissions.find((s) => s.id === selectedSubmissionId) || submissions[0];
  const currentReport = currentSubmission ? reports[currentSubmission.id] : null;

  const [activeViolationId, setActiveViolationId] = useState<string | null>(null);

  // Dynamic content highlighter matching violations against submission text
  const renderHighlightedContent = () => {
    if (!currentSubmission) return null;
    if (!currentReport || currentReport.violations.length === 0) {
      return <p>{currentSubmission.content}</p>;
    }

    const text = currentSubmission.content;
    const violations = currentReport.violations;

    interface Span {
      start: number;
      end: number;
      violation: (typeof violations)[0];
    }
    const spans: Span[] = [];

    violations.forEach((v) => {
      let start = v.char_start;
      let end = v.char_end;

      if (
        start === null ||
        start === undefined ||
        end === null ||
        end === undefined ||
        start < 0 ||
        end > text.length ||
        start >= end
      ) {
        if (v.flagged_text) {
          const idx = text.toLowerCase().indexOf(v.flagged_text.toLowerCase());
          if (idx !== -1) {
            start = idx;
            end = idx + v.flagged_text.length;
          }
        }
      }

      if (
        start !== null &&
        start !== undefined &&
        end !== null &&
        end !== undefined &&
        start >= 0 &&
        end <= text.length &&
        start < end
      ) {
        spans.push({ start, end, violation: v });
      }
    });

    if (spans.length === 0) {
      return <p>{text}</p>;
    }

    spans.sort((a, b) => a.start - b.start);

    const nonOverlapping: Span[] = [];
    let lastEnd = 0;
    for (const span of spans) {
      if (span.start >= lastEnd) {
        nonOverlapping.push(span);
        lastEnd = span.end;
      }
    }

    const elements: React.ReactNode[] = [];
    let currentIndex = 0;

    nonOverlapping.forEach((span, idx) => {
      if (span.start > currentIndex) {
        elements.push(
          <span key={`text-${currentIndex}`}>
            {text.slice(currentIndex, span.start)}
          </span>
        );
      }

      const isSelected = activeViolationId === span.violation.id;
      const severityColor =
        span.violation.severity === 'critical'
          ? 'bg-rose-100 text-rose-900 border-rose-300 hover:bg-rose-200'
          : span.violation.severity === 'high'
          ? 'bg-amber-100 text-amber-900 border-amber-300 hover:bg-amber-200'
          : 'bg-yellow-100 text-yellow-900 border-yellow-300 hover:bg-yellow-200';

      elements.push(
        <mark
          key={`mark-${idx}-${span.violation.id}`}
          onClick={() => setActiveViolationId(span.violation.id)}
          className={`font-medium px-1 py-0.5 rounded border cursor-pointer transition ${severityColor} ${
            isSelected ? 'ring-2 ring-blue-500 shadow-sm' : ''
          }`}
          title={`Violation: ${span.violation.rule_name} (${span.violation.severity})`}
        >
          {text.slice(span.start, span.end)}
        </mark>
      );

      currentIndex = span.end;
    });

    if (currentIndex < text.length) {
      elements.push(
        <span key={`text-end-${currentIndex}`}>
          {text.slice(currentIndex)}
        </span>
      );
    }

    return <p>{elements}</p>;
  };

  if (!currentSubmission) {
    return (
      <EmptyState
        icon={SearchCheck}
        title="No Content Submissions Available"
        description="There are currently no submissions ready for compliance inspection. Create a draft in the submission workspace to begin."
        actionText="Create Content Submission"
        onAction={() => onNavigate('submission')}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Controls: Submission Picker */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/80 shadow-subtle flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
            <FileText className="w-4 h-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Inspecting Submission
            </div>
            <h2 className="text-sm font-bold text-slate-900 truncate">{currentSubmission.title}</h2>
          </div>
        </div>

        {/* Submission Switcher Dropdown */}
        <div className="flex items-center gap-2">
          {currentSubmission.is_demo ? (
            <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
              Demo Preset
            </span>
          ) : (
            <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
              Live Database Draft
            </span>
          )}
          <span className="text-xs text-slate-500 font-medium">Switch Submission:</span>
          <select
            value={currentSubmission.id}
            onChange={(e) => onSelectSubmission(e.target.value)}
            className="text-xs py-1.5 px-3 rounded-lg border border-slate-200 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 font-medium"
          >
            {submissions.map((sub) => (
              <option key={sub.id} value={sub.id}>
                {sub.title} ({sub.status.replace(/_/g, ' ')})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Optional Inspection Error Alert */}
      {inspectionError && (
        <div className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-xs text-rose-800 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <h4 className="font-bold text-rose-900 text-sm mb-0.5">Compliance Inspection Notice</h4>
            <p className="leading-relaxed">{inspectionError}</p>
          </div>
          {onTriggerAnalysis && currentSubmission && !dbOffline && (
            <button
              onClick={() => onTriggerAnalysis(currentSubmission.id)}
              disabled={isAnalyzing}
              className="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white rounded-lg text-xs font-semibold transition flex-shrink-0"
            >
              Retry Inspection
            </button>
          )}
        </div>
      )}

      {/* Compliance Overview Banner */}
      {currentReport ? (
        <div
          className={`p-5 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-4 ${
            currentReport.is_compliant
              ? 'bg-emerald-50/70 border-emerald-200 text-emerald-950'
              : 'bg-rose-50/70 border-rose-200 text-rose-950'
          }`}
        >
          <div className="flex items-start gap-3.5">
            <div
              className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
                currentReport.is_compliant
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'bg-rose-600 text-white shadow-sm'
              }`}
            >
              {currentReport.is_compliant ? (
                <CheckCircle2 className="w-5 h-5" />
              ) : (
                <AlertTriangle className="w-5 h-5" />
              )}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold tracking-tight">
                  {currentReport.is_compliant
                    ? 'Compliance Verified — No Violations Detected'
                    : `Non-Compliant — ${currentReport.total_violations} Rule Violations Flagged`}
                </h3>
                <StatusBadge status={currentSubmission.status} />
              </div>
              <p className="text-xs opacity-90 mt-1 max-w-2xl leading-relaxed">
                {currentReport.summary}
              </p>
            </div>
          </div>

          {currentReport.is_compliant ? (
            <button
              onClick={() => onAdvanceToReview ? onAdvanceToReview(currentSubmission.id) : onNavigate('review')}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg transition shadow-sm self-start sm:self-center flex-shrink-0"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              Route to Human Review Queue
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          ) : (
            <div className="flex items-center gap-2 flex-wrap self-start sm:self-center flex-shrink-0">
              <button
                onClick={() => onNavigate('corrections')}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition shadow-sm"
              >
                <Sparkles className="w-3.5 h-3.5 text-blue-200" />
                Inspect AI Suggestions
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
              {onAdvanceToReview && currentSubmission.status !== 'under_human_review' && (
                <button
                  onClick={() => onAdvanceToReview(currentSubmission.id)}
                  className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg transition shadow-sm"
                  title="Route directly to review queue without pre-applying corrections"
                >
                  Route to Review
                </button>
              )}
            </div>
          )}
        </div>
      ) : dbOffline ? (
        <div className="p-5 rounded-xl border border-amber-200 bg-amber-50/80 text-xs text-amber-900 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-bold text-amber-950 text-sm mb-1">
                Database Service Offline
              </div>
              <p className="text-amber-800 max-w-xl leading-relaxed">
                Automated compliance inspection cannot run because the database backend is unreachable. 
                Brand guideline retrieval, rule evaluation, and audit logging require an active database.
              </p>
            </div>
          </div>
          <button
            onClick={() => onNavigate('dashboard')}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-semibold transition self-start sm:self-center flex-shrink-0"
          >
            Check System Health
          </button>
        </div>
      ) : (
        <div className="p-5 rounded-xl border border-slate-200 bg-white text-xs text-slate-600 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="font-bold text-slate-900 text-sm mb-1 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500"></span>
              Automated Inspection Ready
            </div>
            <p className="text-slate-500 max-w-xl leading-relaxed">
              This content draft is registered in the governance ledger. Run the LangGraph compliance inspection engine
              to verify compliance against all active brand guidelines, detect rule breaches, extract verbatim evidence citations,
              and synthesize grounded correction suggestions.
            </p>
          </div>
          <div className="flex items-center gap-2.5 self-start sm:self-center flex-shrink-0">
            {onTriggerAnalysis && currentSubmission && (
              <button
                onClick={() => onTriggerAnalysis(currentSubmission.id)}
                disabled={isAnalyzing}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg text-xs font-semibold transition flex items-center gap-1.5 shadow-sm"
              >
                <Sparkles className={`w-3.5 h-3.5 ${isAnalyzing ? 'animate-spin' : ''}`} />
                {isAnalyzing ? 'Inspecting Content...' : 'Run Compliance Inspection'}
              </button>
            )}
            <button
              onClick={() => onNavigate('review')}
              className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold transition"
            >
              Go to Human Review Console
            </button>
          </div>
        </div>
      )}

      {/* Two Column Layout: Text Inspection vs Rule Violations */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Flagged Text Visualizer (5 cols) */}
        <div className="lg:col-span-5 bg-white rounded-xl border border-slate-200/80 shadow-subtle p-5 space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <div>
              <h3 className="text-sm font-bold text-slate-900">Submitted Copy Inspection</h3>
              <p className="text-[11px] text-slate-500">
                Target: <span className="capitalize font-medium text-slate-700">{currentSubmission.target_channel.replace(/_/g, ' ')}</span>
              </p>
            </div>
            <span className="text-[11px] text-slate-400">
              v{currentSubmission.version}
            </span>
          </div>

          {/* Highlighted text container */}
          <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-800 leading-relaxed font-normal">
            {renderHighlightedContent()}
          </div>

          <div className="text-[11px] text-slate-500 bg-slate-50 p-2.5 rounded-lg border border-slate-100 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-rose-500 flex-shrink-0"></span>
            <span>Click any highlighted segment to highlight its rule and evidence citation.</span>
          </div>
        </div>

        {/* Right Column: Violation Cards & Evidence Citations (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-900">
              Evidence-Backed Violations ({currentReport ? currentReport.violations.length : 0})
            </h3>
            <span className="text-[11px] text-slate-500">
              All violations require verified citations
            </span>
          </div>

          {isAnalyzing ? (
            <div className="p-12 text-center bg-white rounded-xl border border-slate-200/90 shadow-subtle space-y-3">
              <Sparkles className="w-8 h-8 text-blue-600 animate-spin mx-auto" />
              <h4 className="text-sm font-bold text-slate-800">Inspecting Content Against Brand Guidelines</h4>
              <p className="text-xs text-slate-500 max-w-sm mx-auto">
                Running deterministic rule detectors, retrieving tenant policies, and extracting grounding evidence citations...
              </p>
            </div>
          ) : currentReport && currentReport.violations.length > 0 ? (
            <div className="space-y-3.5">
              {currentReport.violations.map((violation) => {
                const isSelected = activeViolationId === violation.id;

                return (
                  <div
                    key={violation.id}
                    onClick={() => setActiveViolationId(violation.id)}
                    className={`bg-white rounded-xl border transition p-4 cursor-pointer ${
                      isSelected
                        ? 'border-blue-500 ring-2 ring-blue-500/10 shadow-sm'
                        : 'border-slate-200/90 hover:border-slate-300 shadow-subtle'
                    }`}
                  >
                    {/* Header: Name, Severity, Rule Type */}
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge severity={violation.severity} />
                        <h4 className="text-xs font-bold text-slate-900">{violation.rule_name}</h4>
                      </div>
                      <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-600">
                        {violation.rule_type.replace(/_/g, ' ')}
                      </span>
                    </div>

                    {/* Flagged Text Box */}
                    <div className="mb-2.5 p-2 rounded bg-rose-50/60 border border-rose-100 text-xs">
                      <span className="text-[10px] font-semibold uppercase text-rose-700 block mb-0.5">
                        Flagged Text:
                      </span>
                      <span className="font-mono text-rose-900 bg-white/80 px-1 py-0.5 rounded border border-rose-200/60 inline-block">
                        "{violation.flagged_text}"
                      </span>
                    </div>

                    {/* Explanation */}
                    <p className="text-xs text-slate-600 leading-relaxed mb-3">
                      {violation.explanation}
                    </p>

                    {/* Grounding Evidence Citations */}
                    <div className="pt-2.5 border-t border-slate-100 space-y-2">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-teal-700 flex items-center gap-1">
                        <Scale className="w-3 h-3 text-teal-600" />
                        <span>Grounding Evidence Citations ({violation.evidence_citations.length}):</span>
                      </div>

                      {violation.evidence_citations.map((citation) => (
                        <div
                          key={citation.id}
                          className="bg-slate-50 p-2.5 rounded-lg border border-slate-200/70 text-xs"
                        >
                          <div className="flex items-center justify-between text-[11px] font-semibold text-slate-700 mb-1">
                            <span className="truncate">{citation.document_name}</span>
                            <span className="text-emerald-700 bg-emerald-50 px-1.5 py-0.2 rounded border border-emerald-200 text-[10px]">
                              {Math.round(citation.confidence_score * 100)}% match
                            </span>
                          </div>
                          <p className="text-[11px] text-slate-600 italic leading-snug">
                            "{citation.source_clause}"
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : !currentReport ? (
            <EmptyState
              icon={SearchCheck}
              title="Inspection Pending"
              description={
                dbOffline
                  ? "Database service is currently offline. Connect to PostgreSQL or SQLite to run automated compliance inspections."
                  : "This content draft has not been inspected yet. Click 'Run Compliance Inspection' to evaluate it against active brand guidelines."
              }
              actionText={!dbOffline && onTriggerAnalysis && currentSubmission ? "Run Compliance Inspection" : undefined}
              onAction={!dbOffline && onTriggerAnalysis && currentSubmission ? () => onTriggerAnalysis(currentSubmission.id) : undefined}
            />
          ) : !currentReport.is_compliant ? (
            <EmptyState
              icon={AlertTriangle}
              title="No Active Brand Guidelines Configured"
              description={currentReport.summary || "No active brand guidelines exist for this organization. Content compliance cannot be certified."}
            />
          ) : (
            <EmptyState
              icon={CheckCircle2}
              title="Content is Fully Compliant"
              description="No brand violations or prohibited claims were identified in this content submission."
              actionText="Proceed to Human Review"
              onAction={() => onNavigate('review')}
            />
          )}
        </div>
      </div>
    </div>
  );
};
