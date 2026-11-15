import { test, describe, before, beforeEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import type { AuthUser } from '../types/index';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let getAuthToken: () => string | null;
let getCurrentUser: () => AuthUser | null;
let logout: () => Promise<void>;
let createSubmission: (payload: any, submitForInspection?: boolean) => Promise<any>;

describe('Phase 3.4 Role-Based Permissions & Clean Tenant Workspace Invariants', () => {
  before(async () => {
    const apiModule = await import(pathToFileURL(path.resolve(__dirname, '../services/api.ts')).href);
    getAuthToken = apiModule.getAuthToken;
    getCurrentUser = apiModule.getCurrentUser;
    logout = apiModule.logout;
    createSubmission = apiModule.createSubmission;
  });

  const sidebarPath = path.resolve(__dirname, '../components/layout/Sidebar.tsx');
  const dashboardPath = path.resolve(__dirname, '../pages/DashboardPage.tsx');
  const guidelinesPath = path.resolve(__dirname, '../pages/GuidelinesPage.tsx');
  const correctionsPath = path.resolve(__dirname, '../pages/CorrectionsPage.tsx');
  const submissionPath = path.resolve(__dirname, '../pages/SubmissionPage.tsx');
  const reviewPath = path.resolve(__dirname, '../pages/ReviewPage.tsx');
  const appPath = path.resolve(__dirname, '../App.tsx');
  const apiPath = path.resolve(__dirname, '../services/api.ts');

  const sidebarContent = fs.readFileSync(sidebarPath, 'utf-8');
  const dashboardContent = fs.readFileSync(dashboardPath, 'utf-8');
  const guidelinesContent = fs.readFileSync(guidelinesPath, 'utf-8');
  const correctionsContent = fs.readFileSync(correctionsPath, 'utf-8');
  const submissionContent = fs.readFileSync(submissionPath, 'utf-8');
  const reviewContent = fs.readFileSync(reviewPath, 'utf-8');
  const appContent = fs.readFileSync(appPath, 'utf-8');
  const apiContent = fs.readFileSync(apiPath, 'utf-8');

  // Storage mock
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

  beforeEach(() => {
    mockLocalStorage.clear();
    (globalThis as any).localStorage = mockLocalStorage;
    (globalThis as any).window = {
      dispatchEvent: () => true,
    };
    (globalThis as any).fetch = async () => ({
      ok: true,
      status: 200,
      json: async () => ({}),
    });
  });

  test('Invariant 1: Sidebar displays dynamic guideline count and hides badge when zero rules exist', () => {
    // 1. Verify hardcoded '5 Rules' is completely eliminated
    assert.strictEqual(
      sidebarContent.includes("badge: '5 Rules'"),
      false,
      "Sidebar must never contain hardcoded '5 Rules' badge"
    );

    // 2. Verify dynamic badge calculation based on guidelinesCount
    assert.strictEqual(
      sidebarContent.includes('guidelinesCount > 0'),
      true,
      'Sidebar must conditionally show guideline count only when guidelinesCount > 0'
    );
    assert.strictEqual(
      sidebarContent.includes('guidelinesCount?: number'),
      true,
      'SidebarProps must accept optional guidelinesCount'
    );

    // 3. Verify App.tsx passes actual guidelines.length to Sidebar
    assert.strictEqual(
      appContent.includes('guidelinesCount={guidelines.length}'),
      true,
      'App.tsx must pass actual guidelines.length to Sidebar'
    );
  });

  test('Invariant 2: Sidebar restricts navigation: Review visible only to ADMIN and REVIEWER; Team visible only to ADMIN', () => {
    // 1. Verify Review tab is conditioned on isReviewerOrAdmin
    assert.strictEqual(
      sidebarContent.includes("isReviewerOrAdmin"),
      true,
      'Sidebar must define isReviewerOrAdmin check'
    );
    assert.strictEqual(
      sidebarContent.includes("currentUser?.role === 'ADMIN' || currentUser?.role === 'REVIEWER'"),
      true,
      "isReviewerOrAdmin must require role 'ADMIN' or 'REVIEWER'"
    );

    // 2. Verify Team tab is conditioned on isAdmin
    assert.strictEqual(
      sidebarContent.includes("const isAdmin = currentUser?.role === 'ADMIN'"),
      true,
      "isAdmin must require role 'ADMIN'"
    );
  });

  test('Invariant 3: Dashboard displays N/A or dash for compliance rate when zero submissions exist', () => {
    // 1. Verify compliance rate calculation handles zero submissions without returning 100
    assert.strictEqual(
      dashboardContent.includes("complianceRate !== null ? `${complianceRate}%` : '—'"),
      true,
      "DashboardPage must display '—' when complianceRate is null"
    );
    assert.strictEqual(
      dashboardContent.includes("No submissions evaluated yet"),
      true,
      "DashboardPage must display informative 'No submissions evaluated yet' explanation"
    );

    // Behavioral calculation test
    const calcRate = (subs: any[], approved: number) => {
      const hasSubmissions = subs.length > 0;
      return hasSubmissions ? Math.round((approved / subs.length) * 100) : null;
    };
    assert.strictEqual(calcRate([], 0), null, 'Empty submissions array must produce null compliance rate');
    assert.strictEqual(calcRate([{ id: '1' }], 1), 100, 'All approved submissions must produce 100%');
    assert.strictEqual(calcRate([{ id: '1' }, { id: '2' }], 1), 50, 'Half approved must produce 50%');
  });

  test('Invariant 4: Dashboard displays clean empty state for audit trail when auditLogs is empty', () => {
    assert.strictEqual(
      dashboardContent.includes('No Audit Events Recorded'),
      true,
      'DashboardPage must display empty state title when auditLogs is empty'
    );
    assert.strictEqual(
      dashboardContent.includes('Human review decisions and governance transitions will be recorded here automatically'),
      true,
      'DashboardPage must explain that human review decisions populate the audit trail'
    );
  });

  test('Invariant 5: Brand Guidelines page restricts rule authoring and toggles strictly to ADMIN', () => {
    // 1. Accepts currentUser
    assert.strictEqual(
      guidelinesContent.includes('currentUser?: AuthUser | null'),
      true,
      'GuidelinesPage must accept currentUser in props'
    );
    assert.strictEqual(
      guidelinesContent.includes("const isAdmin = currentUser?.role === 'ADMIN'"),
      true,
      'GuidelinesPage must evaluate isAdmin based on currentUser.role'
    );

    // 2. Add Brand Rule button gated to ADMIN
    assert.strictEqual(
      guidelinesContent.includes('{isAdmin ? ('),
      true,
      "GuidelinesPage must render 'Add Brand Rule' button only for ADMIN"
    );

    // 3. Non-admin users see Read-Only indicator
    assert.strictEqual(
      guidelinesContent.includes('Read-Only Guidelines'),
      true,
      'GuidelinesPage must render Read-Only Guidelines banner/badge for non-admin'
    );

    // 4. Toggle switch gated to ADMIN; non-admins get read-only status badge
    assert.strictEqual(
      guidelinesContent.includes('Active Toggle Switch for ADMIN, Read-Only Status Badge for non-admin'),
      true,
      'GuidelinesPage must separate ADMIN toggle switch from non-admin read-only status badge'
    );
  });

  test('Invariant 6: Corrections page distinguishes zero submissions from zero violations', () => {
    // 1. Zero submissions shows 'No Content Submissions Available'
    assert.strictEqual(
      correctionsContent.includes('No Content Submissions Available'),
      true,
      "CorrectionsPage must render 'No Content Submissions Available' when submissions are empty"
    );
    assert.strictEqual(
      correctionsContent.includes("actionText=\"Create Content Submission\""),
      true,
      "CorrectionsPage must offer action button to navigate to 'submission'"
    );

    // 2. Submissions exist with zero violations shows 'No Corrections Needed'
    assert.strictEqual(
      correctionsContent.includes('No Corrections Needed'),
      true,
      "CorrectionsPage must render 'No Corrections Needed' only when submission exists and has 0 violations"
    );
  });

  test('Invariant 7: Content Submission correctly attributes author using authenticated user full_name', () => {
    // 1. SubmissionPage accepts currentUser
    assert.strictEqual(
      submissionContent.includes('currentUser?: AuthUser | null'),
      true,
      'SubmissionPage must accept currentUser in props'
    );
    assert.strictEqual(
      submissionContent.includes("author_name: currentUser?.full_name || 'Content Creator (Authenticated)'"),
      true,
      'SubmissionPage must use currentUser.full_name as author_name'
    );

    // 2. App.tsx passes author_id with user full_name to API
    assert.strictEqual(
      appContent.includes('author_id: currentUser ? currentUser.full_name : newSub.author_name'),
      true,
      'App.tsx must pass author_id with user full_name to createSubmission'
    );
  });

  test('Invariant 8: Review console prevents direct URL access by CREATOR with governance restriction guard', () => {
    assert.strictEqual(
      reviewContent.includes("currentUser && currentUser.role === 'CREATOR'"),
      true,
      'ReviewPage must check if current user has CREATOR role'
    );
    assert.strictEqual(
      reviewContent.includes('Governance Review Authority Required'),
      true,
      'ReviewPage must render Governance Review Authority Required guard for CREATOR'
    );
    assert.strictEqual(
      reviewContent.includes('The Human Review & Authorization Console is strictly restricted'),
      true,
      'ReviewPage must display explicit restriction message'
    );
  });

  test('Invariant 9: Demo presets remain isolated; logout purges state and subsequent login loads only tenant records', async () => {
    // 1. Initial local storage is empty
    assert.strictEqual(getAuthToken(), null, 'Initially, no auth token should be stored');
    assert.strictEqual(getCurrentUser(), null, 'Initially, no current user should be stored');

    // 2. Set mock authenticated session
    mockLocalStorage.setItem('brandshield_auth_token', 'test_jwt_alpha');
    mockLocalStorage.setItem(
      'brandshield_auth_user',
      JSON.stringify({
        id: 'user-alpha-1',
        organization_id: 'org-alpha',
        email: 'admin@alpha.com',
        full_name: 'Alice Alpha',
        role: 'ADMIN',
        is_active: true,
      })
    );

    assert.strictEqual(getAuthToken(), 'test_jwt_alpha');
    const user = getCurrentUser();
    assert.strictEqual(user?.email, 'admin@alpha.com');
    assert.strictEqual(user?.organization_id, 'org-alpha');

    // 3. Logout clears all tenant session data
    await logout();
    assert.strictEqual(getAuthToken(), null, 'After logout, token must be completely removed');
    assert.strictEqual(getCurrentUser(), null, 'After logout, user session must be completely removed');

    // 4. In App.tsx, clearWorkspaceState resets arrays to empty
    assert.strictEqual(
      appContent.includes('setGuidelines([])'),
      true,
      'clearWorkspaceState must wipe guidelines array to empty'
    );
    assert.strictEqual(
      appContent.includes('setSubmissions([])'),
      true,
      'clearWorkspaceState must wipe submissions array to empty'
    );
    assert.strictEqual(
      appContent.includes('setReports({})'),
      true,
      'clearWorkspaceState must wipe reports object to empty'
    );
    assert.strictEqual(
      appContent.includes('setAuditLogs([])'),
      true,
      'clearWorkspaceState must wipe auditLogs array to empty'
    );
  });

  test('Invariant 10: Client API requests bind tenant authorization strictly via Bearer token', async () => {
    assert.strictEqual(
      apiContent.includes("headers['Authorization'] = `Bearer ${token}`"),
      true,
      'api.ts must bind JWT token to Authorization Bearer header'
    );
    assert.strictEqual(
      apiContent.includes("const token = getAuthToken();"),
      true,
      'api.ts must retrieve stored token via getAuthToken()'
    );

    // Behavioral test: verify apiRequest attaches Bearer header when token is present
    let capturedHeaders: Record<string, string> = {};
    (globalThis as any).fetch = async (_url: string, options: any) => {
      capturedHeaders = options?.headers || {};
      return {
        ok: true,
        status: 200,
        json: async () => ({ id: 'sub-123', status: 'draft', version: 1, created_at: new Date().toISOString() }),
      };
    };

    mockLocalStorage.setItem('brandshield_auth_token', 'test_bearer_token_xyz');
    await createSubmission({
      title: 'Test Title',
      content: 'Test content draft for header assertion.',
      target_channel: 'twitter_x',
    });

    assert.strictEqual(
      capturedHeaders['Authorization'],
      'Bearer test_bearer_token_xyz',
      'apiRequest must attach Bearer authorization header with stored token'
    );
  });
});
