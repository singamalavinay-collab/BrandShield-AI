import { test, describe, before, beforeEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let uploadSubmission: (formData: any, submitForInspection?: boolean) => Promise<any>;
let setAuthSession: (session: any) => void;

describe('Phase 2, Stage 2D: Unified Multi-Input Workspace & Frontend Multimodal Integration', () => {
  // Storage mock for Node environment
  const storage: Record<string, string> = {};
  const mockLocalStorage = {
    getItem: (key: string) => storage[key] || null,
    setItem: (key: string, value: string) => {
      storage[key] = value;
    },
    removeItem: (key: string) => {
      delete storage[key];
    },
    clear: () => {
      Object.keys(storage).forEach((k) => delete storage[k]);
    },
  };

  before(() => {
    (globalThis as any).localStorage = mockLocalStorage;
    (globalThis as any).window = {
      dispatchEvent: () => true,
    };
  });

  beforeEach(() => {
    mockLocalStorage.clear();
  });
  before(async () => {
    const apiModule = await import(pathToFileURL(path.resolve(__dirname, '../services/api.ts')).href);
    uploadSubmission = apiModule.uploadSubmission;
    setAuthSession = apiModule.setAuthSession;
  });

  const submissionPagePath = path.resolve(__dirname, '../pages/SubmissionPage.tsx');
  const analysisPagePath = path.resolve(__dirname, '../pages/AnalysisResultsPage.tsx');
  const reviewPagePath = path.resolve(__dirname, '../pages/ReviewPage.tsx');
  const dashboardPagePath = path.resolve(__dirname, '../pages/DashboardPage.tsx');
  const mediaBadgePath = path.resolve(__dirname, '../components/common/MediaBadge.tsx');
  const apiPath = path.resolve(__dirname, '../services/api.ts');
  const appPath = path.resolve(__dirname, '../App.tsx');

  const submissionPageSrc = fs.readFileSync(submissionPagePath, 'utf-8');
  const analysisPageSrc = fs.readFileSync(analysisPagePath, 'utf-8');
  const reviewPageSrc = fs.readFileSync(reviewPagePath, 'utf-8');
  const dashboardPageSrc = fs.readFileSync(dashboardPagePath, 'utf-8');
  const mediaBadgeSrc = fs.readFileSync(mediaBadgePath, 'utf-8');
  const apiSrc = fs.readFileSync(apiPath, 'utf-8');
  const appSrc = fs.readFileSync(appPath, 'utf-8');

  // ============================================================================
  // 1. Modality Configuration & UI Invariants
  // ============================================================================

  test('Workspace Invariant 1: Workspace supports all 5 modalities (Text, Image, Audio, Video, Document)', () => {
    assert.strictEqual(
      submissionPageSrc.includes("text:") &&
      submissionPageSrc.includes("image:") &&
      submissionPageSrc.includes("audio:") &&
      submissionPageSrc.includes("video:") &&
      submissionPageSrc.includes("document:"),
      true,
      'SubmissionPage must configure all 5 input modalities in MODALITY_CONFIG'
    );

    assert.strictEqual(
      submissionPageSrc.includes('role="tablist"'),
      true,
      'SubmissionPage must render accessible tablist for modalities'
    );
  });

  test('Workspace Invariant 2: Mobile camera capture specifies capture="environment" and accept="image/*"', () => {
    assert.strictEqual(
      submissionPageSrc.includes('capture="environment"'),
      true,
      'SubmissionPage must support mobile rear camera capture with capture="environment"'
    );
    assert.strictEqual(
      submissionPageSrc.includes('accept="image/*"'),
      true,
      'Camera input must restrict capture to images (accept="image/*")'
    );
    assert.strictEqual(
      submissionPageSrc.includes('Capture with Camera'),
      true,
      'SubmissionPage must offer dedicated camera capture button'
    );
  });

  test('Workspace Invariant 3: Client-side 10MB ceiling guard and zero-byte protection', () => {
    assert.strictEqual(
      submissionPageSrc.includes('MAX_UPLOAD_SIZE = 10 * 1024 * 1024') ||
      submissionPageSrc.includes('10 * 1024 * 1024'),
      true,
      'SubmissionPage must enforce exact 10MB client check matching backend ceiling'
    );
    assert.strictEqual(
      submissionPageSrc.includes('0 bytes'),
      true,
      'SubmissionPage must validate non-zero byte files'
    );
  });

  test('Workspace Invariant 4: Object URL memory leak prevention via revokeObjectURL', () => {
    assert.strictEqual(
      submissionPageSrc.includes('URL.revokeObjectURL(previewUrl)'),
      true,
      'SubmissionPage must clean up Object URLs on component unmount and file replacement'
    );
    assert.strictEqual(
      submissionPageSrc.includes('handleRemoveFile'),
      true,
      'SubmissionPage must provide file removal capability before submission'
    );
  });

  test('Workspace Invariant 5: Anti-duplicate submission guard and touch targets >= 44px', () => {
    assert.strictEqual(
      submissionPageSrc.includes('disabled={isSubmitting}'),
      true,
      'Submission buttons and inputs must be disabled during active submission'
    );
    assert.strictEqual(
      submissionPageSrc.includes('min-h-[44px]'),
      true,
      'Submission workspace buttons and tabs must enforce mobile touch target min 44px'
    );
  });

  // ============================================================================
  // 2. Multipart API Integration & Header Handling
  // ============================================================================

  test('API Invariant 1: apiRequest leaves boundary generation to fetch when body is FormData', () => {
    assert.strictEqual(
      apiSrc.includes("options.body instanceof FormData") &&
      apiSrc.includes("delete headers['Content-Type']"),
      true,
      'apiRequest must omit manual Content-Type header when body is FormData to allow browser boundary calculation'
    );
  });

  test('API Invariant 2: uploadSubmission calls POST /api/v1/submissions/upload with Bearer token', async () => {
    let capturedUrl = '';
    let capturedOptions: any = null;

    setAuthSession({
      access_token: 'test-multimodal-jwt-token',
      token_type: 'bearer',
      user: {
        id: 'usr-creator-1',
        organization_id: 'org-test',
        email: 'creator@acme.com',
        full_name: 'Charlie Creator',
        role: 'CREATOR',
        is_active: true,
      },
    });

    (globalThis as any).fetch = async (url: string, options: any) => {
      capturedUrl = url;
      capturedOptions = options;
      return {
        ok: true,
        status: 201,
        json: async () => ({
          id: 'sub-upload-1234',
          title: 'Spring Campaign Poster',
          content: 'BrandShield AI — Verified Brand Safety',
          target_channel: 'linkedin',
          target_audience: 'Enterprise CMOs',
          status: 'submitted',
          version: 1,
          created_at: '2026-11-20T10:00:00Z',
          author_name: 'Charlie Creator',
          media_type: 'image',
          file_hash_sha256: 'a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef',
          mime_type: 'image/png',
          file_size_bytes: 2048576,
          multimodal_metadata: {
            processing_status: 'completed',
            analysis_engine: 'gemini_multimodal_vision',
            dimensions: [1200, 800],
          },
        }),
      };
    };

    const mockFormData = new FormData();
    mockFormData.append('title', 'Spring Campaign Poster');
    mockFormData.append('media_type', 'image');
    mockFormData.append('target_channel', 'linkedin');

    const result = await uploadSubmission(mockFormData, true);

    assert.strictEqual(capturedUrl.includes('/api/v1/submissions/upload'), true);
    assert.strictEqual(capturedOptions.method, 'POST');
    assert.strictEqual(capturedOptions.headers['Authorization'], 'Bearer test-multimodal-jwt-token');
    // Ensure manual Content-Type: application/json was NOT passed
    assert.strictEqual(capturedOptions.headers['Content-Type'], undefined);

    // Verify mapped attributes
    assert.strictEqual(result.id, 'sub-upload-1234');
    assert.strictEqual(result.media_type, 'image');
    assert.strictEqual(result.file_size_bytes, 2048576);
    assert.strictEqual(result.mime_type, 'image/png');
    assert.strictEqual(result.multimodal_metadata.analysis_engine, 'gemini_multimodal_vision');
    assert.strictEqual(result.author_name, 'Charlie Creator');
  });

  // ============================================================================
  // 3. Results Visualization & Honest Status Displays
  // ============================================================================

  test('Visualization Invariant 1: MediaBadge renders distinct labels and styles for all modalities', () => {
    assert.strictEqual(mediaBadgeSrc.includes("'image'"), true);
    assert.strictEqual(mediaBadgeSrc.includes("'audio'"), true);
    assert.strictEqual(mediaBadgeSrc.includes("'video'"), true);
    assert.strictEqual(mediaBadgeSrc.includes("'document'"), true);
    assert.strictEqual(mediaBadgeSrc.includes("'text'"), true);
  });

  test('Visualization Invariant 2: AnalysisResultsPage renders bounding box, video timestamp, and brand entity tags', () => {
    assert.strictEqual(
      analysisPageSrc.includes('violation.bounding_box'),
      true,
      'AnalysisResultsPage must render bounding box tag when coordinates are present'
    );
    assert.strictEqual(
      analysisPageSrc.includes('violation.timestamp_seconds'),
      true,
      'AnalysisResultsPage must render video timestamp tag when seconds are present'
    );
    assert.strictEqual(
      analysisPageSrc.includes('Brand Palette:'),
      true,
      'AnalysisResultsPage must render detected brand palette color swatches'
    );
  });

  test('Visualization Invariant 3: Transparent honest status handling for UNAVAILABLE, OCR_REQUIRED, and FAILED states', () => {
    assert.strictEqual(
      analysisPageSrc.includes("'UNAVAILABLE'"),
      true,
      'AnalysisResultsPage must display honest offline perception alert'
    );
    assert.strictEqual(
      analysisPageSrc.includes("'OCR_REQUIRED'"),
      true,
      'AnalysisResultsPage must display OCR recommendation notice'
    );
    assert.strictEqual(
      analysisPageSrc.includes("'FAILED'"),
      true,
      'AnalysisResultsPage must display extraction failure notice'
    );
  });

  test('Visualization Invariant 4: ReviewPage and DashboardPage display MediaBadge and multimodal metadata', () => {
    assert.strictEqual(
      reviewPageSrc.includes('<MediaBadge mediaType={pendingSubmission.media_type} />'),
      true,
      'ReviewPage must display MediaBadge in submission header'
    );
    assert.strictEqual(
      dashboardPageSrc.includes('<MediaBadge mediaType={sub.media_type} />'),
      true,
      'DashboardPage must display MediaBadge in recent submissions table'
    );
  });

  test('Visualization Invariant 5: App.tsx connects handleUploadSubmission to SubmissionPage', () => {
    assert.strictEqual(
      appSrc.includes('onSubmitUpload={handleUploadSubmission}'),
      true,
      'App.tsx must pass onSubmitUpload handler to SubmissionPage'
    );
    assert.strictEqual(
      appSrc.includes('uploadSubmission(formData, shouldInspect)'),
      true,
      'App.tsx handleUploadSubmission must invoke uploadSubmission service'
    );
  });
});
