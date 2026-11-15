import React from 'react';
import {
  Shield,
  LayoutDashboard,
  BookOpen,
  FilePlus2,
  SearchCheck,
  Wand2,
  ShieldCheck,
  Users,
  X,
  Lock,
} from 'lucide-react';
import { NavigationTab, AuthUser } from '../../types';

interface SidebarProps {
  currentTab: NavigationTab;
  onSelectTab: (tab: NavigationTab) => void;
  pendingReviewsCount: number;
  violationsCount: number;
  guidelinesCount?: number;
  isMobileOpen: boolean;
  onCloseMobile: () => void;
  currentUser?: AuthUser | null;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentTab,
  onSelectTab,
  pendingReviewsCount,
  violationsCount,
  guidelinesCount = 0,
  isMobileOpen,
  onCloseMobile,
  currentUser,
}) => {
  const isAdmin = currentUser?.role === 'ADMIN';
  const isReviewerOrAdmin = currentUser?.role === 'ADMIN' || currentUser?.role === 'REVIEWER';

  const navItems: Array<{
    id: NavigationTab;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    badge?: string | number;
    badgeVariant?: 'red' | 'purple' | 'blue';
  }> = [
    {
      id: 'dashboard',
      label: 'Dashboard',
      icon: LayoutDashboard,
    },
    {
      id: 'guidelines',
      label: 'Brand Guidelines',
      icon: BookOpen,
      badge: guidelinesCount > 0 ? `${guidelinesCount} ${guidelinesCount === 1 ? 'Rule' : 'Rules'}` : undefined,
      badgeVariant: 'blue',
    },
    {
      id: 'submission',
      label: 'Content Submission',
      icon: FilePlus2,
    },
    {
      id: 'analysis',
      label: 'Analysis Results',
      icon: SearchCheck,
      badge: violationsCount > 0 ? `${violationsCount} Flagged` : undefined,
      badgeVariant: 'red',
    },
    {
      id: 'corrections',
      label: 'Corrections & Suggestions',
      icon: Wand2,
    },
    ...(isReviewerOrAdmin
      ? [
          {
            id: 'review' as NavigationTab,
            label: 'Review & Approval',
            icon: ShieldCheck,
            badge: pendingReviewsCount > 0 ? `${pendingReviewsCount} Pending` : undefined,
            badgeVariant: 'purple' as const,
          },
        ]
      : []),
    ...(isAdmin
      ? [
          {
            id: 'team' as NavigationTab,
            label: 'Team & Access',
            icon: Users,
          },
        ]
      : []),
  ];

  const handleNavClick = (tab: NavigationTab) => {
    onSelectTab(tab);
    onCloseMobile();
  };

  const sidebarContent = (
    <div className="flex flex-col h-full bg-slate-900 text-slate-100">
      {/* Brand Header */}
      <div className="px-5 py-5 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center text-white shadow-sm ring-1 ring-blue-400/30">
            <Shield className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="font-bold text-white text-base tracking-tight leading-none">
              BrandShield AI
            </div>
            <div className="text-[11px] text-teal-400 font-medium tracking-wide mt-1">
              Brand Governance Engine
            </div>
          </div>
        </div>

        {/* Mobile close button */}
        <button
          onClick={onCloseMobile}
          className="md:hidden p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Main Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <div className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          Core Governance Modules
        </div>

        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentTab === item.id;

          let badgeStyles = 'bg-slate-800 text-slate-300';
          if (item.badgeVariant === 'red') {
            badgeStyles = 'bg-red-950 text-red-300 border border-red-800/60';
          } else if (item.badgeVariant === 'purple') {
            badgeStyles = 'bg-purple-950 text-purple-300 border border-purple-800/60';
          } else if (item.badgeVariant === 'blue') {
            badgeStyles = 'bg-blue-950 text-blue-300 border border-blue-800/60';
          }

          return (
            <button
              key={item.id}
              onClick={() => handleNavClick(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition text-left group ${
                isActive
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
              }`}
            >
              <div className="flex items-center gap-3">
                <Icon
                  className={`w-4 h-4 transition ${
                    isActive ? 'text-white' : 'text-slate-400 group-hover:text-slate-200'
                  }`}
                />
                <span>{item.label}</span>
              </div>

              {item.badge && (
                <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${badgeStyles}`}>
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Human Governance Invariant Card */}
      <div className="p-3.5 m-3 rounded-lg bg-slate-950 border border-slate-800/80 text-xs">
        <div className="flex items-center gap-2 text-teal-400 font-semibold mb-1">
          <Lock className="w-3.5 h-3.5 text-teal-400" />
          <span>Human-in-the-Loop</span>
        </div>
        <p className="text-slate-400 text-[11px] leading-relaxed">
          AI suggests violations & corrections. Final approval requires explicit human authorization.
        </p>
      </div>

      {/* Version & Status Footer */}
      <div className="px-5 py-3 border-t border-slate-800 text-[11px] text-slate-400 flex items-center justify-between">
        <span>v0.1.0 (Phase 3A)</span>
        <span className="inline-flex items-center gap-1.5 text-teal-400 font-medium">
          <span className="w-1.5 h-1.5 rounded-full bg-teal-400"></span>
          Ready
        </span>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Fixed Sidebar */}
      <aside className="hidden md:block w-64 lg:w-72 flex-shrink-0 h-screen sticky top-0 border-r border-slate-800 z-30">
        {sidebarContent}
      </aside>

      {/* Mobile Drawer Backdrop */}
      {isMobileOpen && (
        <div
          onClick={onCloseMobile}
          className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-40 md:hidden transition-opacity"
        />
      )}

      {/* Mobile Drawer */}
      <div
        className={`fixed inset-y-0 left-0 w-72 z-50 transform transition-transform duration-200 ease-in-out md:hidden ${
          isMobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {sidebarContent}
      </div>
    </>
  );
};
