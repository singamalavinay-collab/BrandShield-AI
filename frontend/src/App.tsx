import React, { useState, useEffect, useCallback } from 'react';
import {
  NavigationTab,
  ContentSubmission,
  BrandGuideline,
  ComplianceReport,
  AuditEntry,
  BackendHealth,
  SystemDiagnostic,
  ReviewAction,
  AuthUser,
} from './types';
import {
  INITIAL_GUIDELINES,
  INITIAL_SUBMISSIONS,
  INITIAL_REPORTS,
  INITIAL_AUDIT_LOGS,
} from './data/initialData';
import {
  checkBackendHealth,
  fetchSystemDiagnostic,
  fetchGuidelines,
  createGuideline,
  toggleGuidelineActive,
  fetchSubmissions,
  createSubmission,
  uploadSubmission,
  analyzeSubmission,
  fetchSubmissionReport,
  advanceSubmissionToReview,
  fetchAuditLogs,
  recordHumanReview,
  getCurrentUser,
  logout,
  ensureAuthenticatedSession,
} from './services/api';
import { Sidebar } from './components/layout/Sidebar';
import { Navbar } from './components/layout/Navbar';
import { LandingHeader } from './components/layout/LandingHeader';
import { LoginModal } from './components/auth/LoginModal';
import { InvitationAcceptModal } from './components/auth/InvitationAcceptModal';
import { parseCurrentRoute, scrubUrlToken, setHashRoute } from './services/router';

// Page components
import { LandingPage } from './pages/LandingPage';
import { DashboardPage } from './pages/DashboardPage';
import { GuidelinesPage } from './pages/GuidelinesPage';
import { SubmissionPage } from './pages/SubmissionPage';
import { AnalysisResultsPage } from './pages/AnalysisResultsPage';
import { CorrectionsPage } from './pages/CorrectionsPage';
import { ReviewPage } from './pages/ReviewPage';
import { TeamManagementPage } from './pages/TeamManagementPage';

