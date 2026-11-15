import React, { useState } from 'react';
import {
  Send,
  Save,
  AlertCircle,
  CheckCircle2,
  HelpCircle,
  RefreshCw,
} from 'lucide-react';
import { TargetChannel, ContentSubmission, AuthUser } from '../types';

interface SubmissionPageProps {
  onSubmitContent: (
    newSub: Omit<ContentSubmission, 'id' | 'created_at' | 'version' | 'status'>,
    shouldInspect: boolean
  ) => Promise<void> | void;
  dbOffline?: boolean;
  currentUser?: AuthUser | null;
}

export const SubmissionPage: React.FC<SubmissionPageProps> = ({
  onSubmitContent,
  dbOffline = false,
  currentUser,
}) => {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [targetChannel, setTargetChannel] = useState<TargetChannel>('twitter_x');
  const [targetAudience, setTargetAudience] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [presetNotice, setPresetNotice] = useState<string | null>(null);

  // Character and word counters
  const charCount = content.length;
  const wordCount = content.trim().length > 0 ? content.trim().split(/\s+/).length : 0;

  // Preset Template loader for testing
  const loadPreset = (presetType: 'violations' | 'compliant') => {
    setSuccessMessage(null);
    setValidationError(null);

    if (presetType === 'violations') {
      setTitle('Q2 Enterprise Feature Launch');
      setTargetChannel('twitter_x');
      setTargetAudience('Tech Executives & Risk Managers');
      setContent(
        'We are excited to launch Brandshield! Our revolutionary miracle AI tool guarantees 100% brand compliance everywhere. It automatically posts to socialmedia without any human delay!'
      );
      setPresetNotice('Demonstration draft with 4 rule violations loaded.');
    } else {
      setTitle('Brand Compliance Monthly Overview');
      setTargetChannel('email_newsletter');
      setTargetAudience('Internal Brand & Marketing Stakeholders');
      setContent(
        'BrandShield AI provides rigorous real-time monitoring across all brand communications. All AI-generated correction suggestions require explicit human authorization prior to external distribution, ensuring compliance with our master brand identity standards.'
      );
      setPresetNotice('Compliant demonstration draft loaded.');
    }
  };

  const handleAction = async (isSubmittingForInspection: boolean) => {
    if (isSubmitting) return;

    setValidationError(null);
    setSuccessMessage(null);

    if (title.trim().length < 3) {
      setValidationError('Submission title must be at least 3 characters long.');
      return;
    }

    if (content.trim().length < 10) {
      setValidationError('Content text must be at least 10 characters long.');
      return;
    }

    try {
      setIsSubmitting(true);
      await onSubmitContent(
        {
          title: title.trim(),
          content: content.trim(),
          target_channel: targetChannel,
          target_audience: targetAudience.trim() || 'General Enterprise Audience',
          author_name: currentUser?.full_name || 'Content Creator (Authenticated)',
          is_demo: false,
        },
        isSubmittingForInspection
      );

      if (!isSubmittingForInspection) {
        setSuccessMessage('Content successfully saved as draft in the governance ledger.');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to submit content';
      setValidationError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Content Submission Workspace</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Submit marketing copy, social drafts, or corporate announcements for brand compliance inspection.
          </p>
        </div>

        {/* Quick Presets Menu */}
        <div className="flex items-center gap-2 self-start sm:self-center">
          <span className="text-xs text-slate-500 font-medium hidden sm:inline">Load Demo Preset:</span>
          <button
            type="button"
            onClick={() => loadPreset('violations')}
            className="px-2.5 py-1 text-xs font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 rounded-md border border-amber-200 transition"
            title="Load sample demonstration draft containing 4 intentional violations"
          >
            Sample with Violations
          </button>
          <button
            type="button"
            onClick={() => loadPreset('compliant')}
            className="px-2.5 py-1 text-xs font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 rounded-md border border-emerald-200 transition"
            title="Load sample compliant demonstration draft"
          >
            Compliant Sample
          </button>
        </div>
      </div>

      {dbOffline && (
        <div className="p-3.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 text-xs flex items-center gap-2.5">
          <AlertCircle className="w-4 h-4 flex-shrink-0 text-amber-600" />
          <div>
            <span className="font-semibold">Database Service Offline:</span> Submissions cannot run automated compliance inspections until the database is connected. Drafts will only be staged locally.
          </div>
        </div>
      )}

      {presetNotice && (
        <div className="p-3 rounded-lg bg-blue-50 border border-blue-200 text-blue-800 text-xs flex items-center justify-between">
          <span>{presetNotice}</span>
          <button
            onClick={() => setPresetNotice(null)}
            className="text-blue-500 hover:text-blue-700 font-bold ml-2"
          >
            ×
          </button>
        </div>
      )}

      {/* Main Drafting Form Card */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-subtle p-6 space-y-5">
        {validationError && (
          <div className="p-3.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-600" />
            <span>{validationError}</span>
          </div>
        )}

        {successMessage && (
          <div className="p-3.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-emerald-600" />
            <span>{successMessage}</span>
          </div>
        )}

        {/* Title Input */}
        <div>
          <label className="block text-xs font-semibold text-slate-800 mb-1.5">
            Submission Title <span className="text-rose-500">*</span>
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={isSubmitting}
            placeholder="e.g. Q2 Product Announcement Thread"
            className="w-full px-3.5 py-2.5 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 text-slate-900 placeholder-slate-400 font-medium"
          />
        </div>

        {/* Target Channel and Audience Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-800 mb-1.5">
              Target Distribution Channel <span className="text-rose-500">*</span>
            </label>
            <select
              value={targetChannel}
              onChange={(e) => setTargetChannel(e.target.value as TargetChannel)}
              disabled={isSubmitting}
              className="w-full px-3.5 py-2.5 text-xs rounded-lg border border-slate-200 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 font-medium"
            >
              <option value="twitter_x">Twitter / X Post</option>
              <option value="linkedin">LinkedIn Post</option>
              <option value="email_newsletter">Email Newsletter</option>
              <option value="blog_post">Blog Post / Article</option>
              <option value="advertisement">Paid Advertisement Copy</option>
              <option value="press_release">Official Press Release</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-800 mb-1.5">
              Target Audience
            </label>
            <input
              type="text"
              value={targetAudience}
              onChange={(e) => setTargetAudience(e.target.value)}
              disabled={isSubmitting}
              placeholder="e.g. Enterprise CMOs, IT Leaders"
              className="w-full px-3.5 py-2.5 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 text-slate-900 placeholder-slate-400 font-medium"
            />
          </div>
        </div>

        {/* Content Textarea */}
        <div>
          <div className="flex justify-between items-center mb-1.5">
            <label className="block text-xs font-semibold text-slate-800">
              Draft Content for Verification <span className="text-rose-500">*</span>
            </label>
            <div className="text-[11px] text-slate-400 flex items-center gap-3">
              <span>{wordCount} words</span>
              <span>•</span>
              <span className={targetChannel === 'twitter_x' && charCount > 280 ? 'text-amber-600 font-bold' : ''}>
                {charCount} characters {targetChannel === 'twitter_x' && '/ 280 max'}
              </span>
            </div>
          </div>
          <textarea
            rows={7}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            disabled={isSubmitting}
            placeholder="Paste or compose your content draft here. The governance engine will scan against all active brand rules, legal directives, and tone standards..."
            className="w-full p-3.5 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 text-slate-900 placeholder-slate-400 leading-relaxed font-normal"
          />
        </div>

        {/* Action Controls & Governance Notice */}
        <div className="pt-4 border-t border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <HelpCircle className="w-3.5 h-3.5 text-slate-400" />
            <span>Connected to FastAPI backend with transaction validation.</span>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => handleAction(false)}
              disabled={isSubmitting}
              className="px-4 py-2 rounded-lg border border-slate-200 text-slate-700 bg-white hover:bg-slate-50 text-xs font-semibold transition flex items-center gap-1.5 disabled:opacity-50"
            >
              {isSubmitting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5 text-slate-500" />}
              Save Draft
            </button>

            <button
              type="button"
              onClick={() => handleAction(true)}
              disabled={isSubmitting}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold transition shadow-sm flex items-center gap-1.5 disabled:opacity-50"
            >
              {isSubmitting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              Submit for Compliance Inspection
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
