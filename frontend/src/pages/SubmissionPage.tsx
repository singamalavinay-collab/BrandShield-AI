import React, { useState, useEffect, useRef } from 'react';
import {
  Send,
  Save,
  AlertCircle,
  CheckCircle2,
  HelpCircle,
  RefreshCw,
  FileText,
  Image as ImageIcon,
  Mic,
  Video as VideoIcon,
  Camera,
  UploadCloud,
  Trash2,
  FileCheck,
} from 'lucide-react';
import { TargetChannel, ContentSubmission, AuthUser, InputMediaType } from '../types';

interface SubmissionPageProps {
  onSubmitContent: (
    newSub: Omit<ContentSubmission, 'id' | 'created_at' | 'version' | 'status'>,
    shouldInspect: boolean
  ) => Promise<void> | void;
  onSubmitUpload?: (
    formData: FormData,
    metadata: {
      title: string;
      target_channel: TargetChannel;
      target_audience?: string;
      media_type: InputMediaType;
      content?: string;
      author_name: string;
    },
    shouldInspect: boolean
  ) => Promise<void> | void;
  dbOffline?: boolean;
  currentUser?: AuthUser | null;
}

const MODALITY_CONFIG: Record<
  InputMediaType,
  {
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    description: string;
    acceptedFormats: string;
    acceptMimes: string;
  }
