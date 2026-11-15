import React, { useState, useEffect } from 'react';
import {
  Shield,
  Building2,
  Mail,
  User,
  Lock,
  AlertCircle,
  CheckCircle2,
  X,
  Loader2,
  ArrowRight,
} from 'lucide-react';
import { validateInvitationToken, acceptInvitation } from '../../services/api';
import { scrubUrlToken } from '../../services/router';
import type { AuthSession, InvitationValidationResponse } from '../../types';

interface InvitationAcceptModalProps {
  isOpen: boolean;
  token: string | null;
  onClose: () => void;
  onAcceptSuccess: (session: AuthSession) => void;
  onSwitchToLogin?: () => void;
}

export const InvitationAcceptModal: React.FC<InvitationAcceptModalProps> = ({
  isOpen,
  token,
  onClose,
  onAcceptSuccess,
  onSwitchToLogin,
}) => {
  const [isValidating, setIsValidating] = useState(false);
  const [validationData, setValidationData] = useState<InvitationValidationResponse | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  // Form input state
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Reset and validate whenever token or open status changes
  useEffect(() => {
    if (!isOpen || !token) {
      setValidationData(null);
      setValidationError(null);
      setFullName('');
      setPassword('');
      setConfirmPassword('');
      setSubmitError(null);
      setSuccessMessage(null);
      return;
    }

    // Scrub token from browser address bar immediately upon mounting
    // Security Rule 9: Never expose invitation tokens in URL history, bookmarks, or Referer
    scrubUrlToken();

    let isMounted = true;
    setIsValidating(true);
    setValidationError(null);
    setValidationData(null);

    validateInvitationToken(token)
      .then((data) => {
        if (!isMounted) return;
        setValidationData(data);
        setIsValidating(false);
      })
      .catch((err: any) => {
        if (!isMounted) return;
        setIsValidating(false);
        const message = err?.message || 'The invitation token is invalid, expired, or has already been used.';
        setValidationError(message);
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, token]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) {
      setSubmitError('Invitation token is missing or has expired.');
      return;
    }

    setSubmitError(null);

    // Client-side validations
    const cleanName = fullName.trim();
    if (cleanName.length < 2) {
      setSubmitError('Full name must be at least 2 characters.');
      return;
    }
    if (password.length < 8) {
      setSubmitError('Password must be at least 8 characters long.');
      return;
    }
    if (password !== confirmPassword) {
      setSubmitError('Passwords do not match. Please re-enter your password.');
      return;
    }

    setIsSubmitting(true);
    try {
      const session = await acceptInvitation({
        token,
        full_name: cleanName,
        password,
      });

      setSuccessMessage(`Account provisioned successfully! Joining ${session.user.organization_name || 'workspace'}...`);
      setTimeout(() => {
        onAcceptSuccess(session);
        onClose();
      }, 1200);
    } catch (err: any) {
      setSubmitError(err?.message || 'Failed to accept invitation. Please try again or contact your administrator.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const getRoleBadge = (role: string) => {
    if (role === 'REVIEWER') {
      return {
        label: 'Compliance Reviewer',
        sub: 'Authorized to review, approve, request revisions, and reject content submissions.',
        className: 'bg-purple-950 text-purple-300 border border-purple-800/60',
      };
    }
    return {
      label: 'Content Creator',
      sub: 'Authorized to draft submissions, request automated compliance checks, and apply suggestions.',
      className: 'bg-blue-950 text-blue-300 border border-blue-800/60',
    };
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-lg bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-800 bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400">
              <Shield className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white tracking-tight">Team Invitation Acceptance</h2>
              <p className="text-xs text-slate-400">Join your organization's BrandShield AI workspace</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition"
            aria-label="Close modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto max-h-[calc(85vh-140px)]">
          {/* Validation Loading State */}
          {isValidating && (
            <div className="py-12 flex flex-col items-center justify-center text-center">
              <Loader2 className="w-10 h-10 text-blue-500 animate-spin mb-4" />
              <h3 className="text-sm font-semibold text-white">Verifying invitation token...</h3>
              <p className="text-xs text-slate-400 mt-1">Cryptographically authenticating organization membership</p>
            </div>
          )}

          {/* Validation Error State */}
          {!isValidating && validationError && (
            <div className="py-6 flex flex-col items-center text-center">
              <div className="w-14 h-14 rounded-2xl bg-red-950/60 border border-red-800/60 flex items-center justify-center mb-4 text-red-400">
                <AlertCircle className="w-7 h-7 text-red-400" />
              </div>
              <h3 className="text-base font-semibold text-white">Invitation Unavailable</h3>
              <p className="text-xs text-slate-300 max-w-sm mt-2 leading-relaxed bg-red-950/40 p-3 rounded-lg border border-red-900/40">
                {validationError}
              </p>
              <div className="mt-6 flex items-center gap-3 w-full">
                {onSwitchToLogin && (
                  <button
                    onClick={() => {
                      onClose();
                      onSwitchToLogin();
                    }}
                    className="flex-1 py-2.5 px-4 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition flex items-center justify-center gap-2"
                  >
                    <span>Sign In to Existing Account</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                )}
                <button
                  onClick={onClose}
                  className="flex-1 py-2.5 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition"
                >
                  Close Window
                </button>
              </div>
            </div>
          )}

          {/* Valid Invitation Form */}
          {!isValidating && validationData && (
            <div>
              {/* Organization and Role Banner */}
              <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800 mb-5 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-slate-300 text-xs font-medium">
                    <Building2 className="w-4 h-4 text-teal-400" />
                    <span>Workspace:</span>
                  </div>
                  <span className="text-xs font-bold text-white tracking-wide">
                    {validationData.organization_name}
                  </span>
                </div>

                <div className="flex items-start justify-between gap-2 pt-2 border-t border-slate-800/80">
                  <div className="text-xs text-slate-400">Assigned Role:</div>
                  <div className="text-right">
                    <span
                      className={`text-[11px] font-bold px-2.5 py-0.5 rounded-full inline-block ${
                        getRoleBadge(validationData.role).className
                      }`}
                    >
                      {getRoleBadge(validationData.role).label}
                    </span>
                    <p className="text-[10px] text-slate-400 mt-1 max-w-xs text-right">
                      {getRoleBadge(validationData.role).sub}
                    </p>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-slate-800/80">
                  <div className="flex items-center gap-2 text-slate-400 text-xs">
                    <Mail className="w-3.5 h-3.5 text-slate-400" />
                    <span>Invited Email:</span>
                  </div>
                  <span className="text-xs font-mono text-slate-200">
                    {validationData.email}
                  </span>
                </div>
              </div>

              {/* Submit / Success Banners */}
              {submitError && (
                <div className="p-3 mb-4 rounded-lg bg-red-950/60 border border-red-800/60 text-xs text-red-300 flex items-start gap-2.5">
                  <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
                  <span className="leading-relaxed">{submitError}</span>
                </div>
              )}

              {successMessage && (
                <div className="p-3 mb-4 rounded-lg bg-emerald-950/60 border border-emerald-800/60 text-xs text-emerald-300 flex items-center gap-2.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                  <span>{successMessage}</span>
                </div>
              )}

              {/* Form to complete account setup */}
              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Your Full Name <span className="text-red-400">*</span>
                  </label>
                  <div className="relative">
                    <User className="w-4 h-4 text-slate-400 absolute left-3 top-3 pointer-events-none" />
                    <input
                      type="text"
                      required
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      placeholder="e.g. Alex Rivera"
                      minLength={2}
                      maxLength={150}
                      disabled={isSubmitting || !!successMessage}
                      className="w-full bg-slate-950 border border-slate-700/80 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Choose Password <span className="text-red-400">*</span>
                  </label>
                  <div className="relative">
                    <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-3 pointer-events-none" />
                    <input
                      type="password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Minimum 8 characters"
                      minLength={8}
                      maxLength={128}
                      disabled={isSubmitting || !!successMessage}
                      className="w-full bg-slate-950 border border-slate-700/80 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Confirm Password <span className="text-red-400">*</span>
                  </label>
                  <div className="relative">
                    <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-3 pointer-events-none" />
                    <input
                      type="password"
                      required
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="Re-enter your password"
                      minLength={8}
                      maxLength={128}
                      disabled={isSubmitting || !!successMessage}
                      className="w-full bg-slate-950 border border-slate-700/80 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
                    />
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={isSubmitting || !!successMessage}
                    className="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-lg shadow-sm hover:shadow transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    {isSubmitting ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Provisioning Membership...</span>
                      </>
                    ) : (
                      <>
                        <span>Accept Invitation & Enter Workspace</span>
                        <ArrowRight className="w-4 h-4" />
                      </>
                    )}
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>

        {/* Modal Footer Security Notice */}
        <div className="px-6 py-3.5 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between text-[11px] text-slate-400">
          <span className="flex items-center gap-1.5 text-teal-400">
            <Lock className="w-3 h-3 text-teal-400" />
            <span>End-to-End Tenant Isolation</span>
          </span>
          <span>BrandShield AI Governance</span>
        </div>
      </div>
    </div>
  );
};
