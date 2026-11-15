import React, { useState, useEffect, useCallback } from 'react';
import {
  Users,
  UserPlus,
  Mail,
  Shield,
  ShieldAlert,
  Clock,
  CheckCircle2,
  XCircle,
  Copy,
  Check,
  Trash2,
  RefreshCw,
  AlertCircle,
  Lock,
  Building2,
  UserCheck,
} from 'lucide-react';
import { createInvitation, listInvitations, revokeInvitation, fetchOrganizationMembers } from '../services/api';
import type { AuthUser, TeamInvitation, InvitationRole, OrganizationMember } from '../types';

interface TeamManagementPageProps {
  currentUser: AuthUser | null;
  onNavigateHome?: () => void;
}

export const TeamManagementPage: React.FC<TeamManagementPageProps> = ({
  currentUser,
  onNavigateHome,
}) => {
  const isAdmin = currentUser?.role === 'ADMIN';

  const [invitations, setInvitations] = useState<TeamInvitation[]>([]);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Invite modal state
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<InvitationRole>('CREATOR');
  const [isSubmittingInvite, setIsSubmittingInvite] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [newlyCreatedInvite, setNewlyCreatedInvite] = useState<TeamInvitation | null>(null);
  const [hasCopiedLink, setHasCopiedLink] = useState(false);

  // Revoke confirmation modal state
  const [revokingInvitation, setRevokingInvitation] = useState<TeamInvitation | null>(null);
  const [isRevoking, setIsRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const loadInvitations = useCallback(async () => {
    if (!isAdmin) return;
    setIsLoading(true);
    setError(null);
    try {
      const [invData, memData] = await Promise.all([
        listInvitations(),
        fetchOrganizationMembers(),
      ]);
      setInvitations(invData);
      setMembers(memData);
    } catch (err: any) {
      setError(err?.message || 'Failed to retrieve organization data.');
    } finally {
      setIsLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    if (isAdmin) {
      loadInvitations();
    }
  }, [isAdmin, loadInvitations]);

  // Access Control Guard: Non-ADMIN users cannot access Team Management
  if (!currentUser || !isAdmin) {
    return (
      <div className="max-w-4xl mx-auto py-12 px-4 sm:px-6">
        <div className="p-8 rounded-2xl bg-slate-900 border border-slate-800 text-center">
          <div className="w-16 h-16 rounded-2xl bg-amber-950/60 border border-amber-800/60 flex items-center justify-center mx-auto mb-4 text-amber-400">
            <ShieldAlert className="w-8 h-8 text-amber-400" />
          </div>
          <h2 className="text-xl font-bold text-white tracking-tight">Administrative Privileges Required</h2>
          <p className="text-sm text-slate-400 max-w-md mx-auto mt-2 leading-relaxed">
            Team management, role assignment, and member invitations are restricted to Organization Administrators (ADMIN).
            Your current role is <span className="font-semibold text-slate-200">{currentUser?.role || 'UNAUTHENTICATED'}</span>.
          </p>
          {onNavigateHome && (
            <div className="mt-6">
              <button
                onClick={onNavigateHome}
                className="py-2.5 px-5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition"
              >
                Return to Dashboard
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Derived invitation subsets
  const pendingInvitations = invitations.filter((inv) => inv.status === 'PENDING');
  const acceptedInvitations = invitations.filter((inv) => inv.status === 'ACCEPTED');
  const historyInvitations = invitations.filter((inv) => inv.status === 'REVOKED' || inv.status === 'EXPIRED');

  // Stats calculation based on actual organization members when available, with fallback to invitations
  const hasLiveMembers = members.length > 0;
  const totalMemberCount = hasLiveMembers ? members.length : acceptedInvitations.length + 1;
  const totalReviewers = hasLiveMembers
    ? members.filter((m) => m.role === 'REVIEWER').length
    : acceptedInvitations.filter((i) => i.role === 'REVIEWER').length;
  const totalCreators = hasLiveMembers
    ? members.filter((m) => m.role === 'CREATOR').length
    : acceptedInvitations.filter((i) => i.role === 'CREATOR').length;

  const handleCreateInviteSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setInviteError(null);
    setNewlyCreatedInvite(null);

    const cleanEmail = inviteEmail.trim().toLowerCase();
    if (!cleanEmail) {
      setInviteError('Please provide a valid email address.');
      return;
    }

    setIsSubmittingInvite(true);
    try {
      const invite = await createInvitation({
        email: cleanEmail,
        role: inviteRole,
      });
      setNewlyCreatedInvite(invite);
      setInviteEmail('');
      await loadInvitations();
    } catch (err: any) {
      setInviteError(err?.message || 'Failed to dispatch team invitation.');
    } finally {
      setIsSubmittingInvite(false);
    }
  };

  const handleRevokeConfirm = async () => {
    if (!revokingInvitation) return;
    setIsRevoking(true);
    setRevokeError(null);
    try {
      await revokeInvitation(revokingInvitation.id);
      setRevokingInvitation(null);
      await loadInvitations();
    } catch (err: any) {
      setRevokeError(err?.message || 'Failed to revoke invitation.');
    } finally {
      setIsRevoking(false);
    }
  };

  const copyInvitationLink = (tokenOrLink: string | null | undefined) => {
    if (!tokenOrLink) return;
    let url = tokenOrLink;
    if (!tokenOrLink.startsWith('http')) {
      const baseUrl = window.location.origin + window.location.pathname;
      url = `${baseUrl}#/invite?token=${tokenOrLink}`;
    }
    navigator.clipboard.writeText(url);
    setHasCopiedLink(true);
    setTimeout(() => setHasCopiedLink(false), 2000);
  };

  const formatDate = (isoStr: string | null | undefined) => {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
    } catch {
      return isoStr;
    }
  };

  const formatExpires = (isoStr: string) => {
    try {
      const now = new Date();
      const exp = new Date(isoStr);
      const diffDays = Math.ceil((exp.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
      if (diffDays <= 0) return 'Expired';
      if (diffDays === 1) return 'Expires tomorrow';
      return `Expires in ${diffDays} days`;
    } catch {
      return formatDate(isoStr);
    }
  };

  const renderRoleBadge = (role: string) => {
    if (role === 'ADMIN') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-950 text-amber-300 border border-amber-800/60">
          <Shield className="w-3 h-3 text-amber-400" />
          <span>ADMIN</span>
        </span>
      );
    }
    if (role === 'REVIEWER') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-purple-950 text-purple-300 border border-purple-800/60">
          <UserCheck className="w-3 h-3 text-purple-400" />
          <span>REVIEWER</span>
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-blue-950 text-blue-300 border border-blue-800/60">
        <Users className="w-3 h-3 text-blue-400" />
        <span>CREATOR</span>
      </span>
    );
  };

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 sm:px-6 lg:px-8 space-y-8 animate-fade-in">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-2 text-teal-400 text-xs font-medium tracking-wide uppercase">
            <Building2 className="w-3.5 h-3.5" />
            <span>{currentUser.organization_name || 'Organization Workspace'}</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight mt-1">Team & Access Governance</h1>
          <p className="text-sm text-slate-400 mt-1 max-w-xl">
            Manage organization members, assign roles, and dispatch single-use invitations.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={loadInvitations}
            disabled={isLoading}
            className="p-2.5 rounded-lg border border-slate-700 bg-slate-800 text-slate-300 hover:text-white hover:bg-slate-700 transition"
            title="Refresh member lists"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-blue-400' : ''}`} />
          </button>

          <button
            onClick={() => {
              setNewlyCreatedInvite(null);
              setInviteError(null);
              setIsInviteModalOpen(true);
            }}
            className="flex items-center gap-2 py-2.5 px-4 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs transition shadow-sm"
          >
            <UserPlus className="w-4 h-4" />
            <span>Invite Team Member</span>
          </button>
        </div>
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs text-slate-400">Total Active Members</div>
          <div className="text-2xl font-bold text-white mt-1">{totalMemberCount}</div>
          <div className="text-[11px] text-teal-400 mt-1">
            {hasLiveMembers
              ? `${members.filter((m) => m.is_owner || m.role === 'ADMIN').length} Admin/Owner + ${members.filter((m) => m.role !== 'ADMIN' && !m.is_owner).length} Members`
              : `1 Admin + ${acceptedInvitations.length} Invited`}
          </div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs text-slate-400">Pending Invitations</div>
          <div className="text-2xl font-bold text-amber-400 mt-1">{pendingInvitations.length}</div>
          <div className="text-[11px] text-slate-400 mt-1">Awaiting acceptance</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs text-slate-400">Compliance Reviewers</div>
          <div className="text-2xl font-bold text-purple-400 mt-1">{totalReviewers}</div>
          <div className="text-[11px] text-slate-400 mt-1">Authorized human approvers</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs text-slate-400">Content Creators</div>
          <div className="text-2xl font-bold text-blue-400 mt-1">{totalCreators}</div>
          <div className="text-[11px] text-slate-400 mt-1">Content authors & drafters</div>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-4 rounded-xl bg-red-950/60 border border-red-800/60 text-xs text-red-300 flex items-start gap-3">
          <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <span className="font-semibold text-red-200">Unable to load team data:</span> {error}
          </div>
          <button onClick={loadInvitations} className="text-red-300 hover:text-white underline font-semibold">
            Retry
          </button>
        </div>
      )}

      {/* Section 1: Active Pending Invitations */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-amber-400" />
            <h2 className="text-base font-semibold text-white tracking-tight">
              Pending Invitations ({pendingInvitations.length})
            </h2>
          </div>
          <span className="text-xs text-slate-400">Invitations expire 7 days after creation</span>
        </div>

        {pendingInvitations.length === 0 ? (
          <div className="p-8 rounded-xl bg-slate-900/40 border border-slate-800 text-center">
            <Mail className="w-8 h-8 text-slate-600 mx-auto mb-2" />
            <p className="text-sm font-medium text-slate-300">No active pending invitations</p>
            <p className="text-xs text-slate-400 mt-1">
              All dispatched invitations have either been accepted or reached their expiry date.
            </p>
          </div>
        ) : (
          <div className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/70 border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="px-5 py-3.5">Recipient Email</th>
                    <th className="px-5 py-3.5">Assigned Role</th>
                    <th className="px-5 py-3.5">Status</th>
                    <th className="px-5 py-3.5">Dispatched</th>
                    <th className="px-5 py-3.5">Expiry</th>
                    <th className="px-5 py-3.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {pendingInvitations.map((inv) => (
                    <tr key={inv.id} className="hover:bg-slate-800/40 transition">
                      <td className="px-5 py-3.5 font-medium text-white flex items-center gap-2">
                        <Mail className="w-3.5 h-3.5 text-slate-400" />
                        <span>{inv.email}</span>
                      </td>
                      <td className="px-5 py-3.5">{renderRoleBadge(inv.role)}</td>
                      <td className="px-5 py-3.5">
                        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-400">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                          <span>Pending</span>
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-slate-400">{formatDate(inv.created_at)}</td>
                      <td className="px-5 py-3.5 text-amber-300/90 font-medium">
                        {formatExpires(inv.expires_at)}
                      </td>
                      <td className="px-5 py-3.5 text-right space-x-2">
                        {inv.invitation_token && (
                          <button
                            onClick={() => copyInvitationLink(inv.invitation_token)}
                            className="inline-flex items-center gap-1 py-1 px-2.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition text-[11px] font-medium"
                            title="Copy single-use invitation link"
                          >
                            <Copy className="w-3 h-3" />
                            <span>Copy Link</span>
                          </button>
                        )}
                        <button
                          onClick={() => setRevokingInvitation(inv)}
                          className="inline-flex items-center gap-1 py-1 px-2.5 rounded bg-red-950/40 hover:bg-red-900/60 text-red-300 border border-red-900/50 transition text-[11px] font-medium"
                        >
                          <Trash2 className="w-3 h-3 text-red-400" />
                          <span>Revoke</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Section 2: Active Organization Members */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <h2 className="text-base font-semibold text-white tracking-tight">
              Accepted Members & Organization Roster ({totalMemberCount})
            </h2>
          </div>
          <span className="text-xs text-slate-400">Authenticated participants in this workspace</span>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/70 border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
                <tr>
                  <th className="px-5 py-3.5">Member Identity</th>
                  <th className="px-5 py-3.5">Role</th>
                  <th className="px-5 py-3.5">Status</th>
                  <th className="px-5 py-3.5">Joined Date</th>
                  <th className="px-5 py-3.5">Membership Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {hasLiveMembers ? (
                  members.map((member) => {
                    const isSelf = member.id === currentUser.id || member.email === currentUser.email;
                    return (
                      <tr
                        key={member.id}
                        className={isSelf ? 'bg-blue-950/20 hover:bg-blue-950/30 transition' : 'hover:bg-slate-800/40 transition'}
                      >
                        <td className="px-5 py-3.5">
                          <div className="font-semibold text-white flex items-center gap-2">
                            <span>{member.full_name}</span>
                            {isSelf && (
                              <span className="text-[10px] bg-teal-950 text-teal-300 border border-teal-800/60 px-1.5 py-0.5 rounded font-mono">
                                You
                              </span>
                            )}
                          </div>
                          <div className="text-[11px] text-slate-400 font-mono mt-0.5">{member.email}</div>
                        </td>
                        <td className="px-5 py-3.5">{renderRoleBadge(member.role)}</td>
                        <td className="px-5 py-3.5">
                          <span className={`inline-flex items-center gap-1.5 font-semibold ${member.is_active ? 'text-emerald-400' : 'text-slate-500'}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${member.is_active ? 'bg-emerald-400' : 'bg-slate-500'}`}></span>
                            <span>{member.is_active ? 'Active' : 'Inactive'}</span>
                          </span>
                        </td>
                        <td className="px-5 py-3.5 text-slate-400">{formatDate(member.created_at)}</td>
                        <td className="px-5 py-3.5 text-slate-300 font-medium">
                          {member.is_owner ? 'Organization Owner' : (member.role === 'ADMIN' ? 'Administrator' : 'Team Member')}
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <>
                    {/* Fallback to currentUser + acceptedInvitations */}
                    <tr className="bg-blue-950/20 hover:bg-blue-950/30 transition">
                      <td className="px-5 py-3.5">
                        <div className="font-semibold text-white flex items-center gap-2">
                          <span>{currentUser.full_name}</span>
                          <span className="text-[10px] bg-teal-950 text-teal-300 border border-teal-800/60 px-1.5 py-0.5 rounded font-mono">
                            You
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-400 font-mono mt-0.5">{currentUser.email}</div>
                      </td>
                      <td className="px-5 py-3.5">{renderRoleBadge(currentUser.role)}</td>
                      <td className="px-5 py-3.5">
                        <span className="inline-flex items-center gap-1.5 text-emerald-400 font-semibold">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                          <span>Active</span>
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-slate-400">Workspace Onboarding</td>
                      <td className="px-5 py-3.5 text-slate-300 font-medium">Organization Owner</td>
                    </tr>

                    {acceptedInvitations.map((inv) => (
                      <tr key={inv.id} className="hover:bg-slate-800/40 transition">
                        <td className="px-5 py-3.5">
                          <div className="font-semibold text-white">{inv.email}</div>
                          <div className="text-[11px] text-slate-400 font-mono mt-0.5">Invited Member</div>
                        </td>
                        <td className="px-5 py-3.5">{renderRoleBadge(inv.role)}</td>
                        <td className="px-5 py-3.5">
                          <span className="inline-flex items-center gap-1.5 text-emerald-400 font-semibold">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                            <span>Active</span>
                          </span>
                        </td>
                        <td className="px-5 py-3.5 text-slate-400">{formatDate(inv.accepted_at || inv.created_at)}</td>
                        <td className="px-5 py-3.5 text-slate-300">Invited via Token</td>
                      </tr>
                    ))}
                  </>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Section 3: Invitation History (Revoked & Expired) */}
      {historyInvitations.length > 0 && (
        <div className="space-y-4 pt-4 border-t border-slate-800/60">
          <div className="flex items-center gap-2">
            <XCircle className="w-4 h-4 text-slate-400" />
            <h2 className="text-sm font-semibold text-slate-300 tracking-tight">
              Invitation History ({historyInvitations.length})
            </h2>
          </div>

          <div className="rounded-xl bg-slate-900/60 border border-slate-800/80 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/70 border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="px-5 py-2.5">Email</th>
                    <th className="px-5 py-2.5">Role</th>
                    <th className="px-5 py-2.5">Outcome</th>
                    <th className="px-5 py-2.5">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {historyInvitations.map((inv) => (
                    <tr key={inv.id} className="text-slate-400">
                      <td className="px-5 py-2.5 font-mono text-slate-300">{inv.email}</td>
                      <td className="px-5 py-2.5">{inv.role}</td>
                      <td className="px-5 py-2.5">
                        {inv.status === 'REVOKED' ? (
                          <span className="text-red-400 font-medium">Revoked by Admin</span>
                        ) : (
                          <span className="text-slate-400">Expired</span>
                        )}
                      </td>
                      <td className="px-5 py-2.5">{formatDate(inv.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Invite Member Modal */}
      {isInviteModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="relative w-full max-w-lg bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-6 py-5 border-b border-slate-800 bg-slate-900/50">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400">
                  <UserPlus className="w-5 h-5 text-blue-400" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-white">Invite Team Member</h3>
                  <p className="text-xs text-slate-400">Dispatch a cryptographically secure single-use invitation</p>
                </div>
              </div>
              <button
                onClick={() => setIsInviteModalOpen(false)}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
              >
                ✕
              </button>
            </div>

            <div className="p-6 space-y-4">
              {inviteError && (
                <div className="p-3 rounded-lg bg-red-950/60 border border-red-800/60 text-xs text-red-300 flex items-start gap-2.5">
                  <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
                  <span>{inviteError}</span>
                </div>
              )}

              {newlyCreatedInvite ? (
                <div className="space-y-4">
                  <div className="p-4 rounded-xl bg-emerald-950/50 border border-emerald-800/60 text-xs text-emerald-300">
                    <div className="flex items-center gap-2 font-semibold text-emerald-200">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      <span>Invitation Generated Successfully!</span>
                    </div>
                    <p className="mt-1 text-slate-300 text-[11px] leading-relaxed">
                      Because outbound email infrastructure is simulated in this environment, share this single-use link
                      directly with <span className="font-mono text-white">{newlyCreatedInvite.email}</span>.
                    </p>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1.5">
                      Single-Use Invitation Link
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        readOnly
                        value={
                          newlyCreatedInvite.invitation_token
                            ? `${window.location.origin}${window.location.pathname}#/invite?token=${newlyCreatedInvite.invitation_token}`
                            : 'Link generated'
                        }
                        className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 font-mono select-all"
                      />
                      <button
                        onClick={() => copyInvitationLink(newlyCreatedInvite.invitation_token)}
                        className="py-2 px-3 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition"
                      >
                        {hasCopiedLink ? (
                          <>
                            <Check className="w-3.5 h-3.5 text-emerald-300" />
                            <span>Copied</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5" />
                            <span>Copy</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>

                  <div className="pt-2 flex justify-end">
                    <button
                      onClick={() => setIsInviteModalOpen(false)}
                      className="py-2 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition"
                    >
                      Done
                    </button>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleCreateInviteSubmit} className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1.5">
                      Recipient Email Address <span className="text-red-400">*</span>
                    </label>
                    <div className="relative">
                      <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-3 pointer-events-none" />
                      <input
                        type="email"
                        required
                        value={inviteEmail}
                        onChange={(e) => setInviteEmail(e.target.value)}
                        placeholder="colleague@company.com"
                        className="w-full bg-slate-950 border border-slate-700/80 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1.5">
                      Assigned Role <span className="text-red-400">*</span>
                    </label>
                    <div className="grid grid-cols-2 gap-3">
                      <label
                        className={`p-3 rounded-xl border cursor-pointer transition flex flex-col ${
                          inviteRole === 'CREATOR'
                            ? 'bg-blue-950/40 border-blue-500 text-white'
                            : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                        }`}
                      >
                        <input
                          type="radio"
                          name="inviteRole"
                          value="CREATOR"
                          checked={inviteRole === 'CREATOR'}
                          onChange={() => setInviteRole('CREATOR')}
                          className="sr-only"
                        />
                        <div className="font-semibold text-xs text-blue-300">Content Creator</div>
                        <div className="text-[11px] text-slate-400 mt-1">Author content, draft submissions</div>
                      </label>

                      <label
                        className={`p-3 rounded-xl border cursor-pointer transition flex flex-col ${
                          inviteRole === 'REVIEWER'
                            ? 'bg-purple-950/40 border-purple-500 text-white'
                            : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                        }`}
                      >
                        <input
                          type="radio"
                          name="inviteRole"
                          value="REVIEWER"
                          checked={inviteRole === 'REVIEWER'}
                          onChange={() => setInviteRole('REVIEWER')}
                          className="sr-only"
                        />
                        <div className="font-semibold text-xs text-purple-300">Compliance Reviewer</div>
                        <div className="text-[11px] text-slate-400 mt-1">Authorize reviews, approve, reject</div>
                      </label>
                    </div>

                    <div className="p-3 mt-3 rounded-lg bg-slate-950 border border-slate-800 text-[11px] text-slate-400 flex items-start gap-2">
                      <Lock className="w-3.5 h-3.5 text-teal-400 flex-shrink-0 mt-0.5" />
                      <span>
                        Security Invariant: Invitations are restricted strictly to CREATOR and REVIEWER roles. ADMIN
                        privileges cannot be granted via invitations.
                      </span>
                    </div>
                  </div>

                  <div className="pt-2 flex items-center justify-end gap-3">
                    <button
                      type="button"
                      onClick={() => setIsInviteModalOpen(false)}
                      className="py-2 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={isSubmittingInvite}
                      className="py-2 px-4 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition disabled:opacity-50"
                    >
                      {isSubmittingInvite ? 'Dispatching...' : 'Dispatch Invitation'}
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Revoke Confirmation Modal */}
      {revokingInvitation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="relative w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl p-6 space-y-4">
            <div className="flex items-center gap-3 text-red-400">
              <div className="w-10 h-10 rounded-xl bg-red-950/60 border border-red-800/60 flex items-center justify-center">
                <Trash2 className="w-5 h-5 text-red-400" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-white">Revoke Invitation?</h3>
                <p className="text-xs text-slate-400">This action cannot be undone</p>
              </div>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              Are you sure you want to revoke the invitation for{' '}
              <span className="font-semibold text-white font-mono">{revokingInvitation.email}</span>? Any link already
              shared will immediately become invalid.
            </p>

            {revokeError && (
              <div className="p-3 rounded-lg bg-red-950/60 border border-red-800/60 text-xs text-red-300">
                {revokeError}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setRevokingInvitation(null)}
                disabled={isRevoking}
                className="py-2 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition"
              >
                Keep Active
              </button>
              <button
                type="button"
                onClick={handleRevokeConfirm}
                disabled={isRevoking}
                className="py-2 px-4 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-semibold transition disabled:opacity-50"
              >
                {isRevoking ? 'Revoking...' : 'Revoke Invitation'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
