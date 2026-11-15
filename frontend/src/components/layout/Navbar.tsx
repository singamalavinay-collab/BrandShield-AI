import React, { useState, useRef, useEffect } from 'react';
import {
  RefreshCw,
  Server,
  User,
  Building2,
  Menu,
  Database,
  LogIn,
  LogOut,
  Mail,
  Shield,
  ChevronDown,
} from 'lucide-react';
import { AuthUser, BackendHealth, SystemDiagnostic } from '../../types';

interface NavbarProps {
  title: string;
  description: string;
  backendHealth: BackendHealth;
  systemDiagnostic: SystemDiagnostic | null;
  currentUser: AuthUser | null;
  isCheckingHealth: boolean;
  onRefreshHealth: () => void;
  onToggleMobileMenu: () => void;
  onOpenLogin: () => void;
  onLogout: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  title,
  description,
  backendHealth,
  systemDiagnostic,
  currentUser,
  isCheckingHealth,
  onRefreshHealth,
  onToggleMobileMenu,
  onOpenLogin,
  onLogout,
}) => {
  const isDbConnected = systemDiagnostic?.database?.connected ?? false;
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);

  // Close profile popover on click outside or Escape
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setIsProfileOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsProfileOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  const getRoleDescription = (role: string) => {
    switch (role) {
      case 'ADMIN':
        return 'Organization Administrator (Full Control)';
      case 'REVIEWER':
        return 'Compliance Officer (Review & Approval)';
      case 'CREATOR':
        return 'Content Author (Draft Creation)';
      case 'AUDITOR':
        return 'Compliance Auditor (Read-Only)';
      default:
        return role;
    }
  };

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-20">
      <div className="px-4 sm:px-6 lg:px-8 py-3.5 flex items-center justify-between gap-4">
        {/* Left: Mobile Toggle & Page Info */}
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={onToggleMobileMenu}
            className="md:hidden p-2 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition"
            aria-label="Toggle navigation menu"
          >
            <Menu className="w-5 h-5" />
          </button>

          <div>
            <h1 className="text-lg sm:text-xl font-bold text-slate-900 tracking-tight flex items-center gap-2 truncate">
              {title}
            </h1>
            <p className="text-xs text-slate-500 hidden sm:block truncate mt-0.5">
              {description}
            </p>
          </div>
        </div>

        {/* Right: Tenant, Database Status, Backend Health & Reviewer Profile */}
        <div className="flex items-center gap-2.5 sm:gap-4 flex-shrink-0">
          {/* Tenant Pill (Dynamic Organization Identity) */}
          <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-50 border border-slate-200 text-xs text-slate-700">
            <Building2 className="w-3.5 h-3.5 text-slate-500" />
            <span className="font-semibold text-slate-800">
              {currentUser?.organization_name || (currentUser ? 'Organization Workspace' : 'Public Workspace')}
            </span>
            <span className="text-[10px] text-slate-400 font-normal">
              {currentUser ? `| ${currentUser.role}` : '| Guest Mode'}
            </span>
          </div>

          {/* Database Connectivity Status */}
          <div
            title={
              isDbConnected
                ? `Database Connected (${systemDiagnostic?.database.active_dialect})`
                : 'PostgreSQL instance not connected (Local mode)'
            }
            className={`hidden sm:inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium border ${
              isDbConnected
                ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                : 'bg-slate-100 text-slate-600 border-slate-200'
            }`}
          >
            <Database className="w-3 h-3 text-slate-500" />
            <span className={`w-1.5 h-1.5 rounded-full ${isDbConnected ? 'bg-emerald-500' : 'bg-slate-400'}`} />
            <span className="text-[11px]">{isDbConnected ? 'DB Active' : 'DB Offline'}</span>
          </div>

          {/* Backend Health Status Badge */}
          <button
            onClick={onRefreshHealth}
            title={backendHealth.is_connected ? 'Backend API Connected & Verified' : 'Click to check backend connectivity'}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition ${
              backendHealth.is_connected
                ? 'bg-emerald-50 text-emerald-800 border-emerald-200 hover:bg-emerald-100'
                : 'bg-amber-50 text-amber-800 border-amber-200 hover:bg-amber-100'
            }`}
          >
            <Server className="w-3.5 h-3.5" />
            <span
              className={`w-2 h-2 rounded-full ${
                backendHealth.is_connected ? 'bg-emerald-500' : 'bg-amber-500'
              }`}
            />
            <span className="hidden md:inline">
              {backendHealth.is_connected ? `API v${backendHealth.version || '0.1.0'}` : 'API Offline (UI Mode)'}
            </span>
            <RefreshCw
              className={`w-3 h-3 text-slate-400 ${isCheckingHealth ? 'animate-spin text-blue-600' : ''}`}
            />
          </button>

          {/* User Profile / Login Action & Popover */}
          <div className="relative flex items-center gap-2 pl-2 border-l border-slate-200" ref={profileRef}>
            {currentUser ? (
              <>
                <button
                  onClick={() => setIsProfileOpen((prev) => !prev)}
                  className="flex items-center gap-2 p-1 rounded-lg hover:bg-slate-50 transition border border-transparent hover:border-slate-200"
                  aria-expanded={isProfileOpen}
                  aria-haspopup="true"
                >
                  <div className="w-7 h-7 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center font-semibold text-xs border border-blue-200">
                    <User className="w-4 h-4" />
                  </div>
                  <div className="hidden sm:block text-left">
                    <div className="text-xs font-semibold text-slate-800 leading-tight flex items-center gap-1.5">
                      <span>{currentUser.full_name}</span>
                      <span className="text-[10px] font-medium px-1.5 py-0.2 rounded bg-blue-50 text-blue-700 border border-blue-200">
                        {currentUser.role}
                      </span>
                    </div>
                    <div className="text-[10px] text-slate-500 leading-tight truncate max-w-[140px]">
                      {currentUser.email}
                    </div>
                  </div>
                  <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${isProfileOpen ? 'rotate-180' : ''}`} />
                </button>

                {/* Profile Popover Card */}
                {isProfileOpen && (
                  <div className="absolute right-0 top-full mt-2 w-72 rounded-xl bg-white shadow-xl border border-slate-200/90 py-3 px-4 z-50 animate-in fade-in zoom-in-95 duration-100">
                    {/* Organization Banner */}
                    <div className="pb-3 border-b border-slate-100">
                      <div className="flex items-center gap-1.5 text-xs font-bold text-slate-900 truncate">
                        <Building2 className="w-4 h-4 text-blue-600 flex-shrink-0" />
                        <span className="truncate">{currentUser.organization_name || 'Organization Workspace'}</span>
                      </div>
                      <div className="text-[10px] text-slate-400 mt-0.5">
                        Authenticated Multi-Tenant Workspace
                      </div>
                    </div>

                    {/* User Identity Details */}
                    <div className="py-3 space-y-2 text-xs">
                      <div className="flex items-start gap-2">
                        <div className="w-8 h-8 rounded-full bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-xs flex-shrink-0 mt-0.5">
                          {currentUser.full_name.charAt(0).toUpperCase()}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="font-semibold text-slate-900 truncate">{currentUser.full_name}</div>
                          <div className="text-slate-500 text-[11px] flex items-center gap-1 truncate mt-0.5">
                            <Mail className="w-3 h-3 text-slate-400 flex-shrink-0" />
                            <span className="truncate">{currentUser.email}</span>
                          </div>
                        </div>
                      </div>

                      {/* Role Pill & Permissions Description */}
                      <div className="p-2 rounded-lg bg-slate-50 border border-slate-200/70 text-[11px]">
                        <div className="font-semibold text-slate-800 flex items-center gap-1.5">
                          <Shield className="w-3 h-3 text-indigo-600" />
                          <span>Role: {currentUser.role}</span>
                        </div>
                        <div className="text-[10px] text-slate-500 mt-0.5">
                          {getRoleDescription(currentUser.role)}
                        </div>
                      </div>
                    </div>

                    {/* Actions & Sign Out */}
                    <div className="pt-2 border-t border-slate-100">
                      <button
                        onClick={() => {
                          setIsProfileOpen(false);
                          onLogout();
                        }}
                        className="w-full flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg text-xs font-semibold text-red-600 hover:text-red-700 hover:bg-red-50 transition"
                      >
                        <LogOut className="w-3.5 h-3.5" />
                        <span>Sign Out of Workspace</span>
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <button
                onClick={onOpenLogin}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs transition shadow-sm"
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>Sign In</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
