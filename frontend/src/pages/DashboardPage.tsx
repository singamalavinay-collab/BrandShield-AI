import React from 'react';
import {
  BookOpen,
  FileText,
  AlertTriangle,
  CheckCircle2,
  ArrowRight,
  Server,
  RefreshCw,
  Plus,
  Clock,
  UserCheck,
  Database,
} from 'lucide-react';
import {
  NavigationTab,
  ContentSubmission,
  BrandGuideline,
  BackendHealth,
  AuditEntry,
  SystemDiagnostic,
} from '../types';
import { StatusBadge } from '../components/common/StatusBadge';
import { MediaBadge } from '../components/common/MediaBadge';
import { AlertBanner } from '../components/common/AlertBanner';
import { EmptyState } from '../components/common/EmptyState';

interface DashboardPageProps {
  onNavigate: (tab: NavigationTab) => void;
  submissions: ContentSubmission[];
  guidelines: BrandGuideline[];
  auditLogs: AuditEntry[];
  backendHealth: BackendHealth;
  systemDiagnostic: SystemDiagnostic | null;
  isCheckingHealth: boolean;
  onRefreshHealth: () => void;
  onSelectSubmissionForAnalysis: (subId: string) => void;
  onSelectSubmissionForReview: (subId: string) => void;
}

