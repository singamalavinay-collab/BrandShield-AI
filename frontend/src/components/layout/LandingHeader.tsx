import React from 'react';
import { Shield, Server, LogIn, ArrowRight, Play } from 'lucide-react';
import { BackendHealth } from '../../types';

interface LandingHeaderProps {
  backendHealth: BackendHealth;
  onOpenLogin: () => void;
  onOpenRegister: () => void;
  onEnterDemo: () => void;
}

export const LandingHeader: React.FC<LandingHeaderProps> = ({
  backendHealth,
  onOpenLogin,
  onOpenRegister,
  onEnterDemo,
}) => {
  return (
    <header className="sticky top-0 z-40 bg-white/95 backdrop-blur-md border-b border-slate-200/80 transition-all">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* Brand Logo */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center text-white shadow-sm ring-1 ring-blue-500/20">
            <Shield className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="font-bold text-slate-900 text-base tracking-tight leading-none flex items-center gap-2">
              <span>BrandShield AI</span>
              <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200/60 hidden sm:inline-block">
                SaaS
              </span>
            </div>
            <div className="text-[11px] text-slate-500 font-medium tracking-normal mt-0.5 hidden xs:block">
              Enterprise Brand Governance Platform
            </div>
          </div>
        </div>

        {/* Center / Navigation Links */}
        <nav className="hidden md:flex items-center gap-6 text-xs font-semibold text-slate-600">
          <a
            href="#features"
            className="hover:text-blue-600 transition"
          >
            Capabilities
          </a>
          <a
            href="#governance"
            className="hover:text-blue-600 transition"
          >
            Human Invariant
          </a>
          <a
            href="#architecture"
            className="hover:text-blue-600 transition"
          >
            Multi-Tenant Security
          </a>
        </nav>

        {/* Right Actions */}
        <div className="flex items-center gap-2.5 sm:gap-3">
          {/* Live System Health Badge */}
          <div
            title={backendHealth.is_connected ? 'Backend API Connected' : 'Backend API Offline'}
            className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-slate-100 text-slate-700 border border-slate-200/80"
          >
            <Server className="w-3 h-3 text-slate-500" />
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                backendHealth.is_connected ? 'bg-emerald-500 ring-2 ring-emerald-200' : 'bg-amber-500 ring-2 ring-amber-200'
              }`}
            />
            <span className="text-[10px] font-mono">
              {backendHealth.is_connected ? 'API v0.1.0' : 'API Offline'}
            </span>
          </div>

          {/* Interactive Demo Sandbox Button */}
          <button
            onClick={onEnterDemo}
            className="hidden lg:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-700 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 border border-slate-200/80 transition"
            title="Explore pre-seeded demonstration drafts and brand rules"
          >
            <Play className="w-3 h-3 text-blue-600 fill-blue-600" />
            <span>Interactive Demo</span>
          </button>

          {/* Sign In */}
          <button
            onClick={onOpenLogin}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-700 hover:text-slate-900 hover:bg-slate-100 transition"
          >
            <LogIn className="w-3.5 h-3.5" />
            <span>Sign In</span>
          </button>

          {/* Get Started / Create Workspace */}
          <button
            onClick={onOpenRegister}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 shadow-sm transition transform active:scale-[0.98]"
          >
            <span>Get Started</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </header>
  );
};