> = {
  text: {
    label: 'Text Draft',
    icon: FileText,
    description: 'Type or paste marketing copy, social drafts, and messaging.',
    acceptedFormats: 'Plain text',
    acceptMimes: '',
  },
  image: {
    label: 'Image Asset',
    icon: ImageIcon,
    description: 'Upload banner ads, screenshots, logos, or snap with camera.',
    acceptedFormats: 'JPEG, PNG, WebP (max 10MB)',
    acceptMimes: 'image/jpeg,image/png,image/webp',
  },
  audio: {
    label: 'Audio Track',
    icon: Mic,
    description: 'Upload podcast audio, voiceovers, or customer call recordings.',
    acceptedFormats: 'MP3, WAV (max 10MB)',
    acceptMimes: 'audio/mpeg,audio/wav',
  },
  video: {
    label: 'Video Clip',
    icon: VideoIcon,
    description: 'Upload video spots, product demos, or screencasts.',
    acceptedFormats: 'MP4, WebM (max 10MB)',
    acceptMimes: 'video/mp4,video/webm',
  },
  document: {
    label: 'Document',
    icon: FileCheck,
    description: 'Upload brand guidelines, press releases, or marketing briefs.',
    acceptedFormats: 'PDF, DOCX (max 10MB)',
    acceptMimes: '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  },
};

export const SubmissionPage: React.FC<SubmissionPageProps> = ({
  onSubmitContent,
  onSubmitUpload,
  dbOffline = false,
  currentUser,
}) => {
  const [activeModality, setActiveModality] = useState<InputMediaType>('text');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [targetChannel, setTargetChannel] = useState<TargetChannel>('twitter_x');
  const [targetAudience, setTargetAudience] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [presetNotice, setPresetNotice] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);

  // Revoke object URL on unmount or file replacement
  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  // Character and word counters
  const charCount = content.length;
  const wordCount = content.trim().length > 0 ? content.trim().split(/\s+/).length : 0;

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  const handleRemoveFile = () => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    if (cameraInputRef.current) {
      cameraInputRef.current.value = '';
    }
  };

  const handleSelectModality = (modality: InputMediaType) => {
    if (modality === activeModality) return;
    setActiveModality(modality);
    handleRemoveFile();
    setValidationError(null);
    setSuccessMessage(null);
  };

  const validateAndSetFile = (file: File | null) => {
    setValidationError(null);
    setSuccessMessage(null);
    if (!file) return;

    // 10MB client check: 10 * 1024 * 1024 = 10,485,760 bytes
    const MAX_UPLOAD_SIZE = 10 * 1024 * 1024;
    if (file.size > MAX_UPLOAD_SIZE) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
      setValidationError(
        `File "${file.name}" exceeds the maximum upload ceiling of 10MB (${sizeMB} MB). Please compress or choose a smaller file.`
      );
      return;
    }

    if (file.size === 0) {
      setValidationError(`File "${file.name}" is empty (0 bytes).`);
      return;
    }

    const ext = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.')).toLowerCase() : '';
    const mime = file.type.toLowerCase();

    if (activeModality === 'image') {
      const validExts = ['.jpg', '.jpeg', '.png', '.webp'];
      const validMimes = ['image/jpeg', 'image/png', 'image/webp'];
      if (!validExts.includes(ext) && !validMimes.some((m) => mime.includes(m))) {
        setValidationError(
          `Invalid image file format for "${file.name}". Only JPEG, PNG, and WebP images are supported.`
        );
        return;
      }
    } else if (activeModality === 'audio') {
      const validExts = ['.mp3', '.wav'];
      const validMimes = ['audio/mpeg', 'audio/wav', 'audio/x-wav', 'audio/mp3'];
      if (!validExts.includes(ext) && !validMimes.some((m) => mime.includes(m))) {
        setValidationError(
          `Invalid audio file format for "${file.name}". Only MP3 and WAV audio files are supported.`
        );
        return;
      }
    } else if (activeModality === 'video') {
      const validExts = ['.mp4', '.webm'];
      const validMimes = ['video/mp4', 'video/webm'];
      if (!validExts.includes(ext) && !validMimes.some((m) => mime.includes(m))) {
        setValidationError(
          `Invalid video file format for "${file.name}". Only MP4 and WebM video files are supported.`
        );
        return;
      }
    } else if (activeModality === 'document') {
      const validExts = ['.pdf', '.docx'];
      const validMimes = [
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      ];
      if (!validExts.includes(ext) && !validMimes.some((m) => mime.includes(m))) {
        setValidationError(
          `Invalid document format for "${file.name}". Only PDF and DOCX documents are supported.`
        );
        return;
      }
    }

    // Revoke previous preview URL if present
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }

    const objectUrl = URL.createObjectURL(file);
    setSelectedFile(file);
    setPreviewUrl(objectUrl);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  // Preset Template loader for testing
  const loadPreset = (presetType: 'violations' | 'compliant') => {
    setSuccessMessage(null);
    setValidationError(null);
    setActiveModality('text');
    handleRemoveFile();

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

    const cleanTitle = title.trim();
    if (cleanTitle.length < 2) {
      setValidationError('Submission title must be at least 2 characters long.');
      return;
    }
    if (cleanTitle.length > 250) {
      setValidationError('Submission title cannot exceed 250 characters.');
      return;
    }

    // If text modality, content text is mandatory
    if (activeModality === 'text') {
      if (content.trim().length < 10) {
        setValidationError('Content text must be at least 10 characters long.');
        return;
      }
    } else {
      // For media modalities, a file must be selected
      if (!selectedFile) {
        setValidationError(
          `Please select or upload a valid ${activeModality} asset to proceed.`
        );
        return;
      }
    }

    try {
      setIsSubmitting(true);

      if (selectedFile && onSubmitUpload) {
        // Multipart media upload path
        const formData = new FormData();
        formData.append('title', cleanTitle);
        formData.append('target_channel', targetChannel);
        if (targetAudience.trim()) {
          formData.append('target_audience', targetAudience.trim());
        }
        formData.append('media_type', activeModality);
        if (content.trim()) {
          formData.append('content', content.trim());
        }
        formData.append('file', selectedFile);
        formData.append('submit_for_inspection', String(isSubmittingForInspection));

        await onSubmitUpload(
          formData,
          {
            title: cleanTitle,
            target_channel: targetChannel,
            target_audience: targetAudience.trim() || 'General Enterprise Audience',
            media_type: activeModality,
            content: content.trim() || undefined,
            author_name: currentUser?.full_name || 'Content Creator (Authenticated)',
          },
          isSubmittingForInspection
        );

        if (!isSubmittingForInspection) {
          setSuccessMessage(
            `${MODALITY_CONFIG[activeModality].label} draft successfully saved in the governance ledger.`
          );
        }
      } else {
        // Standard text submission path
        await onSubmitContent(
          {
            title: cleanTitle,
            content: content.trim() || `[${activeModality.toUpperCase()} Submission: ${selectedFile?.name || 'Asset'}]`,
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
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to submit content';
      setValidationError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto px-2 sm:px-4">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">
            Unified Multi-Input Submission Workspace
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Submit brand content across text, images, audio, video, or documents for automated governance analysis.
          </p>
        </div>

        {/* Quick Presets Menu */}
        <div className="flex items-center gap-2 self-start sm:self-center">
          <span className="text-xs text-slate-500 font-medium hidden sm:inline">Demo Presets:</span>
          <button
            type="button"
            onClick={() => loadPreset('violations')}
            className="min-h-[44px] sm:min-h-0 px-2.5 py-1.5 sm:py-1 text-xs font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 rounded-md border border-amber-200 transition"
            title="Load sample demonstration draft containing 4 intentional violations"
          >
            Sample with Violations
          </button>
          <button
            type="button"
            onClick={() => loadPreset('compliant')}
            className="min-h-[44px] sm:min-h-0 px-2.5 py-1.5 sm:py-1 text-xs font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 rounded-md border border-emerald-200 transition"
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
            className="text-blue-500 hover:text-blue-700 font-bold ml-2 p-1 min-h-[44px] sm:min-h-0"
          >
            ×
          </button>
        </div>
      )}

      {/* Main Drafting Form Card */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-subtle p-5 sm:p-6 space-y-5">
        {/* Modality Segmented Bar */}
        <div>
          <label className="block text-xs font-semibold text-slate-800 mb-2">
            Select Input Modality
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2" role="tablist">
            {(Object.keys(MODALITY_CONFIG) as InputMediaType[]).map((key) => {
              const config = MODALITY_CONFIG[key];
              const Icon = config.icon;
              const isSelected = activeModality === key;

              return (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={isSelected}
                  onClick={() => handleSelectModality(key)}
                  disabled={isSubmitting}
                  className={`min-h-[44px] flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border text-xs font-medium transition cursor-pointer ${
                    isSelected
                      ? 'bg-blue-50 border-blue-500 text-blue-700 font-semibold ring-2 ring-blue-500/10 shadow-xs'
                      : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50 hover:border-slate-300'
                  }`}
                >
                  <Icon className={`w-4 h-4 flex-shrink-0 ${isSelected ? 'text-blue-600' : 'text-slate-400'}`} />
                  <span className="truncate">{config.label}</span>
                </button>
              );
            })}
          </div>
          <p className="text-[11px] text-slate-500 mt-1.5">
            {MODALITY_CONFIG[activeModality].description}
          </p>
        </div>

        {validationError && (
          <div className="p-3.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-600" />
            <span className="break-words">{validationError}</span>
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
            placeholder="e.g. Q2 Product Announcement Campaign"
            className="w-full min-h-[44px] px-3.5 py-2.5 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 text-slate-900 placeholder-slate-400 font-medium"
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
              className="w-full min-h-[44px] px-3.5 py-2.5 text-xs rounded-lg border border-slate-200 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 font-medium"
            >
              <option value="twitter_x">Twitter / X Post</option>
              <option value="linkedin">LinkedIn Post</option>
              <option value="email_newsletter">Email Newsletter</option>
              <option value="blog_post">Blog Post / Article</option>
              <option value="advertisement">Paid Advertisement Copy</option>
              <option value="press_release">Official Press Release</option>
              <option value="ad_copy">Short Ad Copy</option>
              <option value="email">Direct Email</option>
              <option value="other">Other / Multi-Channel</option>
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
              className="w-full min-h-[44px] px-3.5 py-2.5 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 text-slate-900 placeholder-slate-400 font-medium"
            />
          </div>
        </div>

        {/* Multimodal Upload Zone (Shown for image, audio, video, document) */}
        {activeModality !== 'text' && (
          <div className="space-y-3">
            <label className="block text-xs font-semibold text-slate-800">
              {MODALITY_CONFIG[activeModality].label} File <span className="text-rose-500">*</span>
            </label>

            {/* Hidden native file inputs */}
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept={MODALITY_CONFIG[activeModality].acceptMimes}
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0) {
                  validateAndSetFile(e.target.files[0]);
                }
              }}
            />

            {/* Mobile camera capture input */}
            <input
              ref={cameraInputRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0) {
                  validateAndSetFile(e.target.files[0]);
                }
              }}
            />

            {!selectedFile ? (
              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`p-6 sm:p-8 rounded-xl border-2 border-dashed text-center transition flex flex-col items-center justify-center gap-3 ${
                  isDragging
                    ? 'border-blue-500 bg-blue-50/50'
                    : 'border-slate-300 hover:border-slate-400 bg-slate-50/60'
                }`}
              >
                <div className="w-12 h-12 rounded-full bg-blue-100/70 text-blue-600 flex items-center justify-center">
                  <UploadCloud className="w-6 h-6" />
                </div>

                <div>
                  <p className="text-xs font-semibold text-slate-800">
                    Drag and drop your {activeModality} asset here, or click to browse
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    Supported: {MODALITY_CONFIG[activeModality].acceptedFormats}
                  </p>
                </div>

                <div className="flex flex-wrap items-center justify-center gap-2.5 pt-1">
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isSubmitting}
                    className="min-h-[44px] px-4 py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition shadow-xs flex items-center gap-1.5"
                  >
                    <UploadCloud className="w-4 h-4" />
                    <span>Browse Files</span>
                  </button>

                  {activeModality === 'image' && (
                    <button
                      type="button"
                      onClick={() => cameraInputRef.current?.click()}
                      disabled={isSubmitting}
                      className="min-h-[44px] px-4 py-2 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 border border-slate-300 rounded-lg transition shadow-xs flex items-center gap-1.5"
                      title="Direct camera capture on mobile or webcam devices"
                    >
                      <Camera className="w-4 h-4 text-blue-600" />
                      <span>Capture with Camera</span>
                    </button>
                  )}
                </div>
              </div>
            ) : (
              /* Selected File Preview Card */
              <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/50 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="w-8 h-8 rounded-lg bg-blue-100 text-blue-700 flex items-center justify-center flex-shrink-0">
                      {React.createElement(MODALITY_CONFIG[activeModality].icon, { className: 'w-4 h-4' })}
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-slate-900 truncate">
                        {selectedFile.name}
                      </p>
                      <p className="text-[11px] text-slate-500">
                        {formatFileSize(selectedFile.size)} • {selectedFile.type || activeModality}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isSubmitting}
                      className="min-h-[44px] sm:min-h-0 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:text-slate-900 bg-white hover:bg-slate-100 rounded-md border border-slate-200 transition"
                    >
                      Replace
                    </button>
                    <button
                      type="button"
                      onClick={handleRemoveFile}
                      disabled={isSubmitting}
                      className="min-h-[44px] sm:min-h-0 p-2 text-rose-600 hover:text-rose-700 hover:bg-rose-50 rounded-md transition"
                      title="Remove file"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Media-specific visual preview */}
                {previewUrl && (
                  <div className="pt-2 border-t border-slate-200/70">
                    {activeModality === 'image' && (
                      <div className="max-h-72 overflow-hidden rounded-lg border border-slate-200 bg-black/5 flex items-center justify-center">
                        <img
                          src={previewUrl}
                          alt="Uploaded asset preview"
                          className="max-h-72 w-auto object-contain mx-auto"
                        />
                      </div>
                    )}

                    {activeModality === 'audio' && (
                      <div className="p-3 bg-white rounded-lg border border-slate-200">
                        <audio controls src={previewUrl} className="w-full">
                          Your browser does not support the audio element.
                        </audio>
                      </div>
                    )}

                    {activeModality === 'video' && (
                      <div className="rounded-lg overflow-hidden bg-black border border-slate-200">
                        <video controls src={previewUrl} className="w-full max-h-72">
                          Your browser does not support the video tag.
                        </video>
                      </div>
                    )}

                    {activeModality === 'document' && (
                      <div className="p-4 bg-white rounded-lg border border-slate-200 flex items-center gap-3">
                        <FileCheck className="w-8 h-8 text-blue-600 flex-shrink-0" />
                        <div>
                          <p className="text-xs font-semibold text-slate-800">
                            Document ready for brand guideline inspection
                          </p>
                          <p className="text-[11px] text-slate-500">
                            Structured paragraphs, headings, and statements will be parsed and evaluated against active policies.
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Content Textarea (Draft copy for text, or accompanying caption/notes for media) */}
        <div>
          <div className="flex justify-between items-center mb-1.5">
            <label className="block text-xs font-semibold text-slate-800">
              {activeModality === 'text' ? (
                <>
                  Draft Content for Verification <span className="text-rose-500">*</span>
                </>
              ) : (
                'Accompanying Copy, Caption, or Context (Optional)'
              )}
            </label>
            <div className="text-[11px] text-slate-400 flex items-center gap-3">
              <span>{wordCount} words</span>
              <span>•</span>
              <span
                className={
                  targetChannel === 'twitter_x' && charCount > 280
                    ? 'text-amber-600 font-bold'
                    : ''
                }
              >
                {charCount} characters {targetChannel === 'twitter_x' && '/ 280 max'}
              </span>
            </div>
          </div>
          <textarea
            rows={activeModality === 'text' ? 7 : 4}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            disabled={isSubmitting}
            placeholder={
              activeModality === 'text'
                ? 'Paste or compose your content draft here. The governance engine will scan against all active brand rules, legal directives, and tone standards...'
                : 'Optional: provide promotional copy, social caption, or descriptive notes to be audited alongside this media asset...'
            }
            className="w-full p-3.5 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 text-slate-900 placeholder-slate-400 leading-relaxed font-normal"
          />
        </div>

        {/* Action Controls & Governance Notice */}
        <div className="pt-4 border-t border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <HelpCircle className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
            <span>Connected to FastAPI backend with multipart transaction validation.</span>
          </div>

          <div className="flex items-center gap-2.5 flex-wrap sm:flex-nowrap">
            <button
              type="button"
              onClick={() => handleAction(false)}
              disabled={isSubmitting}
              className="min-h-[44px] px-4 py-2 rounded-lg border border-slate-200 text-slate-700 bg-white hover:bg-slate-50 text-xs font-semibold transition flex items-center gap-1.5 disabled:opacity-50"
            >
              {isSubmitting ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Save className="w-3.5 h-3.5 text-slate-500" />
              )}
              Save Draft
            </button>

            <button
              type="button"
              onClick={() => handleAction(true)}
              disabled={isSubmitting}
              className="min-h-[44px] px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold transition shadow-sm flex items-center gap-1.5 disabled:opacity-50"
            >
              {isSubmitting ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Send className="w-3.5 h-3.5" />
              )}
              Submit for Compliance Inspection
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