export const DashboardPage: React.FC<DashboardPageProps> = ({
  onNavigate,
  submissions,
  guidelines,
  auditLogs,
  backendHealth,
  systemDiagnostic,
  isCheckingHealth,
  onRefreshHealth,
  onSelectSubmissionForAnalysis,
  onSelectSubmissionForReview,
}) => {
  const activeGuidelinesCount = guidelines.filter((g) => g.is_active).length;
  const pendingReviewsCount = submissions.filter((s) => s.status === 'under_human_review').length;
  const unroutedViolationsCount = submissions.filter((s) => s.status === 'violations_found').length;
  const evaluatedSubmissions = submissions.filter((s) =>
    ['passed_checks', 'violations_found', 'under_human_review', 'approved', 'rejected', 'revision_requested'].includes(
      s.status
    )
  );
  const compliantCount = evaluatedSubmissions.filter((s) =>
    ['passed_checks', 'approved'].includes(s.status)
  ).length;
  const complianceRate =
    evaluatedSubmissions.length > 0
      ? Math.round((compliantCount / evaluatedSubmissions.length) * 100)
      : null;

  const isDbConnected = systemDiagnostic?.database?.connected ?? false;
  const isAllDemo = submissions.length > 0 && submissions.every((s) => s.is_demo);

  return (
    <div className="space-y-6">
      {/* Governance Banner */}
      <AlertBanner type="governance" title="Autonomous AI Approval Strictly Prohibited">
        BrandShield AI operates with mandatory human oversight. AI analysis detects violations and proposes
        corrections, but final approval and publication require explicit authorized human sign-off.
      </AlertBanner>

      {/* Demonstration / Live Integration Transparency Banner */}
      {isAllDemo && (
        <AlertBanner type="info" title="Demonstration Presets Active">
          Currently displaying template guidelines and demonstration drafts for interface evaluation. Real content
          submitted via the Submission Workspace is routed through the integrated FastAPI backend API.
        </AlertBanner>
      )}

      {/* Primary KPI Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Metric 1 */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/80 shadow-subtle hover:border-slate-300 transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Active Guidelines
            </span>
            <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
              <BookOpen className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold text-slate-900 mt-2">{activeGuidelinesCount}</div>
          <div className="text-xs text-slate-500 mt-1 flex items-center gap-1">
            <span>Enforced across all channels</span>
          </div>
        </div>

        {/* Metric 2 */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/80 shadow-subtle hover:border-slate-300 transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Monitored Submissions
            </span>
            <div className="w-8 h-8 rounded-lg bg-slate-100 text-slate-700 flex items-center justify-center">
              <FileText className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold text-slate-900 mt-2">{submissions.length}</div>
          <div className="text-xs text-slate-500 mt-1">
            {compliantCount} compliant, {submissions.length - compliantCount} in governance
          </div>
        </div>

        {/* Metric 3 */}
        <div
          className="bg-white p-5 rounded-xl border border-slate-200/80 shadow-subtle hover:border-slate-300 transition"
          title="Formal review queue requires submissions to be in 'under_human_review' status. Submissions with 'violations_found' can be advanced to review from the Analysis page."
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Formal Review Queue
            </span>
            <div className="w-8 h-8 rounded-lg bg-purple-50 text-purple-600 flex items-center justify-center">
              <AlertTriangle className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold text-purple-700 mt-2">{pendingReviewsCount}</div>
          <div className="text-xs text-slate-500 mt-1">
            {pendingReviewsCount} in queue awaiting sign-off
            {unroutedViolationsCount > 0 && (
              <span className="block text-[11px] text-amber-600 mt-0.5">
                ({unroutedViolationsCount} unrouted {unroutedViolationsCount === 1 ? 'violation' : 'violations'} in staging)
              </span>
            )}
          </div>
        </div>

        {/* Metric 4 */}
        <div
          className="bg-white p-5 rounded-xl border border-slate-200/80 shadow-subtle hover:border-slate-300 transition"
          title="Compliance rate is calculated across evaluated drafts (passed checks + approved / total evaluated)."
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Compliance Rate
            </span>
            <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
              <CheckCircle2 className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold text-emerald-700 mt-2">
            {complianceRate !== null ? `${complianceRate}%` : '—'}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {isAllDemo
              ? 'Demo simulation rate'
              : evaluatedSubmissions.length > 0
              ? `${compliantCount} of ${evaluatedSubmissions.length} evaluated drafts compliant`
              : 'No submissions evaluated yet'}
          </div>
        </div>
      </div>

      {/* Two Column Grid: Recent Submissions & Backend Status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Recent Submissions (2 cols) */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200/80 shadow-subtle overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Recent Content Submissions</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Current content lifecycle across marketing, social, and legal
              </p>
            </div>
            <button
              onClick={() => onNavigate('submission')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition shadow-sm"
            >
              <Plus className="w-3.5 h-3.5" />
              New Draft
            </button>
          </div>

          {submissions.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={FileText}
                title="No Content Submissions Yet"
                description="Your workspace is initialized and ready for brand compliance monitoring. Submit your first draft to evaluate it against your brand rules."
                actionText="Create First Draft"
                onAction={() => onNavigate('submission')}
              />
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {submissions.map((sub) => (
                <div
                  key={sub.id}
                  className="p-4 hover:bg-slate-50/80 transition flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-sm font-semibold text-slate-900 truncate">{sub.title}</h3>
                      <span className="font-mono text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200">
                        #{sub.id.length > 12 ? sub.id.slice(0, 8) : sub.id}
                      </span>
                      <MediaBadge mediaType={sub.media_type} />
                      <StatusBadge status={sub.status} />
                      {sub.is_demo ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-medium">
                          Demo Preset
                        </span>
                      ) : (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium">
                          Live Entry
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 line-clamp-1 mt-1">{sub.content}</p>
                    <div className="flex items-center gap-4 text-[11px] text-slate-400 mt-2 flex-wrap">
                      <span>Channel: <strong className="text-slate-600 capitalize">{sub.target_channel.replace('_', ' ')}</strong></span>
                      <span>Author: {sub.author_name}</span>
                      <span>v{sub.version}</span>
                      {sub.created_at && (
                        <span>
                          Created: {new Date(sub.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}, {new Date(sub.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 self-end sm:self-center">
                    <button
                      onClick={() => onSelectSubmissionForAnalysis(sub.id)}
                      className="px-2.5 py-1 text-xs font-medium text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 rounded-md transition"
                    >
                      Analysis
                    </button>
                    {sub.status === 'under_human_review' && (
                      <button
                        onClick={() => onSelectSubmissionForReview(sub.id)}
                        className="px-2.5 py-1 text-xs font-medium text-purple-700 bg-purple-50 border border-purple-200 hover:bg-purple-100 rounded-md transition flex items-center gap-1"
                      >
                        <UserCheck className="w-3 h-3" />
                        Review
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="p-3 bg-slate-50 border-t border-slate-200 text-center">
            <button
              onClick={() => onNavigate('submission')}
              className="text-xs font-medium text-blue-600 hover:text-blue-800 transition inline-flex items-center gap-1"
            >
              Submit another content draft for inspection
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>
        </div>

        {/* Right Column: Engine Health & Quick Governance Audit */}
        <div className="space-y-6">
          {/* Engine Health Card */}
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-subtle p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Server className="w-4 h-4 text-slate-600" />
                <h3 className="text-sm font-semibold text-slate-900">Backend API Connectivity</h3>
              </div>
              <button
                onClick={onRefreshHealth}
                disabled={isCheckingHealth}
                className="p-1 rounded text-slate-400 hover:text-slate-600 transition"
                title="Ping health check endpoint"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isCheckingHealth ? 'animate-spin text-blue-600' : ''}`} />
              </button>
            </div>

            <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Target Endpoint:</span>
                <code className="text-[11px] bg-slate-200/80 px-1 py-0.5 rounded text-slate-800 font-mono">
                  GET /health
                </code>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">API Status:</span>
                <span className={`font-semibold flex items-center gap-1.5 ${
                  backendHealth.is_connected ? 'text-emerald-700' : 'text-amber-700'
                }`}>
                  <span className={`w-2 h-2 rounded-full ${
                    backendHealth.is_connected ? 'bg-emerald-500' : 'bg-amber-500'
                  }`} />
                  {backendHealth.is_connected ? 'Connected (Healthy)' : 'Offline (UI Preview)'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500 flex items-center gap-1">
                  <Database className="w-3 h-3 text-slate-400" />
                  Database:
                </span>
                <span className={`font-medium ${isDbConnected ? 'text-emerald-700' : 'text-slate-600'}`}>
                  {isDbConnected ? `Connected (${systemDiagnostic?.database.active_dialect})` : 'PostgreSQL Unconnected'}
                </span>
              </div>
              {backendHealth.is_connected && (
                <>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">Service:</span>
                    <span className="text-slate-700 font-medium">{backendHealth.app_name}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">Latency:</span>
                    <span className="text-slate-700 font-medium">{backendHealth.latency_ms} ms</span>
                  </div>
                </>
              )}
              {!backendHealth.is_connected && (
                <div className="pt-1 text-[11px] text-slate-500 leading-snug">
                  Backend API is currently offline or warming up. Reconnecting to service...
                </div>
              )}
            </div>
          </div>

          {/* Immutable Audit Log Highlights */}
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-subtle p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-slate-600" />
                <h3 className="text-sm font-semibold text-slate-900">Governance Audit Trail</h3>
              </div>
              <span className="text-[10px] uppercase font-semibold tracking-wider text-teal-700 bg-teal-50 px-2 py-0.5 rounded border border-teal-200">
                Immutable
              </span>
            </div>

            {auditLogs.length > 0 ? (
              <div className="space-y-3">
                {auditLogs.slice(0, 3).map((log) => (
                  <div key={log.id} className="text-xs p-2.5 rounded-lg bg-slate-50 border border-slate-200/70">
                    <div className="flex items-center justify-between text-slate-700 font-medium">
                      <span className="truncate">{log.action_type.replace(/_/g, ' ')}</span>
                      <span className={`text-[10px] px-1.5 py-0.2 rounded font-semibold ${
                        log.actor_type === 'human'
                          ? 'bg-purple-100 text-purple-700'
                          : 'bg-slate-200 text-slate-700'
                      }`}>
                        {log.actor_type}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-500 mt-1">
                      Actor: <strong className="text-slate-700">{log.actor_name}</strong>
                    </div>
                    <div className="text-[10px] text-slate-400 mt-0.5">
                      {new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • Transition: {log.previous_status} → {log.new_status}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-4 rounded-lg bg-slate-50 border border-dashed border-slate-200 text-center">
                <Clock className="w-5 h-5 text-slate-400 mx-auto mb-1.5" />
                <p className="text-xs font-semibold text-slate-700">No Audit Events Recorded</p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  Human review decisions and governance transitions will be recorded here automatically.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
