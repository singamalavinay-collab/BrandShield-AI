import React from 'react';
import {
  Shield,
  Lock,
  ArrowRight,
  Play,
  CheckCircle2,
  Sparkles,
  Building2,
  Search,
  History,
} from 'lucide-react';
import { BackendHealth } from '../types';

interface LandingPageProps {
  backendHealth: BackendHealth;
  onOpenLogin: () => void;
  onOpenRegister: () => void;
  onEnterDemo: () => void;
}

export const LandingPage: React.FC<LandingPageProps> = ({
  backendHealth,
  onOpenLogin,
  onOpenRegister,
  onEnterDemo,
}) => {
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col text-slate-900 antialiased">
      {/* 1. Hero Section */}
      <section className="relative pt-12 pb-20 md:pt-20 md:pb-28 overflow-hidden border-b border-slate-200/70 bg-gradient-to-b from-white via-white to-slate-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10 text-center">
          {/* Eyebrow badge */}
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200/80 mb-6 shadow-subtle animate-in fade-in slide-in-from-bottom-2 duration-300">
            <Sparkles className="w-3.5 h-3.5 text-blue-600" />
            <span>Enterprise Brand Governance Platform</span>
            <span className="text-slate-300">•</span>
            <span className="text-slate-600 font-normal">Human-in-the-Loop AI</span>
          </div>

          {/* Main Headline */}
          <h1 className="text-3xl sm:text-5xl lg:text-6xl font-black text-slate-950 tracking-tight max-w-4xl mx-auto leading-[1.12]">
            Deterministic Brand Compliance with{' '}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600">
              Inviolable Human Oversight
            </span>
          </h1>

          {/* Subtitle */}
          <p className="text-base sm:text-lg text-slate-600 max-w-2xl mx-auto mt-6 leading-relaxed">
            Safeguard your enterprise reputation across social, web, and press channels. BrandShield AI pairs deterministic violation detection with authoritative AI corrections—enforcing the inviolable rule that <strong>AI proposes, but only authorized humans approve</strong>.
          </p>

          {/* Call to Action Buttons */}
          <div className="mt-8 sm:mt-10 flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4 max-w-md mx-auto">
            <button
              onClick={onOpenRegister}
              className="w-full sm:w-auto px-6 py-3.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm shadow-sm transition transform hover:-translate-y-0.5 active:translate-y-0 flex items-center justify-center gap-2 group"
            >
              <span>Create Organization Workspace</span>
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-1" />
            </button>

            <button
              onClick={onOpenLogin}
              className="w-full sm:w-auto px-6 py-3.5 rounded-xl bg-white hover:bg-slate-50 text-slate-800 font-semibold text-sm border border-slate-300 shadow-subtle transition flex items-center justify-center gap-2"
            >
              <span>Sign In to Existing Tenant</span>
            </button>
          </div>

          {/* Sandbox Demo Callout */}
          <div className="mt-4">
            <button
              onClick={onEnterDemo}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-blue-600 transition p-1"
            >
              <Play className="w-3 h-3 text-blue-600 fill-blue-600" />
              <span>Or explore pre-seeded demonstration drafts in sandbox mode →</span>
            </button>
          </div>

          {/* Trust Invariant Indicators */}
          <div className="mt-14 pt-8 border-t border-slate-200/80 max-w-4xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-4 text-left">
            <div className="p-3 bg-white rounded-lg border border-slate-200/60 shadow-subtle flex items-start gap-2.5">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-xs font-bold text-slate-900 leading-tight">Deterministic Rules</div>
                <div className="text-[11px] text-slate-500 leading-snug mt-0.5">Exact clause evidence</div>
              </div>
            </div>

            <div className="p-3 bg-white rounded-lg border border-slate-200/60 shadow-subtle flex items-start gap-2.5">
              <Lock className="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-xs font-bold text-slate-900 leading-tight">Human Authority</div>
                <div className="text-[11px] text-slate-500 leading-snug mt-0.5">AI never auto-approves</div>
              </div>
            </div>

            <div className="p-3 bg-white rounded-lg border border-slate-200/60 shadow-subtle flex items-start gap-2.5">
              <Building2 className="w-4 h-4 text-indigo-600 flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-xs font-bold text-slate-900 leading-tight">Multi-Tenant Isolation</div>
                <div className="text-[11px] text-slate-500 leading-snug mt-0.5">Discrete customer spaces</div>
              </div>
            </div>

            <div className="p-3 bg-white rounded-lg border border-slate-200/60 shadow-subtle flex items-start gap-2.5">
              <History className="w-4 h-4 text-purple-600 flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-xs font-bold text-slate-900 leading-tight">Immutable Audit Ledger</div>
                <div className="text-[11px] text-slate-500 leading-snug mt-0.5">DB-level tamper protection</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 2. Core Pillars & Architecture */}
      <section id="features" className="py-16 md:py-24 bg-white border-b border-slate-200/80">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <h2 className="text-xs font-bold uppercase tracking-wider text-blue-600 mb-2">
              Enterprise Governance Pillars
            </h2>
            <h3 className="text-2xl sm:text-3xl font-extrabold text-slate-950 tracking-tight">
              Built for organizations that cannot afford compliance hallucinations
            </h3>
            <p className="text-sm text-slate-600 mt-3">
              Unlike generic LLM wrappers, BrandShield AI provides a deterministic governance engine with verified evidence chains and enforceable organizational boundaries.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Pillar 1 */}
            <div className="p-7 rounded-2xl bg-slate-50/70 border border-slate-200/80 shadow-subtle hover:border-slate-300 transition flex flex-col justify-between">
              <div>
                <div className="w-12 h-12 rounded-xl bg-blue-100 text-blue-700 flex items-center justify-center mb-5">
                  <Search className="w-6 h-6" />
                </div>
                <h4 className="text-lg font-bold text-slate-950 tracking-tight">
                  Deterministic Clause Verification
                </h4>
                <p className="text-xs sm:text-sm text-slate-600 mt-2.5 leading-relaxed">
                  Every flagged draft violation links to an exact source clause in your trademark, legal, or brand guideline documents. Confident, citation-backed scoring eliminates subjective guesswork.
                </p>
              </div>
              <ul className="mt-6 pt-6 border-t border-slate-200/60 space-y-2 text-xs text-slate-700 font-medium">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-blue-600" />
                  <span>Exact clause citations with confidence ratings</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-blue-600" />
                  <span>Channel-specific rule enforcement (X, LinkedIn, Blog)</span>
                </li>
              </ul>
            </div>

            {/* Pillar 2 */}
            <div className="p-7 rounded-2xl bg-slate-50/70 border border-slate-200/80 shadow-subtle hover:border-slate-300 transition flex flex-col justify-between ring-1 ring-blue-500/10">
              <div>
                <div className="w-12 h-12 rounded-xl bg-indigo-100 text-indigo-700 flex items-center justify-center mb-5">
                  <Lock className="w-6 h-6" />
                </div>
                <h4 className="text-lg font-bold text-slate-950 tracking-tight">
                  Mandatory Human Authority
                </h4>
                <p className="text-xs sm:text-sm text-slate-600 mt-2.5 leading-relaxed">
                  Our system architecture enforces the non-negotiable invariant: <strong>AI may analyze and propose remediations, but only authorized human reviewers can approve content for release.</strong>
                </p>
              </div>
              <ul className="mt-6 pt-6 border-t border-slate-200/60 space-y-2 text-xs text-slate-700 font-medium">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-indigo-600" />
                  <span>Database-level CHECK constraint on approvals</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-indigo-600" />
                  <span>Rejection mandates actionable human feedback</span>
                </li>
              </ul>
            </div>

            {/* Pillar 3 */}
            <div className="p-7 rounded-2xl bg-slate-50/70 border border-slate-200/80 shadow-subtle hover:border-slate-300 transition flex flex-col justify-between">
              <div>
                <div className="w-12 h-12 rounded-xl bg-teal-100 text-teal-700 flex items-center justify-center mb-5">
                  <Building2 className="w-6 h-6" />
                </div>
                <h4 className="text-lg font-bold text-slate-950 tracking-tight">
                  Self-Service Tenant Isolation
                </h4>
                <p className="text-xs sm:text-sm text-slate-600 mt-2.5 leading-relaxed">
                  Each organization workspace operates in strict cryptographic isolation. The initial registrant gains full administrator privileges, and invites team members through secure, short-lived tokens.
                </p>
              </div>
              <ul className="mt-6 pt-6 border-t border-slate-200/60 space-y-2 text-xs text-slate-700 font-medium">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-teal-600" />
                  <span>Row-Level Security & tenant-scoped queries</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-teal-600" />
                  <span>Short-lived hashed invitation tokens (7 days)</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* 3. Governance Lifecycle Walkthrough */}
      <section id="governance" className="py-16 md:py-24 bg-slate-50 border-b border-slate-200/80">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <h2 className="text-xs font-bold uppercase tracking-wider text-blue-600 mb-2">
              The 4-Stage Governance Loop
            </h2>
            <h3 className="text-2xl sm:text-3xl font-extrabold text-slate-950 tracking-tight">
              From creative draft to verified publication
            </h3>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="bg-white p-6 rounded-xl border border-slate-200/80 shadow-subtle">
              <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 font-black text-xs flex items-center justify-center mb-3">
                01
              </div>
              <h4 className="font-bold text-sm text-slate-900">Draft Ingestion</h4>
              <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
                Creators stage marketing copy, social posts, or press releases configured for destination publishing channels.
              </p>
            </div>

            <div className="bg-white p-6 rounded-xl border border-slate-200/80 shadow-subtle">
              <div className="w-8 h-8 rounded-lg bg-indigo-50 text-indigo-600 font-black text-xs flex items-center justify-center mb-3">
                02
              </div>
              <h4 className="font-bold text-sm text-slate-900">Automated Audit</h4>
              <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
                Evaluation engine checks drafts against active brand guidelines, generating severity-rated findings with legal citations.
              </p>
            </div>

            <div className="bg-white p-6 rounded-xl border border-slate-200/80 shadow-subtle">
              <div className="w-8 h-8 rounded-lg bg-teal-50 text-teal-600 font-black text-xs flex items-center justify-center mb-3">
                03
              </div>
              <h4 className="font-bold text-sm text-slate-900">AI Remediation</h4>
              <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
                Authoritative AI suggests side-by-side corrected drafts aligning with your trademark and tone guidelines.
              </p>
            </div>

            <div className="bg-white p-6 rounded-xl border border-slate-200/80 shadow-subtle ring-1 ring-purple-500/20">
              <div className="w-8 h-8 rounded-lg bg-purple-50 text-purple-600 font-black text-xs flex items-center justify-center mb-3">
                04
              </div>
              <h4 className="font-bold text-sm text-slate-900">Human Approval Gate</h4>
              <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
                Authorized human reviewers execute Approve, Edit & Approve, or Reject with full immutable audit recording.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 4. Bottom Call to Action */}
      <section className="py-16 md:py-20 bg-slate-950 text-white text-center">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-blue-950 text-blue-300 border border-blue-800/80 mb-6">
            <Building2 className="w-3.5 h-3.5 text-blue-400" />
            <span>Dedicated Multi-Tenant Architecture</span>
          </div>

          <h3 className="text-2xl sm:text-4xl font-black text-white tracking-tight">
            Ready to establish automated brand governance?
          </h3>
          <p className="text-sm sm:text-base text-slate-400 mt-4 max-w-xl mx-auto leading-relaxed">
            Create an isolated organization workspace for your brand in seconds, or test the workflow in our sandbox demo.
          </p>

          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
            <button
              onClick={onOpenRegister}
              className="w-full sm:w-auto px-7 py-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm transition shadow-sm flex items-center justify-center gap-2"
            >
              <span>Get Started Free</span>
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={onEnterDemo}
              className="w-full sm:w-auto px-7 py-3 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 font-semibold text-sm border border-slate-800 transition flex items-center justify-center gap-2"
            >
              <Play className="w-3.5 h-3.5 text-blue-400 fill-blue-400" />
              <span>Explore Interactive Demo</span>
            </button>
          </div>
        </div>
      </section>

      {/* 5. Footer */}
      <footer className="py-8 bg-white border-t border-slate-200/80 text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md bg-blue-600 flex items-center justify-center text-white font-bold text-xs">
              <Shield className="w-3.5 h-3.5" />
            </div>
            <span className="font-semibold text-slate-700">BrandShield AI</span>
            <span>— Enterprise Brand Governance</span>
          </div>
          <div className="flex items-center gap-4 text-[11px] text-slate-400">
            <span>CodeNova India 2026</span>
            <span>•</span>
            <span>FastAPI + React SaaS Architecture</span>
            <span>•</span>
            <span className={backendHealth.is_connected ? 'text-emerald-600' : 'text-amber-600'}>
              {backendHealth.is_connected ? 'API Online' : 'API Offline'}
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
};
