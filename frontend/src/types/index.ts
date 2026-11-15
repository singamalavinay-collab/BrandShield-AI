export type NavigationTab =
  | 'dashboard'
  | 'guidelines'
  | 'submission'
  | 'analysis'
  | 'corrections'
  | 'review'
  | 'team';

export type RuleType =
  | 'tone_of_voice'
  | 'terminology'
  | 'formatting'
  | 'legal_regulatory'
  | 'prohibited_claims'
  | 'trademark_usage';

export type SeverityLevel = 'low' | 'medium' | 'high' | 'critical';

export type SubmissionStatus =
  | 'draft'
  | 'submitted'
  | 'analyzing'
  | 'violations_found'
  | 'passed_checks'
  | 'under_human_review'
  | 'approved'
  | 'rejected'
  | 'revision_requested';

export type UserRole = 'ADMIN' | 'REVIEWER' | 'CREATOR' | 'AUDITOR';

export interface AuthUser {
  id: string;
  organization_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  organization_name?: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterCredentials {
  full_name: string;
  email: string;
  password: string;
}

export interface OnboardCredentials {
  organization_name: string;
  full_name: string;
  email: string;
  password: string;
}

export interface AuthSession {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export interface OrganizationMember {
  id: string;
  organization_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  is_owner: boolean;
  created_at: string;
}

export type InvitationRole = 'CREATOR' | 'REVIEWER';
export type InvitationStatus = 'PENDING' | 'ACCEPTED' | 'REVOKED' | 'EXPIRED';

export interface TeamInvitation {
  id: string;
  organization_id: string;
  email: string;
  role: InvitationRole;
  status: InvitationStatus;
  inviter_id: string;
  inviter_name?: string | null;
  expires_at: string;
  accepted_at?: string | null;
  created_at: string;
  invitation_token?: string | null;
  invitation_link?: string | null;
  email_delivery_status?: string | null;
}

export interface CreateInvitationDTO {
  email: string;
  role: InvitationRole;
}

export interface InvitationValidationResponse {
  valid: boolean;
  email: string;
  role: InvitationRole;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  expires_at: string;
}

export interface AcceptInvitationDTO {
  token: string;
  full_name: string;
  password: string;
}

export type TargetChannel =
  | 'twitter_x'
  | 'linkedin'
  | 'email_newsletter'
  | 'blog_post'
  | 'advertisement'
  | 'press_release';

export type ReviewAction =
  | 'approve'
  | 'edit_and_approve'
  | 'reject'
  | 'request_revision';

export interface BrandGuideline {
  id: string;
  name: string;
  rule_type: RuleType;
  severity: SeverityLevel;
  description: string;
  directive: string;
  examples_approved: string[];
  examples_prohibited: string[];
  tags: string[];
  is_active: boolean;
  is_demo?: boolean;
}

export interface ContentSubmission {
  id: string;
  title: string;
  content: string;
  target_channel: TargetChannel;
  target_audience: string;
  status: SubmissionStatus;
  version: number;
  created_at: string;
  author_name: string;
  latest_review_id?: string;
  is_demo?: boolean;
}

export interface EvidenceCitation {
  id: string;
  violation_id: string;
  rule_id: string;
  rule_name: string;
  rule_type: RuleType;
  source_clause: string;
  document_name: string;
  confidence_score: number;
}

export interface CorrectionSuggestion {
  id: string;
  violation_id: string;
  suggested_text: string;
  rationale: string;
  source: 'ai_generated' | 'rule_derived' | 'human_edited';
  diff_summary?: string;
}

export interface RuleViolation {
  id: string;
  rule_id: string;
  rule_name: string;
  rule_type: RuleType;
  severity: SeverityLevel;
  flagged_text: string;
  char_start?: number;
  char_end?: number;
  explanation: string;
  evidence_citations: EvidenceCitation[];
  suggestions: CorrectionSuggestion[];
}

export interface RemediationSummary {
  total_violations: number;
  remediated_violations: number;
  unresolved_violations: number;
  is_fully_remediated: boolean;
  resolved_violation_ids?: string[];
  unresolved_violation_ids?: string[];
  corruptions?: string[];
}

export interface ComplianceReport {
  id: string;
  submission_id: string;
  submission_title: string;
  submission_version: number;
  is_compliant: boolean;
  total_violations: number;
  summary: string;
  analyzed_at: string;
  violations: RuleViolation[];
  remediated_draft?: string;
  remediation_summary?: RemediationSummary;
}

export interface ReviewDecision {
  id: string;
  submission_id: string;
  submission_version: number;
  reviewer_id: string;
  reviewer_name: string;
  reviewer_role: string;
  action: ReviewAction;
  feedback?: string;
  edited_content?: string;
  decided_at: string;
}

export interface AuditEntry {
  id: string;
  organization_name: string;
  submission_id: string;
  previous_status: SubmissionStatus;
  new_status: SubmissionStatus;
  action_type: string;
  actor_id: string;
  actor_type: 'human' | 'system' | 'ai';
  actor_name: string;
  notes?: string;
  timestamp: string;
}

export interface BackendHealth {
  status: string;
  app_name?: string;
  version?: string;
  environment?: string;
  timestamp?: string;
  latency_ms?: number;
  is_connected: boolean;
  error_message?: string;
}

export interface SystemDiagnostic {
  service: string;
  version: string;
  environment: string;
  database: {
    configured_url_type: string;
    active_dialect: string;
    connected: boolean;
    connection_error?: string | null;
  };
  governance: {
    human_in_the_loop_enforced: boolean;
    ai_approval_prohibited: boolean;
    audit_ledger_immutable: boolean;
  };
}

export interface CreateGuidelineDTO {
  name: string;
  rule_type: RuleType;
  severity: SeverityLevel;
  description: string;
  directive: string;
  examples_approved: string[];
  examples_prohibited: string[];
  tags: string[];
  is_active: boolean;
}

export interface CreateSubmissionDTO {
  title: string;
  content: string;
  target_channel: TargetChannel;
  target_audience?: string;
  metadata?: Record<string, unknown>;
  author_id?: string;
}

export interface ReviewDecisionDTO {
  action: ReviewAction;
  feedback?: string;
  edited_content?: string;
  override_reason?: string;
}

