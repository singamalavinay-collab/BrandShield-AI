import React, { useState, useEffect } from 'react';
import {
  X,
  Lock,
  Mail,
  ShieldAlert,
  CheckCircle2,
  AlertCircle,
  Building2,
  Check,
  Sparkles,
  User,
  UserCheck,
  UserPlus,
} from 'lucide-react';
import { login, onboardWorkspace } from '../../services/api';
import { AuthUser } from '../../types';

interface LoginModalProps {
  isOpen: boolean;
  initialTab?: 'signin' | 'register';
  onClose: () => void;
  onLoginSuccess: (user: AuthUser) => void;
  initialMessage?: string;
}

type AuthTab = 'signin' | 'register';
type QuickFillType = 'sarah' | 'mark' | null;

export const LoginModal: React.FC<LoginModalProps> = ({
  isOpen,
  initialTab = 'signin',
  onClose,
  onLoginSuccess,
  initialMessage,
}) => {
  const [activeTab, setActiveTab] = useState<AuthTab>(initialTab);

  // Sign In Form State
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [selectedQuickFill, setSelectedQuickFill] = useState<QuickFillType>(null);

  // Onboard / Register Form State
  const [regOrgName, setRegOrgName] = useState('');
  const [regFullName, setRegFullName] = useState('');
  const [regEmail, setRegEmail] = useState('');
  const [regPassword, setRegPassword] = useState('');

  // Status & Feedback State
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Synchronize activeTab whenever modal opens or initialTab prop updates
  useEffect(() => {
    if (isOpen) {
      setActiveTab(initialTab);
      resetFormState();
    }
  }, [isOpen, initialTab]);

  if (!isOpen) return null;

  const resetFormState = () => {
    setErrorMessage(null);
    setSuccessMessage(null);
  };

  const handleTabChange = (tab: AuthTab) => {
    setActiveTab(tab);
    resetFormState();
  };

  const mapErrorMessage = (err: unknown): string => {
    if (err instanceof Error) {
      const msg = err.message.toLowerCase();
      if (
        msg.includes('failed to fetch') ||
        msg.includes('network error') ||
        msg.includes('timed out') ||
        msg.includes('econnrefused')
      ) {
        return 'Backend API is currently offline or unreachable at http://127.0.0.1:8000. Please ensure the FastAPI backend is running.';
      }
      return err.message;
    }
    return 'Authentication request failed. Please check your credentials and connection.';
  };

  // Sign in submit
  const handleSignIn = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const session = await login({ email: email.trim(), password });
      setSuccessMessage(`Authenticated as ${session.user.full_name} (${session.user.role})`);
      setTimeout(() => {
        onLoginSuccess(session.user);
        onClose();
      }, 500);
    } catch (err: unknown) {
      setErrorMessage(mapErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  // One-click demo sign in
  const handleInstantDemoLogin = async (demoEmail: string, demoPass: string, role: QuickFillType) => {
    setEmail(demoEmail);
    setPassword(demoPass);
    setSelectedQuickFill(role);
    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const session = await login({ email: demoEmail, password: demoPass });
      setSuccessMessage(`One-click demo sign-in: Authenticated as ${session.user.full_name} (${session.user.role})`);
      setTimeout(() => {
        onLoginSuccess(session.user);
        onClose();
      }, 500);
    } catch (err: unknown) {
      setErrorMessage(mapErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  // Quick fill without immediate submission
  const handleQuickFill = (demoEmail: string, demoPass: string, role: QuickFillType) => {
    setEmail(demoEmail);
    setPassword(demoPass);
    setSelectedQuickFill(role);
    setErrorMessage(null);
  };

  // Register & Onboard workspace submit
  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (regOrgName.trim().length < 2) {
      setErrorMessage('Organization / Workspace name must be at least 2 characters long.');
      return;
    }
    if (regFullName.trim().length < 2) {
      setErrorMessage('Full name must be at least 2 characters long.');
      return;
    }
    if (regPassword.length < 8) {
      setErrorMessage('Password must be at least 8 characters long.');
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const session = await onboardWorkspace({
        organization_name: regOrgName.trim(),
        full_name: regFullName.trim(),
        email: regEmail.trim(),
        password: regPassword,
      });
      setSuccessMessage(
        `Organization '${session.user.organization_name || regOrgName.trim()}' created! Signed in as ${session.user.full_name} (${session.user.role}).`
      );
      setTimeout(() => {
        onLoginSuccess(session.user);
        onClose();
      }, 600);
    } catch (err: unknown) {
      setErrorMessage(mapErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="relative bg-white rounded-xl shadow-2xl border border-slate-200 max-w-md w-full overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600">
              <Lock className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900 tracking-tight">BrandShield Authentication</h2>
              <p className="text-xs text-slate-500">Secure human governance & review access</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition"
            aria-label="Close modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="px-6 pt-4 pb-0 bg-white">
          <div className="flex rounded-lg bg-slate-100 p-1 border border-slate-200/80">
            <button
              type="button"
              onClick={() => handleTabChange('signin')}
              className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition flex items-center justify-center gap-1.5 ${
                activeTab === 'signin'
                  ? 'bg-white text-slate-900 shadow-sm border border-slate-200/60'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <UserCheck className="w-3.5 h-3.5 text-blue-600" />
              <span>Sign In</span>
            </button>
            <button
              type="button"
              onClick={() => handleTabChange('register')}
              className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition flex items-center justify-center gap-1.5 ${
                activeTab === 'register'
                  ? 'bg-white text-slate-900 shadow-sm border border-slate-200/60'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <UserPlus className="w-3.5 h-3.5 text-teal-600" />
              <span>Create Account</span>
            </button>
          </div>
        </div>

        {/* Form Body */}
        <div className="p-6 space-y-4">
          {initialMessage && !errorMessage && !successMessage && (
            <div className="p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-xs flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
              <span>{initialMessage}</span>
            </div>
          )}

          {errorMessage && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-800 text-xs flex items-start gap-2">
              <ShieldAlert className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" />
              <span className="leading-relaxed">{errorMessage}</span>
            </div>
          )}

          {successMessage && (
            <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0 mt-0.5" />
              <span>{successMessage}</span>
            </div>
          )}

          {activeTab === 'signin' ? (
            /* ========================================================== */
            /* SIGN IN VIEW                                               */
            /* ========================================================== */
            <div className="space-y-4">
              <form onSubmit={handleSignIn} className="space-y-3.5">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Work Email Address
                  </label>
                  <div className="relative">
                    <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
                    <input
                      type="email"
                      required
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        setSelectedQuickFill(null);
                      }}
                      placeholder="reviewer@brandshield.ai"
                      className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Password
                  </label>
                  <div className="relative">
                    <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
                    <input
                      type="password"
                      required
                      value={password}
                      onChange={(e) => {
                        setPassword(e.target.value);
                        setSelectedQuickFill(null);
                      }}
                      placeholder="••••••••••••"
                      className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600"
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full py-2.5 px-4 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm transition shadow-sm disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {isLoading ? (
                    <span>Authenticating...</span>
                  ) : (
                    <>
                      <UserCheck className="w-4 h-4" />
                      <span>
                        {selectedQuickFill === 'sarah'
                          ? 'Sign In as Sarah Jenkins (Reviewer)'
                          : selectedQuickFill === 'mark'
                          ? 'Sign In as Mark Creator (Creator)'
                          : 'Sign In to BrandShield'}
                      </span>
                    </>
                  )}
                </button>
              </form>

              {/* Development Quick-Fills */}
              <div className="pt-3 border-t border-slate-100">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                    Development Quick-Fill Accounts
                  </span>
                  <span className="text-[10px] text-teal-700 font-medium">Click to Fill or Instant Login</span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {/* Sarah Jenkins (Reviewer) */}
                  <div
                    onClick={() => handleQuickFill('sarah.jenkins@brandshield.ai', 'ValidReviewerPass123!', 'sarah')}
                    className={`cursor-pointer text-left p-2.5 rounded-lg border transition text-xs flex flex-col justify-between ${
                      selectedQuickFill === 'sarah'
                        ? 'border-blue-500 bg-blue-50/60 ring-1 ring-blue-500/30'
                        : 'border-slate-200 hover:border-blue-300 hover:bg-slate-50/70'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-900">Sarah Jenkins</span>
                        {selectedQuickFill === 'sarah' && (
                          <span className="w-4 h-4 rounded-full bg-blue-600 text-white flex items-center justify-center">
                            <Check className="w-2.5 h-2.5 stroke-[3]" />
                          </span>
                        )}
                      </div>
                      <div className="text-[10px] font-medium text-blue-600 mt-0.5">REVIEWER Role</div>
                      <div className="text-[10px] text-slate-400 truncate">Can approve & edit</div>
                    </div>

                    <button
                      type="button"
                      disabled={isLoading}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleInstantDemoLogin('sarah.jenkins@brandshield.ai', 'ValidReviewerPass123!', 'sarah');
                      }}
                      className="mt-2 w-full py-1 px-2 rounded bg-blue-100 hover:bg-blue-200 text-blue-800 text-[10px] font-semibold transition text-center flex items-center justify-center gap-1"
                    >
                      <Sparkles className="w-3 h-3 text-blue-600" />
                      <span>Instant Demo Login</span>
                    </button>
                  </div>

                  {/* Mark Creator (Creator) */}
                  <div
                    onClick={() => handleQuickFill('mark.creator@brandshield.ai', 'ValidCreatorPass123!', 'mark')}
                    className={`cursor-pointer text-left p-2.5 rounded-lg border transition text-xs flex flex-col justify-between ${
                      selectedQuickFill === 'mark'
                        ? 'border-blue-500 bg-blue-50/60 ring-1 ring-blue-500/30'
                        : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50/70'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-900">Mark Creator</span>
                        {selectedQuickFill === 'mark' && (
                          <span className="w-4 h-4 rounded-full bg-blue-600 text-white flex items-center justify-center">
                            <Check className="w-2.5 h-2.5 stroke-[3]" />
                          </span>
                        )}
                      </div>
                      <div className="text-[10px] font-medium text-slate-600 mt-0.5">CREATOR Role</div>
                      <div className="text-[10px] text-slate-400 truncate">No review authority</div>
                    </div>

                    <button
                      type="button"
                      disabled={isLoading}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleInstantDemoLogin('mark.creator@brandshield.ai', 'ValidCreatorPass123!', 'mark');
                      }}
                      className="mt-2 w-full py-1 px-2 rounded bg-slate-100 hover:bg-slate-200 text-slate-800 text-[10px] font-semibold transition text-center flex items-center justify-center gap-1"
                    >
                      <Sparkles className="w-3 h-3 text-slate-600" />
                      <span>Instant Demo Login</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            /* ========================================================== */
            /* CREATE WORKSPACE & ONBOARD VIEW                            */
            /* ========================================================== */
            <form onSubmit={handleRegister} className="space-y-3.5">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Organization / Brand Workspace Name
                </label>
                <div className="relative">
                  <Building2 className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
                  <input
                    type="text"
                    required
                    minLength={2}
                    maxLength={150}
                    value={regOrgName}
                    onChange={(e) => setRegOrgName(e.target.value)}
                    placeholder="e.g. Acme Corporation"
                    className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Administrator Full Name
                </label>
                <div className="relative">
                  <User className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
                  <input
                    type="text"
                    required
                    minLength={2}
                    maxLength={150}
                    value={regFullName}
                    onChange={(e) => setRegFullName(e.target.value)}
                    placeholder="e.g. Alex Morgan"
                    className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Work Email Address
                </label>
                <div className="relative">
                  <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
                  <input
                    type="email"
                    required
                    value={regEmail}
                    onChange={(e) => setRegEmail(e.target.value)}
                    placeholder="alex.morgan@company.com"
                    className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Password <span className="text-[10px] text-slate-400 font-normal">(minimum 8 characters)</span>
                </label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
                  <input
                    type="password"
                    required
                    minLength={8}
                    maxLength={128}
                    value={regPassword}
                    onChange={(e) => setRegPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600"
                  />
                </div>
              </div>

              {/* Strict Governance Role Notice */}
              <div className="p-3 rounded-lg bg-blue-50/70 border border-blue-200/80 text-xs text-slate-700 space-y-1">
                <div className="flex items-center gap-1.5 font-semibold text-blue-950">
                  <ShieldAlert className="w-3.5 h-3.5 text-blue-600 flex-shrink-0" />
                  <span>Initial Workspace Administrator (ADMIN)</span>
                </div>
                <p className="text-[11px] text-blue-800/80 leading-relaxed">
                  Registration provisions an isolated organization workspace. As the initial registrant, you receive
                  full administrative control. Team members can subsequently be invited with Assigned Role: Content Author (CREATOR)
                  or Compliance Reviewer.
                </p>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full py-2.5 px-4 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm transition shadow-sm disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {isLoading ? (
                  <span>Provisioning Workspace...</span>
                ) : (
                  <>
                    <Building2 className="w-4 h-4" />
                    <span>Create Organization Workspace</span>
                  </>
                )}
              </button>
            </form>
          )}
        </div>

        {/* Footer Security Notice */}
        <div className="px-6 py-3 bg-slate-50 border-t border-slate-100 text-[11px] text-slate-500 flex items-center justify-between">
          <span>Cryptographically signed JWT Bearer Token</span>
          <span className="font-mono text-[10px] text-slate-400">HS256 / SHA-256</span>
        </div>
      </div>
    </div>
  );
};