export const App: React.FC = () => {
  // Navigation State
  const [currentTab, setCurrentTab] = useState<NavigationTab>('dashboard');
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  // Authentication State
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(() => getCurrentUser());
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false);
  const [authModalTab, setAuthModalTab] = useState<'signin' | 'register'>('signin');
  const [isDemoMode, setIsDemoMode] = useState<boolean>(false);

  // Invitation State (Security Rule 9: In-memory only, never persisted)
  const [invitationToken, setInvitationToken] = useState<string | null>(null);
  const [isInvitationModalOpen, setIsInvitationModalOpen] = useState(false);

  // Core Entity State - strictly decoupled: empty for unauthenticated/live, explicit for demo
  const [guidelines, setGuidelines] = useState<BrandGuideline[]>([]);
  const [submissions, setSubmissions] = useState<ContentSubmission[]>([]);
  const [reports, setReports] = useState<Record<string, ComplianceReport>>({});
  const [auditLogs, setAuditLogs] = useState<AuditEntry[]>([]);

  // Selection & Staging State
  const [selectedSubmissionId, setSelectedSubmissionId] = useState<string>('');
  const [stagedContent, setStagedContent] = useState<string | undefined>(undefined);

  // Clear all workspace state (prevents data cross-contamination)
  const clearWorkspaceState = useCallback(() => {
    setGuidelines([]);
    setSubmissions([]);
    setReports({});
    setAuditLogs([]);
    setSelectedSubmissionId('');
    setStagedContent(undefined);
    setInspectionError(null);
  }, []);

  // Explicitly populate demo presets (only in demo mode)
  const loadDemoState = useCallback(() => {
    setGuidelines(INITIAL_GUIDELINES);
    setSubmissions(INITIAL_SUBMISSIONS);
    setReports(INITIAL_REPORTS);
    setAuditLogs(INITIAL_AUDIT_LOGS);
    setSelectedSubmissionId(INITIAL_SUBMISSIONS[0]?.id || '');
    setStagedContent(undefined);
    setInspectionError(null);
  }, []);

  const openSignInModal = useCallback(() => {
    setAuthModalTab('signin');
    setIsLoginModalOpen(true);
    setHashRoute('login');
  }, []);

  const openRegisterModal = useCallback(() => {
    setAuthModalTab('register');
    setIsLoginModalOpen(true);
    setHashRoute('register');
  }, []);

  const handleEnterDemo = useCallback(() => {
    clearWorkspaceState();
    setCurrentUser(null);
    setIsDemoMode(true);
    loadDemoState();
    setHashRoute('demo');
  }, [clearWorkspaceState, loadDemoState]);

  const handleExitDemo = useCallback(() => {
    clearWorkspaceState();
    setIsDemoMode(false);
    setHashRoute('');
  }, [clearWorkspaceState]);

  // Hash routing & invitation token protection (Condition 9)
  useEffect(() => {
    const initRoute = () => {
      const route = parseCurrentRoute();
      if (route.params.token) {
        const token = route.params.token;
        // Scrub invitation token from URL immediately to prevent token leakage (Condition 9)
        scrubUrlToken();
        setInvitationToken(token);
        setIsInvitationModalOpen(true);
      }
      if (route.path === 'team') {
        setCurrentTab('team');
      }
      if (route.path === 'demo') {
        clearWorkspaceState();
        setIsDemoMode(true);
        loadDemoState();
      } else if (route.path === 'login' || route.path === 'signin') {
        setAuthModalTab('signin');
        setIsLoginModalOpen(true);
      } else if (route.path === 'register' || route.path === 'onboard') {
        setAuthModalTab('register');
        setIsLoginModalOpen(true);
      } else if (route.path === 'workspace') {
        if (!getCurrentUser()) {
          setHashRoute('');
        }
      }
    };

    initRoute();
    window.addEventListener('hashchange', initRoute);
    return () => window.removeEventListener('hashchange', initRoute);
  }, [openSignInModal, clearWorkspaceState, loadDemoState]);

  // Backend Health & Diagnostic State
  const [backendHealth, setBackendHealth] = useState<BackendHealth>({
    status: 'checking',
    is_connected: false,
  });
  const [systemDiagnostic, setSystemDiagnostic] = useState<SystemDiagnostic | null>(null);
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [inspectionError, setInspectionError] = useState<string | null>(null);

  // Auth event listeners
  useEffect(() => {
    const handleSessionUpdated = (e: Event) => {
      const customEvent = e as CustomEvent<AuthUser>;
      setCurrentUser(customEvent.detail);
    };
    const handleSessionCleared = () => {
      clearWorkspaceState();
      setCurrentUser(null);
    };

    window.addEventListener('auth:session-updated', handleSessionUpdated);
    window.addEventListener('auth:session-cleared', handleSessionCleared);

    return () => {
      window.removeEventListener('auth:session-updated', handleSessionUpdated);
      window.removeEventListener('auth:session-cleared', handleSessionCleared);
    };
  }, [clearWorkspaceState]);

  // Stateless logout: Discard local credentials and wipe all in-memory tenant state
  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      clearWorkspaceState();
      setCurrentUser(null);
      setIsDemoMode(false);
      setHashRoute('');
    }
  };

  // Refresh live immutable audit ledger from backend
  const refreshAuditLogs = useCallback(async () => {
    if (backendHealth.is_connected && currentUser && !isDemoMode) {
      try {
        const liveLogs = await fetchAuditLogs();
        if (liveLogs && Array.isArray(liveLogs)) {
          setAuditLogs(liveLogs);
        }
      } catch {
        // preserve current audit logs on network failure
      }
    }
  }, [backendHealth.is_connected, currentUser, isDemoMode]);

  // Refresh health and diagnostics
  const refreshBackendHealth = useCallback(async () => {
    setIsCheckingHealth(true);
    const health = await checkBackendHealth();
    setBackendHealth(health);

    if (health.is_connected) {
      try {
        const diag = await fetchSystemDiagnostic();
        setSystemDiagnostic(diag);

        // Fetch live guidelines and submissions ONLY if user is authenticated (Requirement 5)
        if (diag.database.connected && currentUser) {
          try {
            const liveGuidelines = await fetchGuidelines();
            setGuidelines(liveGuidelines);

            const liveSubmissions = await fetchSubmissions();
            setSubmissions(liveSubmissions);

            if (liveSubmissions.length > 0) {
              setSelectedSubmissionId((prev) =>
                prev && liveSubmissions.some((s) => s.id === prev) ? prev : liveSubmissions[0].id
              );
            } else {
              setSelectedSubmissionId('');
              setReports({});
            }

            // Also refresh audit logs
            const liveLogs = await fetchAuditLogs();
            if (liveLogs && Array.isArray(liveLogs)) {
              setAuditLogs(liveLogs);
            }
          } catch {
            // Live data fetch failed; maintain current state
          }
        }
      } catch {
        setSystemDiagnostic(null);
      }
    } else {
      setSystemDiagnostic(null);
    }

    setIsCheckingHealth(false);
  }, [currentUser]);

  useEffect(() => {
    refreshBackendHealth();
  }, [refreshBackendHealth]);

  // Auto-refresh audit ledger whenever user views dashboard
  useEffect(() => {
    if (currentTab === 'dashboard') {
      refreshAuditLogs();
    }
  }, [currentTab, refreshAuditLogs]);

  // Guidelines Handlers
  const handleToggleGuidelineActive = async (id: string) => {
    const target = guidelines.find((g) => g.id === id);

    // If connected and it's a live database guideline (UUID format)
    if (backendHealth.is_connected && target && !target.is_demo) {
      try {
        const updated = await toggleGuidelineActive(id);
        setGuidelines((prev) => prev.map((g) => (g.id === id ? updated : g)));
        return;
      } catch {
        // Fall back to local state toggle if API fails
      }
    }

    // Local state toggle
    setGuidelines((prev) =>
      prev.map((g) => (g.id === id ? { ...g, is_active: !g.is_active } : g))
    );
  };

  const handleAddGuideline = async (newGuideline: Omit<BrandGuideline, 'id'>) => {
    if (backendHealth.is_connected && systemDiagnostic?.database.connected) {
      try {
        const created = await createGuideline({
          name: newGuideline.name,
          rule_type: newGuideline.rule_type,
          severity: newGuideline.severity,
          description: newGuideline.description,
          directive: newGuideline.directive,
          examples_approved: newGuideline.examples_approved,
          examples_prohibited: newGuideline.examples_prohibited,
          tags: newGuideline.tags,
          is_active: newGuideline.is_active,
        });
        setGuidelines((prev) => [{ ...created, is_demo: false }, ...prev]);
        return;
      } catch (err: unknown) {
        console.error('API create guideline failed, falling back to local state:', err);
      }
    }

    // Local state fallback
    const id = `g-${Date.now().toString().slice(-4)}`;
    setGuidelines((prev) => [{ ...newGuideline, id, is_demo: false }, ...prev]);
  };

  // Submission Handlers
  const handleSubmitContent = async (
    newSub: Omit<ContentSubmission, 'id' | 'created_at' | 'version' | 'status'>,
    shouldInspect: boolean,
    existingDraftId?: string | null
  ): Promise<ContentSubmission | null> => {
    setInspectionError(null);
    let createdSubmission: ContentSubmission | null = null;

    if (existingDraftId && shouldInspect) {
      if (backendHealth.is_connected && systemDiagnostic?.database.connected) {
        try {
          setIsAnalyzing(true);
          const analyzedSub = await analyzeSubmission(existingDraftId);
          setSubmissions((prev) =>
            prev.map((s) => (s.id === existingDraftId ? { ...s, status: analyzedSub.status } : s))
          );
          setSelectedSubmissionId(existingDraftId);
          const report = await fetchSubmissionReport(existingDraftId);
          setReports((prev) => ({ ...prev, [existingDraftId]: report }));
          setInspectionError(null);
          await refreshAuditLogs();
          setCurrentTab('analysis');
          return analyzedSub;
        } catch (err: unknown) {
          console.error('Automated compliance inspection on existing draft failed:', err);
          setInspectionError(
            err instanceof Error ? err.message : 'Automated compliance inspection failed.'
          );
        } finally {
          setIsAnalyzing(false);
        }
      }
    }

    if (backendHealth.is_connected && systemDiagnostic?.database.connected) {
      const token = ensureAuthenticatedSession();
      if (!token && shouldInspect) {
        setInspectionError('Authentication required: Please sign in or create an account to submit content for compliance evaluation.');
        setIsLoginModalOpen(true);
        return null;
      }
      try {
        createdSubmission = await createSubmission(
          {
            title: newSub.title,
            content: newSub.content,
            target_channel: newSub.target_channel,
            target_audience: newSub.target_audience,
            metadata: {},
            // Server-authoritative ownership: Client cannot specify author_id (legacy: author_id: currentUser ? currentUser.full_name : newSub.author_name)
          },
          shouldInspect
        );
      } catch (err: unknown) {
        console.error('API create submission failed, falling back to local state:', err);
        setInspectionError(err instanceof Error ? err.message : 'API create submission failed');
      }
    } else if (backendHealth.is_connected && !systemDiagnostic?.database.connected) {
      setInspectionError(
        'Database service is offline. Content staged locally, but automated inspection requires an active database.'
      );
    }

    if (!createdSubmission) {
      const newId = `sub-${Date.now().toString().slice(-4)}`;
      const status = shouldInspect ? 'submitted' : 'draft';

      createdSubmission = {
        ...newSub,
        id: newId,
        status,
        version: 1,
        created_at: new Date().toISOString(),
        author_name: currentUser ? currentUser.full_name : (newSub.author_name || 'Unknown author'),
        is_demo: false,
      };
    }

    const submissionId = createdSubmission.id;
    setSubmissions((prev) => [createdSubmission!, ...prev.filter((s) => s.id !== submissionId)]);
    setSelectedSubmissionId(submissionId);

    // If submitting for inspection, run compliance engine and fetch report
    if (shouldInspect) {
      if (backendHealth.is_connected && systemDiagnostic?.database.connected) {
        try {
          setIsAnalyzing(true);
          const analyzedSub = await analyzeSubmission(submissionId);
          createdSubmission.status = analyzedSub.status;
          setSubmissions((prev) =>
            prev.map((s) => (s.id === submissionId ? { ...s, status: analyzedSub.status } : s))
          );
          const report = await fetchSubmissionReport(submissionId);
          setReports((prev) => ({ ...prev, [submissionId]: report }));
          setInspectionError(null);
          await refreshAuditLogs();
        } catch (err: unknown) {
          console.error('Automated compliance inspection failed:', err);
          setInspectionError(
            err instanceof Error ? err.message : 'Automated compliance inspection failed.'
          );
        } finally {
          setIsAnalyzing(false);
        }
      } else {
        // Fallback local audit entry only when offline / disconnected from DB
        const audit: AuditEntry = {
          id: `aud-${Date.now().toString().slice(-4)}`,
          organization_name: 'BrandShield Primary Org',
          submission_id: submissionId,
          previous_status: 'draft',
          new_status: createdSubmission.status,
          action_type: 'content_submission',
          actor_id: 'usr-author',
          actor_type: 'human',
          actor_name: newSub.author_name,
          notes: 'Submitted draft for brand compliance inspection and governance sign-off.',
          timestamp: new Date().toISOString(),
        };
        setAuditLogs((prev) => [audit, ...prev]);
      }

      // Navigate to analysis results
      setCurrentTab('analysis');
    }

    return createdSubmission;
  };

  const handleUploadSubmission = async (
    formData: FormData,
    metadata: {
      title: string;
      target_channel: any;
      target_audience?: string;
      media_type: any;
      content?: string;
      author_name: string;
    },
    shouldInspect: boolean
  ) => {
    setInspectionError(null);
    let createdSubmission: ContentSubmission | null = null;

    if (backendHealth.is_connected && systemDiagnostic?.database.connected) {
      const token = ensureAuthenticatedSession();
      if (!token && shouldInspect) {
        setInspectionError(
          'Authentication required: Please sign in or create an account to submit content for compliance evaluation.'
        );
        setIsLoginModalOpen(true);
        return;
      }
      try {
        setIsAnalyzing(shouldInspect);
        createdSubmission = await uploadSubmission(formData, shouldInspect);
      } catch (err: unknown) {
        console.error('API upload submission failed, falling back to local state:', err);
        setInspectionError(err instanceof Error ? err.message : 'API upload submission failed');
      } finally {
        setIsAnalyzing(false);
      }
    } else if (backendHealth.is_connected && !systemDiagnostic?.database.connected) {
      setInspectionError(
        'Database service is offline. Media draft staged locally, but automated inspection requires an active database.'
      );
    }

    if (!createdSubmission) {
      const newId = `sub-upload-${Date.now().toString().slice(-4)}`;
      const status = shouldInspect ? 'submitted' : 'draft';

      createdSubmission = {
        id: newId,
        title: metadata.title,
        content: metadata.content || `[${String(metadata.media_type).toUpperCase()} asset: staged locally]`,
        target_channel: metadata.target_channel,
        target_audience: metadata.target_audience || 'General Enterprise Audience',
        status,
        version: 1,
        created_at: new Date().toISOString(),
        author_name: currentUser ? currentUser.full_name : (metadata.author_name || 'Unknown author'),
        is_demo: isDemoMode,
        media_type: metadata.media_type,
        multimodal_metadata: {
          processing_status: 'completed',
          media_type: metadata.media_type,
        },
      };
    }

    const submissionId = createdSubmission.id;
    setSubmissions((prev) => [createdSubmission!, ...prev.filter((s) => s.id !== submissionId)]);
    setSelectedSubmissionId(submissionId);

    // If submitting for inspection, fetch report and record audit log
    if (shouldInspect) {
      if (backendHealth.is_connected && systemDiagnostic?.database.connected) {
        try {
          setIsAnalyzing(true);
          const report = await fetchSubmissionReport(submissionId);
          setReports((prev) => ({ ...prev, [submissionId]: report }));
          setInspectionError(null);
          await refreshAuditLogs();
        } catch (err: unknown) {
          console.error('Fetching compliance report failed:', err);
        } finally {
          setIsAnalyzing(false);
        }
      } else {
        // Fallback local audit entry only when offline / disconnected from DB
        const audit: AuditEntry = {
          id: `aud-${Date.now().toString().slice(-4)}`,
          organization_name: 'BrandShield Primary Org',
          submission_id: submissionId,
          previous_status: 'draft',
          new_status: createdSubmission.status,
          action_type: 'upload_multimodal_content',
          actor_id: 'usr-author',
          actor_type: 'human',
          actor_name: metadata.author_name,
          notes: `Submitted ${metadata.media_type} draft for brand compliance inspection and governance sign-off.`,
          timestamp: new Date().toISOString(),
        };
        setAuditLogs((prev) => [audit, ...prev]);
      }

      // Navigate to analysis results
      setCurrentTab('analysis');
    }

    return createdSubmission;
  };

  // Trigger analysis on an existing submission
  const handleTriggerAnalysis = async (submissionId: string) => {
    setInspectionError(null);

    if (!backendHealth.is_connected || !systemDiagnostic?.database.connected) {
      setInspectionError(
        'Cannot run compliance inspection: Database service is offline. Please verify database connection.'
      );
      return;
    }

    const token = ensureAuthenticatedSession();
    if (!token) {
      setInspectionError('Authentication required: Please sign in to trigger compliance inspection.');
      setIsLoginModalOpen(true);
      return;
    }

    try {
      setIsAnalyzing(true);
      const analyzedSub = await analyzeSubmission(submissionId);
      setSubmissions((prev) =>
        prev.map((s) => (s.id === submissionId ? { ...s, status: analyzedSub.status } : s))
      );
      const report = await fetchSubmissionReport(submissionId);
      setReports((prev) => ({ ...prev, [submissionId]: report }));
      setInspectionError(null);
      await refreshAuditLogs();
    } catch (err: unknown) {
      console.error('Compliance inspection failed:', err);
      setInspectionError(
        err instanceof Error ? err.message : 'Compliance inspection failed during execution.'
      );
    } finally {
      setIsAnalyzing(false);
    }
  };

  // Review Decision Handler (Human in the loop authorization)
  const handleRecordDecision = async (
    submissionId: string,
    action: ReviewAction,
    feedback: string,
    editedContent?: string,
    overrideReason?: string
  ) => {
    const targetSub = submissions.find((s) => s.id === submissionId);

    if (backendHealth.is_connected && targetSub && !targetSub.is_demo) {
      try {
        const result = await recordHumanReview(submissionId, {
          action,
          feedback,
          edited_content: editedContent,
          override_reason: overrideReason,
        });

        // Update submission with server result
        setSubmissions((prev) =>
          prev.map((s) =>
            s.id === submissionId
              ? {
                  ...s,
                  status: result.submission.status as ContentSubmission['status'],
                  version: result.submission.version,
                  content: result.submission.content,
                  latest_review_id: result.submission.latest_review_id,
                }
              : s
          )
        );

        // Add real server audit entry
        const serverAudit: AuditEntry = {
          id: result.audit_entry_id,
          organization_name: 'BrandShield Primary Org',
          submission_id: submissionId,
          previous_status: 'under_human_review',
          new_status: result.submission.status as ContentSubmission['status'],
          action_type: `human_review_${action}`,
          actor_id: currentUser ? currentUser.id : 'usr-human',
          actor_type: 'human',
          actor_name: result.decision.reviewer_name,
          notes: (overrideReason ? `[Override: ${overrideReason}] ` : '') + (feedback || `Human decision authorized: ${action.replace(/_/g, ' ')}`),
          timestamp: result.decision.decided_at,
        };
        setAuditLogs((prev) => [serverAudit, ...prev]);
        await refreshAuditLogs();
        return;
      } catch (err: unknown) {
        console.error('API record human review failed, falling back to local commit:', err);
        throw err;
      }
    }

    // Local fallback for demo submissions or offline mode
    let newStatus: ContentSubmission['status'] = 'under_human_review';
    if (action === 'approve' || action === 'edit_and_approve') {
      newStatus = 'approved';
    } else if (action === 'reject') {
      newStatus = 'rejected';
    } else if (action === 'request_revision') {
      newStatus = 'revision_requested';
    }

    setSubmissions((prev) =>
      prev.map((s) => {
        if (s.id === submissionId) {
          return {
            ...s,
            status: newStatus,
            content: editedContent || s.content,
            version: action === 'edit_and_approve' ? s.version + 1 : s.version,
          };
        }
        return s;
      })
    );

    const newAudit: AuditEntry = {
      id: `aud-${Date.now().toString().slice(-4)}`,
      organization_name: 'BrandShield Primary Org',
      submission_id: submissionId,
      previous_status: 'under_human_review',
      new_status: newStatus,
      action_type: `human_review_${action}`,
      actor_id: currentUser ? currentUser.id : 'usr-reviewer',
      actor_type: 'human',
      actor_name: currentUser ? `${currentUser.full_name} (${currentUser.role})` : 'Authorized Human Reviewer',
      notes: (overrideReason ? `[Override: ${overrideReason}] ` : '') + (feedback || `Human decision authorized: ${action.replace(/_/g, ' ')}`),
      timestamp: new Date().toISOString(),
    };

    setAuditLogs((prev) => [newAudit, ...prev]);
  };

  // Advance submission to human review queue
  const handleAdvanceToReview = async (submissionId: string, contentToStage?: string) => {
    if (contentToStage) {
      setStagedContent(contentToStage);
    }
    const targetSub = submissions.find((s) => s.id === submissionId);
    if (backendHealth.is_connected && targetSub && !targetSub.is_demo) {
      try {
        const updated = await advanceSubmissionToReview(submissionId);
        setSubmissions((prev) =>
          prev.map((s) =>
            s.id === submissionId
              ? {
                  ...s,
                  status: updated.status as ContentSubmission['status'],
                }
              : s
          )
        );
        await refreshAuditLogs();
      } catch (err: unknown) {
        console.error('Failed to advance submission to review:', err);
      }
    } else {
      // Local fallback for demo submissions
      setSubmissions((prev) =>
        prev.map((s) => (s.id === submissionId ? { ...s, status: 'under_human_review' } : s))
      );
    }
    setSelectedSubmissionId(submissionId);
    setCurrentTab('review');
  };

  // Auto-fetch compliance report when selected submission changes and report is missing
  useEffect(() => {
    if (
      selectedSubmissionId &&
      !reports[selectedSubmissionId] &&
      backendHealth.is_connected &&
      currentUser &&
      !isDemoMode
    ) {
      const sub = submissions.find((s) => s.id === selectedSubmissionId);
      if (
        sub &&
        !sub.is_demo &&
        (sub.status === 'violations_found' ||
          sub.status === 'passed_checks' ||
          sub.status === 'under_human_review' ||
          sub.status === 'approved' ||
          sub.status === 'rejected')
      ) {
        fetchSubmissionReport(selectedSubmissionId)
          .then((rep) => {
            if (rep) {
              setReports((prev) => ({ ...prev, [selectedSubmissionId]: rep }));
            }
          })
          .catch(() => {
            // report not yet generated or inspection pending
          });
      }
    }
  }, [selectedSubmissionId, reports, backendHealth.is_connected, currentUser, isDemoMode, submissions]);

  // Navigation metadata
  const pageMeta: Record<NavigationTab, { title: string; description: string }> = {
    dashboard: {
      title: 'Brand Governance Overview',
      description: 'System metrics, active guidelines, and active compliance review queue.',
    },
    guidelines: {
      title: 'Brand Guidelines Knowledge Hub',
      description: 'Approved brand directives, legal rules, and messaging requirements.',
    },
    submission: {
      title: 'Content Submission Workspace',
      description: 'Compose and submit marketing copy for brand compliance verification.',
    },
    analysis: {
      title: 'Compliance Inspection Results',
      description: 'Granular violation detection, cited clauses, and confidence scoring.',
    },
    corrections: {
      title: 'Evidence-Backed Correction Studio',
      description: 'Side-by-side comparison of original text and AI remediation proposals.',
    },
    review: {
      title: 'Human Review & Authorization Console',
      description: 'Mandatory human approval gate. AI suggests; humans authorize.',
    },
    team: {
      title: 'Team & Access Governance',
      description: 'Manage organization members, assign roles, and dispatch single-use invitations.',
    },
  };

  const pendingReviewsCount = submissions.filter((s) => s.status === 'under_human_review').length;
  const currentReport = reports[selectedSubmissionId];
  const violationsCount = currentReport ? currentReport.violations.length : 0;

  // Unauthenticated Public Landing Page View
  if (!currentUser && !isDemoMode) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col antialiased text-slate-900">
        <LandingHeader
          backendHealth={backendHealth}
          onOpenLogin={openSignInModal}
          onOpenRegister={openRegisterModal}
          onEnterDemo={handleEnterDemo}
        />

        <LandingPage
          backendHealth={backendHealth}
          onOpenLogin={openSignInModal}
          onOpenRegister={openRegisterModal}
          onEnterDemo={handleEnterDemo}
        />

        {/* Human Authentication Modal */}
        <LoginModal
          isOpen={isLoginModalOpen}
          initialTab={authModalTab}
          onClose={() => setIsLoginModalOpen(false)}
          onLoginSuccess={(user) => {
            clearWorkspaceState();
            setCurrentUser(user);
            setIsDemoMode(false);
            setHashRoute('workspace');
          }}
        />

        {/* Invitation Acceptance Modal */}
        <InvitationAcceptModal
          isOpen={isInvitationModalOpen}
          token={invitationToken}
          onClose={() => {
            setIsInvitationModalOpen(false);
            setInvitationToken(null);
          }}
          onAcceptSuccess={(session) => {
            clearWorkspaceState();
            setCurrentUser(session.user);
            setIsDemoMode(false);
            setHashRoute('workspace');
          }}
          onSwitchToLogin={openSignInModal}
        />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col md:flex-row antialiased text-slate-900">
      {/* Sidebar Navigation */}
      <Sidebar
        currentTab={currentTab}
        onSelectTab={setCurrentTab}
        pendingReviewsCount={pendingReviewsCount}
        violationsCount={violationsCount}
        guidelinesCount={guidelines.length}
        isMobileOpen={isMobileMenuOpen}
        onCloseMobile={() => setIsMobileMenuOpen(false)}
        currentUser={currentUser}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Demonstration Sandbox Notice Banner */}
        {isDemoMode && (
          <div className="bg-gradient-to-r from-blue-700 via-indigo-700 to-blue-800 text-white px-4 py-2 text-xs font-medium flex items-center justify-between gap-3 shadow-sm z-30 sticky top-0">
            <div className="flex items-center gap-2 min-w-0">
              <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse flex-shrink-0" />
              <strong className="font-bold tracking-wide flex-shrink-0">Interactive Demonstration Sandbox</strong>
              <span className="hidden md:inline text-blue-200 truncate">
                | Exploring pre-seeded brand guidelines and sample drafts. Actions in sandbox mode do not alter production database records.
              </span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={handleExitDemo}
                className="px-2.5 py-1 rounded bg-white/10 hover:bg-white/20 text-white font-semibold transition"
              >
                Exit Demo
              </button>
              <button
                onClick={openSignInModal}
                className="px-2.5 py-1 rounded bg-white text-blue-900 font-bold hover:bg-blue-50 transition"
              >
                Sign In
              </button>
              <button
                onClick={openRegisterModal}
                className="px-2.5 py-1 rounded bg-blue-500 text-white font-bold hover:bg-blue-400 transition"
              >
                Register
              </button>
            </div>
          </div>
        )}

        <Navbar
          title={pageMeta[currentTab].title}
          description={pageMeta[currentTab].description}
          backendHealth={backendHealth}
          systemDiagnostic={systemDiagnostic}
          currentUser={currentUser}
          isCheckingHealth={isCheckingHealth}
          onRefreshHealth={refreshBackendHealth}
          onToggleMobileMenu={() => setIsMobileMenuOpen(true)}
          onOpenLogin={openSignInModal}
          onLogout={handleLogout}
        />

        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl w-full mx-auto">
          {currentTab === 'dashboard' && (
            <DashboardPage
              onNavigate={setCurrentTab}
              submissions={submissions}
              guidelines={guidelines}
              auditLogs={auditLogs}
              backendHealth={backendHealth}
              systemDiagnostic={systemDiagnostic}
              isCheckingHealth={isCheckingHealth}
              onRefreshHealth={refreshBackendHealth}
              onSelectSubmissionForAnalysis={(id) => {
                setSelectedSubmissionId(id);
                setCurrentTab('analysis');
              }}
              onSelectSubmissionForReview={(id) => {
                setSelectedSubmissionId(id);
                setCurrentTab('review');
              }}
            />
          )}

          {currentTab === 'guidelines' && (
            <GuidelinesPage
              guidelines={guidelines}
              onToggleActive={handleToggleGuidelineActive}
              onAddGuideline={handleAddGuideline}
              currentUser={currentUser}
            />
          )}

          {currentTab === 'submission' && (
            <SubmissionPage
              onSubmitContent={handleSubmitContent}
              onSubmitUpload={handleUploadSubmission}
              dbOffline={backendHealth.is_connected && !systemDiagnostic?.database.connected}
              currentUser={currentUser}
            />
          )}

          {currentTab === 'analysis' && (
            <AnalysisResultsPage
              onNavigate={setCurrentTab}
              submissions={submissions}
              selectedSubmissionId={selectedSubmissionId}
              onSelectSubmission={setSelectedSubmissionId}
              reports={reports}
              onTriggerAnalysis={handleTriggerAnalysis}
              isAnalyzing={isAnalyzing}
              inspectionError={inspectionError}
              dbOffline={backendHealth.is_connected && !systemDiagnostic?.database.connected}
              onAdvanceToReview={handleAdvanceToReview}
            />
          )}

          {currentTab === 'corrections' && (
            <CorrectionsPage
              onNavigate={setCurrentTab}
              submissions={submissions}
              selectedSubmissionId={selectedSubmissionId}
              reports={reports}
              onStageRemediatedContent={(content) => {
                setStagedContent(content);
              }}
              onAdvanceToReview={handleAdvanceToReview}
            />
          )}

          {currentTab === 'review' && (
            <ReviewPage
              onNavigate={setCurrentTab}
              submissions={submissions}
              selectedSubmissionId={selectedSubmissionId}
              onSelectSubmission={setSelectedSubmissionId}
              reports={reports}
              stagedContent={stagedContent}
              currentUser={currentUser}
              onOpenLogin={() => setIsLoginModalOpen(true)}
              onRecordDecision={handleRecordDecision}
              onAdvanceToReview={handleAdvanceToReview}
            />
          )}

          {currentTab === 'team' && (
            <TeamManagementPage
              currentUser={currentUser}
              onNavigateHome={() => setCurrentTab('dashboard')}
            />
          )}
        </main>

        {/* Global Footer */}
        <footer className="mt-auto py-4 px-6 border-t border-slate-200/80 bg-white text-xs text-slate-500 flex flex-col sm:flex-row items-center justify-between gap-2">
          <div>
            <strong className="font-semibold text-slate-700">BrandShield AI</strong> — Enterprise Brand Governance & Safety Platform
          </div>
          <div className="flex items-center gap-4 text-[11px] text-slate-400">
            <span>CodeNova India 2026</span>
            <span>•</span>
            <span>Human-in-the-Loop Architecture</span>
            <span>•</span>
            <span>FastAPI + React Integration</span>
          </div>
        </footer>
      </div>

      {/* Human Authentication Modal */}
      <LoginModal
        isOpen={isLoginModalOpen}
        initialTab={authModalTab}
        onClose={() => setIsLoginModalOpen(false)}
        onLoginSuccess={(user) => {
          clearWorkspaceState();
          setCurrentUser(user);
          setIsDemoMode(false);
          setHashRoute('workspace');
        }}
      />

      {/* Invitation Acceptance Modal */}
      <InvitationAcceptModal
        isOpen={isInvitationModalOpen}
        token={invitationToken}
        onClose={() => {
          setIsInvitationModalOpen(false);
          setInvitationToken(null);
        }}
        onAcceptSuccess={(session) => {
          clearWorkspaceState();
          setCurrentUser(session.user);
          setIsDemoMode(false);
          setHashRoute('workspace');
        }}
        onSwitchToLogin={openSignInModal}
      />
    </div>
  );
};

export default App;
