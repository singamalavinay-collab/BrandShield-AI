import React, { useState } from 'react';
import {
  BookOpen,
  Search,
  Plus,
  CheckCircle2,
  XCircle,
  Tag,
  SlidersHorizontal,
  X,
  AlertCircle,
} from 'lucide-react';
import { BrandGuideline, RuleType, SeverityLevel, AuthUser } from '../types';
import { StatusBadge } from '../components/common/StatusBadge';
import { EmptyState } from '../components/common/EmptyState';

interface GuidelinesPageProps {
  guidelines: BrandGuideline[];
  onToggleActive: (id: string) => void;
  onAddGuideline: (newGuideline: Omit<BrandGuideline, 'id'>) => Promise<void> | void;
  currentUser?: AuthUser | null;
}

export const GuidelinesPage: React.FC<GuidelinesPageProps> = ({
  guidelines,
  onToggleActive,
  onAddGuideline,
  currentUser,
}) => {
  const isAdmin = currentUser?.role === 'ADMIN';
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedType, setSelectedType] = useState<string>('all');
  const [selectedSeverity, setSelectedSeverity] = useState<string>('all');
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Form State for creating a new guideline
  const [formName, setFormName] = useState('');
  const [formType, setFormType] = useState<RuleType>('tone_of_voice');
  const [formSeverity, setFormSeverity] = useState<SeverityLevel>('medium');
  const [formDescription, setFormDescription] = useState('');
  const [formDirective, setFormDirective] = useState('');
  const [formApprovedExample, setFormApprovedExample] = useState('');
  const [formProhibitedExample, setFormProhibitedExample] = useState('');
  const [formTags, setFormTags] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Filter guidelines
  const filteredGuidelines = guidelines.filter((g) => {
    const matchesSearch =
      g.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      g.directive.toLowerCase().includes(searchQuery.toLowerCase()) ||
      g.tags.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesType = selectedType === 'all' || g.rule_type === selectedType;
    const matchesSeverity = selectedSeverity === 'all' || g.severity === selectedSeverity;

    return matchesSearch && matchesType && matchesSeverity;
  });

  const handleCreateGuideline = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;
    setFormError(null);

    if (formName.trim().length < 3) {
      setFormError('Rule name must be at least 3 characters.');
      return;
    }
    if (formDirective.trim().length < 10) {
      setFormError('Directive must be at least 10 characters.');
      return;
    }
    if (formApprovedExample.trim().length === 0) {
      setFormError('Please provide at least one approved example.');
      return;
    }
    if (formProhibitedExample.trim().length === 0) {
      setFormError('Please provide at least one prohibited example.');
      return;
    }

    const tagsArray = formTags
      .split(',')
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

    try {
      setIsSubmitting(true);
      await onAddGuideline({
        name: formName.trim(),
        rule_type: formType,
        severity: formSeverity,
        description: formDescription.trim() || formDirective.trim(),
        directive: formDirective.trim(),
        examples_approved: [formApprovedExample.trim()],
        examples_prohibited: [formProhibitedExample.trim()],
        tags: tagsArray.length > 0 ? tagsArray : ['custom-rule'],
        is_active: true,
        is_demo: false,
      });

      // Reset and close
      setFormName('');
      setFormDescription('');
      setFormDirective('');
      setFormApprovedExample('');
      setFormProhibitedExample('');
      setFormTags('');
      setIsDrawerOpen(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to register brand guideline';
      setFormError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Page Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Approved Brand Guidelines</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Manage official brand standards, legal compliance directives, and messaging rules.
          </p>
        </div>

        {isAdmin ? (
          <button
            onClick={() => setIsDrawerOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition shadow-sm self-start sm:self-center"
          >
            <Plus className="w-4 h-4" />
            Add Brand Rule
          </button>
        ) : (
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 text-xs font-medium border border-slate-200 self-start sm:self-center">
            <span>Read-Only Guidelines ({currentUser ? currentUser.role : 'Guest'})</span>
          </div>
        )}
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/80 shadow-subtle flex flex-col md:flex-row gap-3">
        {/* Search Input */}
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search guidelines by title, clause, or tag..."
            className="w-full pl-9 pr-3 py-2 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 text-slate-800 placeholder-slate-400"
          />
        </div>

        {/* Category Filter */}
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="w-4 h-4 text-slate-400 hidden sm:block" />
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="text-xs py-2 px-3 rounded-lg border border-slate-200 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
          >
            <option value="all">All Categories</option>
            <option value="tone_of_voice">Tone of Voice</option>
            <option value="terminology">Terminology</option>
            <option value="formatting">Formatting</option>
            <option value="legal_regulatory">Legal & Regulatory</option>
            <option value="prohibited_claims">Prohibited Claims</option>
            <option value="trademark_usage">Trademark Usage</option>
          </select>

          {/* Severity Filter */}
          <select
            value={selectedSeverity}
            onChange={(e) => setSelectedSeverity(e.target.value)}
            className="text-xs py-2 px-3 rounded-lg border border-slate-200 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
          >
            <option value="all">All Severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
      </div>

      {/* Guidelines Grid */}
      {filteredGuidelines.length > 0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {filteredGuidelines.map((guideline) => (
            <div
              key={guideline.id}
              className={`bg-white rounded-xl border transition p-5 flex flex-col justify-between ${
                guideline.is_active
                  ? 'border-slate-200/90 shadow-subtle hover:border-slate-300'
                  : 'border-slate-200 bg-slate-50/60 opacity-75'
              }`}
            >
              <div>
                {/* Card Top: Badges and Toggle */}
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge severity={guideline.severity} />
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200 uppercase tracking-wider">
                      {guideline.rule_type.replace(/_/g, ' ')}
                    </span>
                    {guideline.is_demo && (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-100">
                        Template Rule
                      </span>
                    )}
                  </div>

                  {/* Active Toggle Switch for ADMIN, Read-Only Status Badge for non-admin */}
                  {isAdmin ? (
                    <label className="inline-flex items-center cursor-pointer" title="Toggle active status">
                      <input
                        type="checkbox"
                        checked={guideline.is_active}
                        onChange={() => onToggleActive(guideline.id)}
                        className="sr-only peer"
                      />
                      <div className="w-8 h-4 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-blue-600 relative"></div>
                    </label>
                  ) : (
                    <span
                      className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border ${
                        guideline.is_active
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                          : 'bg-slate-100 text-slate-500 border-slate-200'
                      }`}
                      title={guideline.is_active ? 'Active guideline rule' : 'Inactive guideline rule'}
                    >
                      {guideline.is_active ? 'Active' : 'Inactive'}
                    </span>
                  )}
                </div>

                {/* Title & Directive */}
                <h3 className="text-base font-bold text-slate-900 tracking-tight mb-1.5">
                  {guideline.name}
                </h3>
                <p className="text-xs text-slate-600 leading-relaxed mb-4">
                  {guideline.directive}
                </p>

                {/* Approved vs Prohibited Examples Box */}
                <div className="space-y-2 mb-4 bg-slate-50 p-3 rounded-lg border border-slate-100 text-xs">
                  {guideline.examples_approved.map((example, idx) => (
                    <div key={`app-${idx}`} className="flex items-start gap-2 text-slate-700">
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0 mt-0.5" />
                      <span className="leading-tight"><strong className="text-emerald-800 font-medium">Approved:</strong> {example}</span>
                    </div>
                  ))}
                  {guideline.examples_prohibited.map((example, idx) => (
                    <div key={`proh-${idx}`} className="flex items-start gap-2 text-slate-700">
                      <XCircle className="w-3.5 h-3.5 text-rose-600 flex-shrink-0 mt-0.5" />
                      <span className="leading-tight"><strong className="text-rose-800 font-medium">Prohibited:</strong> {example}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Tags */}
              <div className="flex flex-wrap gap-1.5 pt-3 border-t border-slate-100">
                {guideline.tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 text-[11px] text-slate-500 bg-slate-100 px-2 py-0.5 rounded"
                  >
                    <Tag className="w-2.5 h-2.5" />
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={BookOpen}
          title="No Brand Guidelines Found"
          description="No guidelines match your search query or filter selection. Clear filters or add a new guideline to continue."
          actionText="Clear Filters"
          onAction={() => {
            setSearchQuery('');
            setSelectedType('all');
            setSelectedSeverity('all');
          }}
        />
      )}

      {/* Add Guideline Slide-Over Drawer */}
      {isDrawerOpen && (
        <div className="fixed inset-0 z-50 overflow-hidden">
          <div
            onClick={() => setIsDrawerOpen(false)}
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-xs transition-opacity"
          />

          <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
            <div className="w-screen max-w-md bg-white shadow-xl flex flex-col">
              {/* Drawer Header */}
              <div className="px-6 py-5 border-b border-slate-200 flex items-center justify-between">
                <div>
                  <h3 className="text-base font-bold text-slate-900">Define Brand Rule</h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Create a new verifiable guideline for content compliance
                  </p>
                </div>
                <button
                  onClick={() => setIsDrawerOpen(false)}
                  className="p-1 rounded-md text-slate-400 hover:text-slate-600"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Drawer Body Form */}
              <form onSubmit={handleCreateGuideline} className="flex-1 overflow-y-auto p-6 space-y-4 text-xs">
                {formError && (
                  <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <span>{formError}</span>
                  </div>
                )}

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Guideline Name <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="e.g. Official Product Suffix Convention"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block font-semibold text-slate-700 mb-1">Rule Category</label>
                    <select
                      value={formType}
                      onChange={(e) => setFormType(e.target.value as RuleType)}
                      className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                    >
                      <option value="tone_of_voice">Tone of Voice</option>
                      <option value="terminology">Terminology</option>
                      <option value="formatting">Formatting</option>
                      <option value="legal_regulatory">Legal & Regulatory</option>
                      <option value="prohibited_claims">Prohibited Claims</option>
                      <option value="trademark_usage">Trademark Usage</option>
                    </select>
                  </div>

                  <div>
                    <label className="block font-semibold text-slate-700 mb-1">Severity Level</label>
                    <select
                      value={formSeverity}
                      onChange={(e) => setFormSeverity(e.target.value as SeverityLevel)}
                      className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                    >
                      <option value="critical">Critical</option>
                      <option value="high">High</option>
                      <option value="medium">Medium</option>
                      <option value="low">Low</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Rule Directive & Rationale <span className="text-rose-500">*</span>
                  </label>
                  <textarea
                    rows={3}
                    value={formDirective}
                    onChange={(e) => setFormDirective(e.target.value)}
                    placeholder="State the exact governance instruction and requirement clearly..."
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Approved Phrasing Example <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={formApprovedExample}
                    onChange={(e) => setFormApprovedExample(e.target.value)}
                    placeholder="e.g. BrandShield AI enables rapid compliance."
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Prohibited Phrasing Example <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={formProhibitedExample}
                    onChange={(e) => setFormProhibitedExample(e.target.value)}
                    placeholder="e.g. Brandshield solves all marketing issues."
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Tags (comma separated)</label>
                  <input
                    type="text"
                    value={formTags}
                    onChange={(e) => setFormTags(e.target.value)}
                    placeholder="e.g. trademark, product-team, enterprise"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  />
                </div>

                <div className="pt-4 border-t border-slate-200 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setIsDrawerOpen(false)}
                    className="px-4 py-2 border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 transition font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition font-medium shadow-sm disabled:opacity-50"
                  >
                    {isSubmitting ? 'Saving...' : 'Save Guideline'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
