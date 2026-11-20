import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  Edit3,
  RotateCcw,
  AlertTriangle,
  UserCheck,
  Clock,
  LogIn,
  ShieldAlert,
} from 'lucide-react';
import {
  NavigationTab,
  ContentSubmission,
  ComplianceReport,
  ReviewAction,
  AuthUser,
} from '../types';
import { StatusBadge } from '../components/common/StatusBadge';
import { MediaBadge } from '../components/common/MediaBadge';
import { AlertBanner } from '../components/common/AlertBanner';
import { EmptyState } from '../components/common/EmptyState';

interface ReviewPageProps {
  onNavigate: (tab: NavigationTab) => void;
  submissions: ContentSubmission[];
  selectedSubmissionId: string;
  onSelectSubmission: (id: string) => void;
  reports: Record<string, ComplianceReport>;
  stagedContent?: string;
  currentUser: AuthUser | null;
  onOpenLogin: () => void;
  onRecordDecision: (
    submissionId: string,
    action: ReviewAction,
    feedback: string,
    editedContent?: string,
    overrideReason?: string
  ) => Promise<void> | void;
  onAdvanceToReview?: (submissionId: string, stagedContent?: string) => Promise<void> | void;
}

export const ReviewPage: React.FC<ReviewPageProps> = ({
  onNavigate,
  submissions,
  selectedSubmissionId,
  onSelectSubmission,
  reports,
  stagedContent,
  currentUser,
  onOpenLogin,
  onRecordDecision,
  onAdvanceToReview,
}) => {
  // Find current submission or default to the first one under review
  const pendingSubmission =
    submissions.find((s) => s.id === selectedSubmissionId) ||
    submissions.find((s) => s.status === 'under_human_review') ||
    submissions[0];

  const currentReport = pendingSubmission ? reports[pendingSubmission.id] : null;

  // Review decision form state
  const [selectedAction, setSelectedAction] = useState<ReviewAction | null>(null);
  const [feedbackNotes, setFeedbackNotes] = useState('');
  const [overrideReason, setOverrideReason] = useState('');
  const [editableContent, setEditableContent] = useState(
    stagedContent ||
      (pendingSubmission
        ? pendingSubmission.content
        : '')
  );
  const [validationError, setValidationError] = useState<string | null>(null);
  const [decisionSuccess, setDecisionSuccess] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAdvancing, setIsAdvancing] = useState(false);

  // Synchronize editable content whenever staged content or target submission changes
  useEffect(() => {
    if (stagedContent) {
      setEditableContent(stagedContent);
    } else if (pendingSubmission) {
      setEditableContent(pendingSubmission.content);
    }
  }, [stagedContent, pendingSubmission?.id]);

  // Role authorization evaluation
  const isAuthorizedReviewer = currentUser && (currentUser.role === 'ADMIN' || currentUser.role === 'REVIEWER');
  const hasActiveViolations = currentReport && currentReport.total_violations > 0;
  const isUnderReview = pendingSubmission?.status === 'under_human_review';
  const canReview = Boolean(isAuthorizedReviewer && isUnderReview);

  // Access Control Guard: CREATOR role is forbidden from accessing the Human Review Console
  if (currentUser && currentUser.role === 'CREATOR') {
    return (
      <div className="max-w-4xl mx-auto py-12 px-4 sm:px-6">
        <div className="p-8 rounded-2xl bg-slate-900 border border-slate-800 text-center shadow-subtle">
          <div className="w-16 h-16 rounded-2xl bg-amber-950/60 border border-amber-800/60 flex items-center justify-center mx-auto mb-4 text-amber-400">
            <ShieldAlert className="w-8 h-8 text-amber-400" />
          </div>
          <h2 className="text-xl font-bold text-white tracking-tight">Governance Review Authority Required</h2>
          <p className="text-sm text-slate-400 max-w-md mx-auto mt-2 leading-relaxed">
            The Human Review & Authorization Console is strictly restricted to designated Compliance Officers and Administrators (ADMIN, REVIEWER).
            Your current assigned role is <span className="font-semibold text-slate-200">CREATOR</span>.
          </p>
          <div className="mt-4 p-3 rounded-lg bg-slate-800/60 border border-slate-700/60 max-w-md mx-auto text-xs text-slate-300 text-left space-y-1">
            <p className="font-semibold text-slate-200">Governance Principle:</p>
            <p>Content Creators can draft and inspect copy in Content Submission, but cannot review, authorize, or publish submissions.</p>
          </div>
          <div className="mt-6 flex items-center justify-center gap-3">
            <button
              onClick={() => onNavigate('dashboard')}
              className="py-2.5 px-5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition"
            >
              Return to Dashboard
            </button>
            <button
              onClick={() => onNavigate('submission')}
              className="py-2.5 px-5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition"
            >
              Go to Content Submission
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!pendingSubmission) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="Review Queue is Empty"
        description="There are currently no submissions awaiting human governance review. New submissions will appear here once submitted."
        actionText="Submit Content"
        onAction={() => onNavigate('submission')}
      />
    );
  }

  const handleExecuteDecision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;

    if (!currentUser) {
      setValidationError('Human authentication required. Please sign in before authorizing review decisions.');
      onOpenLogin();
      return;
    }

    if (!isAuthorizedReviewer) {
      setValidationError(`Access Denied: Your assigned role '${currentUser.role}' is not authorized to make review decisions. ADMIN or REVIEWER role required.`);
      return;
    }

    if (!isUnderReview) {
      setValidationError(
        `Review actions are restricted to submissions in 'under_human_review' status. This submission is currently in '${pendingSubmission.status.replace(/_/g, ' ')}' status.`
      );
      return;
    }

    setValidationError(null);
    setDecisionSuccess(null);

    if (!selectedAction) {
      setValidationError('Please select a review decision before authorizing.');
      return;
    }

    // Strict validation enforcing human governance invariants
    if (selectedAction === 'edit_and_approve') {
      if (!editableContent || editableContent.trim().length === 0) {
        setValidationError('Edited content cannot be empty when choosing "Edit & Approve".');
        return;
      }
    }

    if (selectedAction === 'approve' && hasActiveViolations) {
      if (!overrideReason || overrideReason.trim().length < 5) {
        setValidationError(
          'Cannot approve copy with active rule violations without an authorized override reason (min 5 characters).'
        );
        return;
      }
    }

    if (selectedAction === 'reject' || selectedAction === 'request_revision') {
      if (!feedbackNotes || feedbackNotes.trim().length < 5) {
        setValidationError(
          `Reviewer feedback is mandatory (min 5 characters) when action is "${selectedAction.replace(/_/g, ' ')}".`
        );
        return;
      }
    }

    try {
      setIsSubmitting(true);
      await onRecordDecision(
        pendingSubmission.id,
        selectedAction,
        feedbackNotes.trim(),
        selectedAction === 'edit_and_approve' ? editableContent.trim() : undefined,
        overrideReason.trim() || undefined
      );

      setDecisionSuccess(
        `Governance decision successfully authorized by ${currentUser.full_name} and permanently committed to the immutable audit ledger.`
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to record review decision';
      setValidationError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAdvanceCurrentSubmission = async () => {
    if (!onAdvanceToReview || !pendingSubmission) return;
    try {
      setIsAdvancing(true);
      await onAdvanceToReview(pendingSubmission.id, stagedContent || undefined);
    } catch (err: unknown) {
      setValidationError(err instanceof Error ? err.message : 'Failed to advance submission to review queue.');
    } finally {
      setIsAdvancing(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Strict Human-in-the-Loop Governance Notice */}
      <AlertBanner type="governance" title="Human-in-the-Loop Governance Gate">
        The AI evaluation engine provides advisory inspection and remediation suggestions. Final publication, approval,
        or rejection strictly requires authorized human sign-off. AI agents are prohibited from making decisions.
      </AlertBanner>

      {/* Reviewer Identity & Authority Card */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-subtle p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm border ${
            isAuthorizedReviewer
              ? 'bg-blue-100 text-blue-700 border-blue-200'
              : currentUser
              ? 'bg-amber-100 text-amber-700 border-amber-200'
              : 'bg-slate-100 text-slate-500 border-slate-200'
          }`}>
            <UserCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-900">
                {currentUser ? currentUser.full_name : 'Unauthenticated Guest'}
              </h3>
              {isAuthorizedReviewer ? (
                <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
                  Authorized Reviewer ({currentUser.role})
                </span>
              ) : currentUser ? (
                <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                  Role: {currentUser.role} (No Review Rights)
                </span>
              ) : (
                <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
                  Sign In Required
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500">
              {currentUser
                ? `Verified Account: ${currentUser.email} • Organization Tenant Active`
                : 'Please sign in to authenticate as an authorized human reviewer.'}
            </p>
          </div>
        </div>

        {/* Right Action: Submission Selector or Sign In */}
        <div className="flex items-center gap-2 self-start sm:self-center">
          {!currentUser && (
            <button
              onClick={onOpenLogin}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs transition shadow-sm"
            >
              <LogIn className="w-3.5 h-3.5" />
              <span>Sign In as Reviewer</span>
            </button>
          )}

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 font-medium">Review Queue:</span>
            <select
              value={pendingSubmission.id}
              onChange={(e) => onSelectSubmission(e.target.value)}
              className="text-xs py-1.5 px-3 rounded-lg border border-slate-200 bg-white text-slate-800 font-medium focus:ring-2 focus:ring-blue-500/20"
            >
              {submissions.map((sub) => (
                <option key={sub.id} value={sub.id}>
                  {sub.title} [{sub.status.replace(/_/g, ' ')}]
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Role Authorization Warning Banner if logged in without review rights */}
      {currentUser && !isAuthorizedReviewer && (
        <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="text-xs font-bold text-amber-900">Governance Review Permissions Required</h4>
            <p className="text-xs text-amber-700 mt-0.5">
              Your account is signed in with the <strong>{currentUser.role}</strong> role. Under BrandShield governance policies,
              only users with <strong>ADMIN</strong> or <strong>REVIEWER</strong> permissions may approve, reject, or edit submissions.
            </p>
          </div>
        </div>
      )}

      {/* Non-Under-Review Status Alert Banner */}
      {!isUnderReview && (
        <div className="p-4 rounded-xl bg-blue-50/80 border border-blue-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="font-bold text-blue-950">
                Submission Status: <span className="uppercase">{pendingSubmission.status.replace(/_/g, ' ')}</span>
              </h4>
              <p className="text-blue-800 mt-0.5">
                {pendingSubmission.status === 'approved'
                  ? 'This submission has been authorized and published. Review actions are locked.'
                  : pendingSubmission.status === 'rejected'
                  ? 'This submission was rejected by a reviewer. Review actions are locked.'
                  : 'This submission must be formally routed to the Human Review Queue before a review decision can be committed.'}
              </p>
            </div>
          </div>
          {(pendingSubmission.status === 'violations_found' ||
            pendingSubmission.status === 'passed_checks' ||
            pendingSubmission.status === 'draft' ||
            pendingSubmission.status === 'submitted') && (
            <button
              onClick={handleAdvanceCurrentSubmission}
              disabled={isAdvancing}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-semibold transition self-start sm:self-center flex-shrink-0 shadow-sm"
            >
              {isAdvancing ? 'Routing to Queue...' : 'Route to Human Review Queue'}
            </button>
          )}
        </div>
      )}

      {/* Success Banner */}
      {decisionSuccess && (
        <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2 font-medium">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0" />
          <span>{decisionSuccess}</span>
        </div>
      )}

      {/* Two-Column Decision Console */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Submission Inspection Details (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-subtle p-5 space-y-4">
            <div className="pb-3 border-b border-slate-100 flex items-start justify-between gap-2">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Target Channel: {pendingSubmission.target_channel.replace(/_/g, ' ')}
                  </span>
                  <MediaBadge mediaType={pendingSubmission.media_type} />
                </div>
                <h3 className="text-base font-bold text-slate-900 mt-0.5">
                  {pendingSubmission.title}
                </h3>
              </div>
              <StatusBadge status={pendingSubmission.status} />
            </div>

            {/* Multimodal Asset Metadata if applicable */}
            {pendingSubmission.media_type && pendingSubmission.media_type !== 'text' && (
              <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200 text-[11px] text-slate-600 space-y-1">
                <div className="flex justify-between font-medium">
                  <span className="text-slate-500">Asset File:</span>
                  <span className="text-slate-800 font-semibold truncate max-w-[200px]">
                    {pendingSubmission.multimodal_metadata?.original_filename || `${pendingSubmission.media_type} upload`}
                  </span>
                </div>
                {pendingSubmission.file_size_bytes && (
                  <div className="flex justify-between">
                    <span className="text-slate-500">Asset Size:</span>
                    <span>{Math.round(pendingSubmission.file_size_bytes / 1024)} KB</span>
                  </div>
                )}
                {pendingSubmission.file_hash_sha256 && (
                  <div className="flex justify-between">
                    <span className="text-slate-500">SHA-256:</span>
                    <code className="font-mono text-[10px] text-slate-700">{pendingSubmission.file_hash_sha256.slice(0, 12)}...</code>
                  </div>
                )}
              </div>
            )}

            {/* Honest Status Alert for Reviewers */}
            {pendingSubmission.multimodal_metadata?.processing_status === 'UNAVAILABLE' && (
              <div className="p-2.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 text-[11px] flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" />
                <span>AI vision service was offline during inspection; offline heuristics were used.</span>
              </div>
            )}

            <div className="space-y-2 text-xs text-slate-600">
              <div className="flex justify-between">
                <span>Audience:</span>
                <span className="font-semibold text-slate-800">
                  {pendingSubmission.target_audience}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Submitted By:</span>
                <span className="text-slate-800">{pendingSubmission.author_name}</span>
              </div>
              <div className="flex justify-between">
                <span>Version:</span>
                <span className="text-slate-800">v{pendingSubmission.version}</span>
              </div>
            </div>

            {/* Current Text Box */}
            <div className="pt-3 border-t border-slate-100">
              <span className="text-xs font-semibold text-slate-800 block mb-1">
                Original Submitted Content:
              </span>
              <p className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-700 leading-relaxed font-mono">
                {pendingSubmission.content}
              </p>
            </div>

            {/* Violation Summary */}
            {currentReport && currentReport.violations.length > 0 && (
              <div className="pt-3 border-t border-slate-100">
                <span className="text-xs font-semibold text-rose-700 block mb-2 flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 text-rose-600" />
                  Identified Violations ({currentReport.violations.length})
                </span>
                <ul className="space-y-2 text-xs text-slate-600">
                  {currentReport.violations.map((v) => (
                    <li key={v.id} className="p-2 rounded bg-rose-50/40 border border-rose-100/60 space-y-1">
                      <div className="flex items-start justify-between gap-1">
                        <span className="font-semibold text-slate-800 flex items-center gap-1">
                          <span className="text-rose-500 font-bold">•</span>
                          {v.rule_name}
                        </span>
                        <span className="text-[10px] font-mono px-1 py-0.5 rounded bg-slate-100 text-slate-600">
                          {v.rule_type.replace(/_/g, ' ')}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-600 pl-3 leading-snug">{v.explanation}</p>
                      {(v.bounding_box || v.timestamp_seconds !== undefined) && (
                        <div className="flex items-center gap-1.5 pl-3 pt-0.5 text-[10px]">
                          {v.bounding_box && (
                            <span className="bg-indigo-50 text-indigo-700 border border-indigo-200 px-1 rounded font-mono">
                              Box: [{v.bounding_box.map((n) => typeof n === 'number' ? n.toFixed(2) : n).join(', ')}]
                            </span>
                          )}
                          {v.timestamp_seconds !== undefined && v.timestamp_seconds !== null && (
                            <span className="bg-blue-50 text-blue-700 border border-blue-200 px-1 rounded font-mono">
                              ⏱ {Math.floor(v.timestamp_seconds / 60).toString().padStart(2, '0')}:{(v.timestamp_seconds % 60).toFixed(3).padStart(6, '0')}
                            </span>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Human Decision Controls (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          <form
            onSubmit={handleExecuteDecision}
            className="bg-white rounded-xl border border-slate-200/80 shadow-subtle p-5 space-y-4"
          >
            <div className="pb-3 border-b border-slate-100">
              <h3 className="text-sm font-bold text-slate-900">Execute Governance Decision</h3>
              <p className="text-xs text-slate-500">
                Choose the appropriate human review action. All decisions generate immutable audit records.
              </p>
            </div>

            {validationError && (
              <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-rose-600 flex-shrink-0" />
                <span>{validationError}</span>
              </div>
            )}

            {/* Action Buttons Radio Group */}
            <div className="grid grid-cols-2 gap-2.5">
              <label
                className={`p-3 rounded-lg border cursor-pointer text-xs transition flex flex-col gap-1 ${
                  selectedAction === 'edit_and_approve'
                    ? 'border-blue-500 bg-blue-50/50 ring-2 ring-blue-500/10'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-900 flex items-center gap-1.5">
                    <Edit3 className="w-3.5 h-3.5 text-blue-600" />
                    Edit & Approve
                  </span>
                  <input
                    type="radio"
                    name="review_action"
                    checked={selectedAction === 'edit_and_approve'}
                    onChange={() => setSelectedAction('edit_and_approve')}
                    className="text-blue-600"
                  />
                </div>
                <span className="text-[11px] text-slate-500 leading-snug">
                  Apply corrections directly and approve draft for publication.
                </span>
              </label>

              <label
                className={`p-3 rounded-lg border cursor-pointer text-xs transition flex flex-col gap-1 ${
                  selectedAction === 'approve'
                    ? 'border-emerald-500 bg-emerald-50/50 ring-2 ring-emerald-500/10'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-900 flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                    Approve As-Is
                  </span>
                  <input
                    type="radio"
                    name="review_action"
                    checked={selectedAction === 'approve'}
                    onChange={() => setSelectedAction('approve')}
                    className="text-emerald-600"
                  />
                </div>
                <span className="text-[11px] text-slate-500 leading-snug">
                  Authorize unchanged draft (requires override if violations exist).
                </span>
              </label>

              <label
                className={`p-3 rounded-lg border cursor-pointer text-xs transition flex flex-col gap-1 ${
                  selectedAction === 'request_revision'
                    ? 'border-amber-500 bg-amber-50/50 ring-2 ring-amber-500/10'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-900 flex items-center gap-1.5">
                    <RotateCcw className="w-3.5 h-3.5 text-amber-600" />
                    Request Revision
                  </span>
                  <input
                    type="radio"
                    name="review_action"
                    checked={selectedAction === 'request_revision'}
                    onChange={() => setSelectedAction('request_revision')}
                    className="text-amber-600"
                  />
                </div>
                <span className="text-[11px] text-slate-500 leading-snug">
                  Send draft back to author with mandatory revision notes.
                </span>
              </label>

              <label
                className={`p-3 rounded-lg border cursor-pointer text-xs transition flex flex-col gap-1 ${
                  selectedAction === 'reject'
                    ? 'border-rose-500 bg-rose-50/50 ring-2 ring-rose-500/10'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-900 flex items-center gap-1.5">
                    <XCircle className="w-3.5 h-3.5 text-rose-600" />
                    Reject Draft
                  </span>
                  <input
                    type="radio"
                    name="review_action"
                    checked={selectedAction === 'reject'}
                    onChange={() => setSelectedAction('reject')}
                    className="text-rose-600"
                  />
                </div>
                <span className="text-[11px] text-slate-500 leading-snug">
                  Permanently decline publication with formal reason.
                </span>
              </label>
            </div>

            {/* Interactive Edited Content Textarea (if Edit and Approve) */}
            {selectedAction === 'edit_and_approve' && (
              <div>
                <label className="block text-xs font-semibold text-slate-800 mb-1">
                  Approved Content for Publication <span className="text-rose-500">*</span>
                </label>
                <textarea
                  rows={4}
                  value={editableContent}
                  onChange={(e) => setEditableContent(e.target.value)}
                  placeholder="Review and finalize the exact text to be approved..."
                  className="w-full p-3 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 text-slate-900 leading-relaxed font-medium"
                />
              </div>
            )}

            {/* Override Reason Input (if Approve As-Is and violations exist) */}
            {selectedAction === 'approve' && hasActiveViolations && (
              <div className="p-3 rounded-lg bg-amber-50/60 border border-amber-200 space-y-1.5">
                <label className="block text-xs font-semibold text-amber-900">
                  Authorized Override Justification <span className="text-rose-500">*</span>
                </label>
                <p className="text-[11px] text-amber-700">
                  Unresolved violations are flagged. Under governance rules, you must record an authorized business or legal exception reason to approve this content as-is.
                </p>
                <textarea
                  rows={2}
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  placeholder="e.g., Executive legal waiver #LEG-2026-088 granted for trial campaign..."
                  className="w-full p-2.5 text-xs rounded-lg border border-amber-300 focus:outline-none focus:ring-2 focus:ring-amber-500/20 text-slate-900 leading-relaxed"
                />
              </div>
            )}

            {/* Reviewer Feedback Input */}
            <div>
              <label className="block text-xs font-semibold text-slate-800 mb-1">
                Reviewer Feedback & Audit Rationale{' '}
                {(selectedAction === 'reject' || selectedAction === 'request_revision') && (
                  <span className="text-rose-500">*</span>
                )}
              </label>
              <textarea
                rows={3}
                value={feedbackNotes}
                onChange={(e) => setFeedbackNotes(e.target.value)}
                placeholder={
                  selectedAction === 'reject' || selectedAction === 'request_revision'
                    ? 'Explain the mandatory revisions required before approval...'
                    : 'Optional audit note for this sign-off...'
                }
                className="w-full p-3 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 text-slate-900 leading-relaxed"
              />
            </div>

            {/* Ledger Commitment Preview */}
            <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs space-y-1">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1">
                <Clock className="w-3 h-3 text-slate-400" />
                <span>Audit Preview (Committed upon authorization):</span>
              </div>
              {selectedAction ? (
                <div className="text-[11px] text-slate-700">
                  Action: <strong className="text-slate-900">{selectedAction}</strong> • Actor:{' '}
                  <strong className="text-slate-900">
                    {currentUser ? `${currentUser.full_name} (human)` : 'Unverified human actor'}
                  </strong>{' '}
                  • Target Status:{' '}
                  <strong className="text-slate-900">
                    {selectedAction === 'approve' || selectedAction === 'edit_and_approve'
                      ? 'approved'
                      : selectedAction === 'reject'
                      ? 'rejected'
                      : 'revision_requested'}
                  </strong>
                </div>
              ) : (
                <div className="text-[11px] text-slate-500 italic">
                  No decision selected. Select an action above to preview the immutable audit record.
                </div>
              )}
            </div>

            {/* Submit Button */}
            <div className="pt-2 flex justify-end">
              <button
                type="submit"
                disabled={isSubmitting || !canReview || !selectedAction}
                className={`px-5 py-2.5 rounded-lg text-white text-xs font-bold transition shadow-sm flex items-center gap-2 ${
                  !currentUser
                    ? 'bg-slate-400 cursor-not-allowed'
                    : !isAuthorizedReviewer
                    ? 'bg-amber-600 opacity-60 cursor-not-allowed'
                    : !isUnderReview
                    ? 'bg-slate-400 cursor-not-allowed'
                    : !selectedAction
                    ? 'bg-slate-400 cursor-not-allowed'
                    : 'bg-blue-600 hover:bg-blue-700'
                }`}
              >
                <ShieldCheck className="w-4 h-4" />
                {!currentUser
                  ? 'Sign In Required to Authorize'
                  : !isAuthorizedReviewer
                  ? `Forbidden for ${currentUser.role}`
                  : !isUnderReview
                  ? `Status: ${pendingSubmission.status.replace(/_/g, ' ')}`
                  : !selectedAction
                  ? 'Select Decision to Authorize'
                  : isSubmitting
                  ? 'Committing to Audit Ledger...'
                  : 'Authorize & Commit Decision'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};
