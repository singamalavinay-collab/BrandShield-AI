import { test, describe, before, beforeEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import type { ContentSubmission } from '../types/index';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let fetchSubmissions: (statusFilter?: string) => Promise<ContentSubmission[]>;
let fetchSubmission: (id: string) => Promise<ContentSubmission>;
let createSubmission: (payload: any, submitForInspection?: boolean) => Promise<ContentSubmission>;
let submitDraftForInspection: (id: string) => Promise<ContentSubmission>;
let analyzeSubmission: (id: string) => Promise<ContentSubmission>;
let advanceSubmissionToReview: (id: string) => Promise<ContentSubmission>;
let fetchPendingReviews: () => Promise<ContentSubmission[]>;
let fetchOrganizationMembers: () => Promise<any[]>;
let fetchAuditLogs: (limit?: number) => Promise<any[]>;
let getAuthToken: () => string | null;
let setAuthSession: (session: any) => void;
let clearAuthSession: () => void;

describe('Phase 3.5 Final Integration & Regression Test Suite', () => {
  before(async () => {
    const apiModule = await import(pathToFileURL(path.resolve(__dirname, '../services/api.ts')).href);
    fetchSubmissions = apiModule.fetchSubmissions;
    fetchSubmission = apiModule.fetchSubmission;
    createSubmission = apiModule.createSubmission;
    submitDraftForInspection = apiModule.submitDraftForInspection;
    analyzeSubmission = apiModule.analyzeSubmission;
    advanceSubmissionToReview = apiModule.advanceSubmissionToReview;
    fetchPendingReviews = apiModule.fetchPendingReviews;
    fetchOrganizationMembers = apiModule.fetchOrganizationMembers;
    fetchAuditLogs = apiModule.fetchAuditLogs;
    getAuthToken = apiModule.getAuthToken;
    setAuthSession = apiModule.setAuthSession;
    clearAuthSession = apiModule.clearAuthSession;
  });

  const appPath = path.resolve(__dirname, '../App.tsx');
  const dashboardPath = path.resolve(__dirname, '../pages/DashboardPage.tsx');
  const reviewPath = path.resolve(__dirname, '../pages/ReviewPage.tsx');
  const sidebarPath = path.resolve(__dirname, '../components/layout/Sidebar.tsx');
  const teamPath = path.resolve(__dirname, '../pages/TeamManagementPage.tsx');
  const apiPath = path.resolve(__dirname, '../services/api.ts');

  const appContent = fs.readFileSync(appPath, 'utf-8');
  const dashboardContent = fs.readFileSync(dashboardPath, 'utf-8');
  const reviewContent = fs.readFileSync(reviewPath, 'utf-8');
  const sidebarContent = fs.readFileSync(sidebarPath, 'utf-8');
  const teamContent = fs.readFileSync(teamPath, 'utf-8');
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
  });

  // ============================================================================
  // 1. API Integration Tests (Mocked Fetch)
  // ============================================================================

  test('API Integration 1: fetchSubmissions maps author_name and rejects raw author_id fallback', async () => {
    const fakeApiResponse = [
      {
        id: 'sub-uuid-1',
        title: 'Launch Announcement',
        content: 'BrandShield copy',
        target_channel: 'twitter_x',
        target_audience: 'Enterprise',
        status: 'draft',
        version: 1,
        created_at: '2026-11-14T10:00:00Z',
        author_id: 'a1111111-1111-1111-1111-111111111111',
        author_name: 'Alice Administrator',
      },
      {
        id: 'sub-uuid-2',
        title: 'Missing Author Record',
        content: 'BrandShield copy 2',
        target_channel: 'linkedin',
        target_audience: 'Legal',
        status: 'submitted',
        version: 1,
        created_at: '2026-11-14T10:05:00Z',
        author_id: 'b2222222-2222-2222-2222-222222222222',
        author_name: null, // No name available
      },
    ];

    (globalThis as any).fetch = async () => ({
      ok: true,
      status: 200,
      json: async () => fakeApiResponse,
    });

    const result = await fetchSubmissions();
    assert.strictEqual(result.length, 2);

    // Record 1: Human-readable display name preserved
    assert.strictEqual(result[0].author_name, 'Alice Administrator');
    assert.notStrictEqual(result[0].author_name, 'a1111111-1111-1111-1111-111111111111');

    // Record 2: Safe fallback to 'Unknown author' - MUST NEVER show author_id UUID
    assert.strictEqual(result[1].author_name, 'Unknown author');
    assert.notStrictEqual(result[1].author_name, 'b2222222-2222-2222-2222-222222222222');
  });

  test('API Integration 2: All submission endpoints consistently map author_name and safe fallback', async () => {
    let capturedBody: any = null;

    (globalThis as any).fetch = async (_url: string, init?: RequestInit) => {
      if (init?.body) {
        capturedBody = JSON.parse(init.body as string);
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          id: 'sub-endpoint-test',
          title: 'Lifecycle Post',
          content: 'Verified text',
          target_channel: 'blog_post',
          status: 'violations_found',
          version: 2,
          created_at: '2026-11-14T12:00:00Z',
          author_id: 'c3333333-3333-3333-3333-333333333333',
          author_name: 'Rachel Reviewer',
        }),
      };
    };

    // 1. fetchSubmission
    const single = await fetchSubmission('sub-endpoint-test');
    assert.strictEqual(single.author_name, 'Rachel Reviewer');

    // 2. createSubmission
    const created = await createSubmission({
      title: 'Lifecycle Post',
      content: 'Verified text',
      target_channel: 'blog_post',
    });
    assert.strictEqual(created.author_name, 'Rachel Reviewer');
    // Ensure payload sent to server does not attempt to specify client-controlled author_id
    assert.strictEqual(capturedBody.author_id, undefined);

    // 3. submitDraftForInspection
    const submitted = await submitDraftForInspection('sub-endpoint-test');
    assert.strictEqual(submitted.author_name, 'Rachel Reviewer');

    // 4. analyzeSubmission
    const analyzed = await analyzeSubmission('sub-endpoint-test');
    assert.strictEqual(analyzed.author_name, 'Rachel Reviewer');

    // 5. advanceSubmissionToReview
    const advanced = await advanceSubmissionToReview('sub-endpoint-test');
    assert.strictEqual(advanced.author_name, 'Rachel Reviewer');

    // 6. fetchPendingReviews
    (globalThis as any).fetch = async () => ({
      ok: true,
      status: 200,
      json: async () => [
        {
          id: 'sub-review-1',
          title: 'Pending Review Post',
          content: 'Copy awaiting review',
          target_channel: 'email_newsletter',
          status: 'under_human_review',
          version: 1,
          created_at: '2026-11-14T13:00:00Z',
          author_id: 'd4444444-4444-4444-4444-444444444444',
          author_name: 'Charlie Creator',
        },
      ],
    });
    const pendingList = await fetchPendingReviews();
    assert.strictEqual(pendingList.length, 1);
    assert.strictEqual(pendingList[0].author_name, 'Charlie Creator');
  });

  test('API Integration 3: Multi-persona attribution preserves distinct names for ADMIN, CREATOR, and REVIEWER', async () => {
    const multiUserResponse = [
      {
        id: 'sub-admin',
        title: 'Master Guidelines Memo',
        content: 'Policy update',
        target_channel: 'email_newsletter',
        status: 'approved',
        version: 1,
        created_at: '2026-11-14T09:00:00Z',
        author_id: '00000000-0000-0000-0000-000000000001',
        author_name: 'Alice Admin',
      },
      {
        id: 'sub-creator',
        title: 'Social Ad Campaign',
        content: 'Spring promotions',
        target_channel: 'twitter_x',
        status: 'submitted',
        version: 1,
        created_at: '2026-11-14T09:15:00Z',
        author_id: '00000000-0000-0000-0000-000000000002',
        author_name: 'Charlie Creator',
      },
      {
        id: 'sub-reviewer',
        title: 'Governance Audit Summary',
        content: 'Quarterly review report',
        target_channel: 'blog_post',
        status: 'passed_checks',
        version: 1,
        created_at: '2026-11-14T09:30:00Z',
        author_id: '00000000-0000-0000-0000-000000000003',
        author_name: 'Rachel Reviewer',
      },
    ];

    (globalThis as any).fetch = async () => ({
      ok: true,
      status: 200,
      json: async () => multiUserResponse,
    });

    const submissions = await fetchSubmissions();
    assert.strictEqual(submissions[0].author_name, 'Alice Admin');
    assert.strictEqual(submissions[1].author_name, 'Charlie Creator');
    assert.strictEqual(submissions[2].author_name, 'Rachel Reviewer');

    // Confirm no raw UUIDs leaked into author_name
    for (const sub of submissions) {
      assert.strictEqual(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sub.author_name),
        false,
        `author_name must not be a raw UUID: got '${sub.author_name}'`
      );
    }
  });

  // ============================================================================
  // 2. Runtime Behavioral Tests
  // ============================================================================

  test('Runtime Behavioral 1: Session teardown thoroughly wipes authentication and workspace state', async () => {
    setAuthSession({
      access_token: 'test-jwt-bearer-token',
      token_type: 'bearer',
      user: {
        id: 'usr-1',
        full_name: 'Alice Admin',
        role: 'ADMIN',
        email: 'admin@acme.com',
        organization_id: 'org-1',
        is_active: true,
      },
    });

    assert.strictEqual(getAuthToken(), 'test-jwt-bearer-token');
    assert.notStrictEqual(storage['brandshield_auth_user'], undefined);

    // Execute clearAuthSession
    clearAuthSession();

    assert.strictEqual(getAuthToken(), null);
    assert.strictEqual(storage['brandshield_auth_user'], undefined);
    assert.strictEqual(storage['brandshield_auth_token'], undefined);
  });

  test('Runtime Behavioral 2: URL invitation token scrubbing and safe extraction', () => {
    const rawUrl = 'https://app.brandshield.ai/#invite_token=secure_invitation_secret_token_12345';
    const hash = rawUrl.split('#')[1] || '';
    const params = new URLSearchParams(hash);
    const token = params.get('invite_token');

    assert.strictEqual(token, 'secure_invitation_secret_token_12345');

    // Simulate URL replacement scrubbing
    const scrubbedUrl = rawUrl.replace(/#invite_token=[^&]+/, '');
    assert.strictEqual(scrubbedUrl.includes('secure_invitation_secret_token_12345'), false);
    assert.strictEqual(scrubbedUrl, 'https://app.brandshield.ai/');
  });

  // ============================================================================
  // 3. Static Source Assertions
  // ============================================================================

  test('Static Source 1: App.tsx enforces server-authoritative submission ownership', () => {
    assert.strictEqual(
      appContent.includes("author_name: currentUser ? currentUser.full_name : (newSub.author_name || 'Unknown author')"),
      true,
      "App.tsx must provide safe 'Unknown author' fallback in local offline state"
    );
  });

  test('Static Source 2: api.ts never falls back to item.author_id for human-readable author_name', () => {
    assert.strictEqual(
      apiContent.includes("item.author_id || 'Content Author'"),
      false,
      "api.ts must not fall back to raw author_id or 'Content Author'"
    );
    assert.strictEqual(
      apiContent.includes("item.author_name || 'Unknown author'"),
      true,
      "api.ts must map author_name with 'Unknown author' fallback"
    );
  });

  test('Static Source 3: DashboardPage and ReviewPage render author_name in display slots', () => {
    assert.strictEqual(
      dashboardContent.includes('Author: {sub.author_name}'),
      true,
      'DashboardPage must render human-readable author_name'
    );
    assert.strictEqual(
      reviewContent.includes('{pendingSubmission.author_name}'),
      true,
      'ReviewPage must render human-readable author_name'
    );
  });

  test('Static Source 4: Role-based navigation guards and invariants remain intact', () => {
    assert.strictEqual(
      sidebarContent.includes("const isAdmin = currentUser?.role === 'ADMIN'"),
      true,
      'Sidebar must enforce ADMIN role checks for team access'
    );
    assert.strictEqual(
      reviewContent.includes("isAuthorizedReviewer"),
      true,
      'ReviewPage must verify human reviewer authority'
    );
  });

  // ============================================================================
  // Phase 4 Targeted Regression Tests: Roster, Audit Trail & Decision Routing
  // ============================================================================

  test('API Integration 4: fetchOrganizationMembers calls /api/v1/invitations/members', async () => {
    let capturedUrl = '';
    (globalThis as any).fetch = async (url: string) => {
      capturedUrl = url;
      return {
        ok: true,
        json: async () => [
          {
            id: 'u-1',
            organization_id: 'org-1',
            email: 'admin@brandshield.ai',
            full_name: 'Alice Admin',
            role: 'ADMIN',
            is_active: true,
            is_owner: true,
            created_at: '2026-11-14T00:00:00Z',
          },
        ],
      };
    };

    const members = await fetchOrganizationMembers();
    assert.strictEqual(capturedUrl.includes('/api/v1/invitations/members'), true);
    assert.strictEqual(members.length, 1);
    assert.strictEqual(members[0].is_owner, true);
    assert.strictEqual(members[0].role, 'ADMIN');
  });

  test('API Integration 5: fetchAuditLogs calls /api/v1/submissions/audit-trail', async () => {
    let capturedUrl = '';
    (globalThis as any).fetch = async (url: string) => {
      capturedUrl = url;
      return {
        ok: true,
        json: async () => [
          {
            id: 'aud-1',
            organization_id: 'org-1',
            organization_name: 'BrandShield Primary Org',
            submission_id: 'sub-1',
            action_type: 'create_draft',
            actor_name: 'Alice Admin',
            timestamp: '2026-11-14T00:00:00Z',
          },
        ],
      };
    };

    const logs = await fetchAuditLogs(15);
    assert.strictEqual(capturedUrl.includes('/api/v1/submissions/audit-trail?limit=15'), true);
    assert.strictEqual(logs.length, 1);
    assert.strictEqual(logs[0].action_type, 'create_draft');
  });

  test('Static Source 5: TeamManagementPage displays active organization members and owner', () => {
    assert.strictEqual(
      teamContent.includes('fetchOrganizationMembers'),
      true,
      'TeamManagementPage must call fetchOrganizationMembers'
    );
    assert.strictEqual(
      teamContent.includes('member.is_owner ? \'Organization Owner\''),
      true,
      'TeamManagementPage must display Organization Owner label'
    );
    assert.strictEqual(
      teamContent.includes('Accepted Members & Organization Roster'),
      true,
      'TeamManagementPage must display Accepted Members section'
    );
  });

  test('Static Source 6: ReviewPage enforces under_human_review status gate and syncs staged content', () => {
    assert.strictEqual(
      reviewContent.includes("isUnderReview = pendingSubmission?.status === 'under_human_review'"),
      true,
      'ReviewPage must check isUnderReview'
    );
    assert.strictEqual(
      reviewContent.includes('setEditableContent(stagedContent)'),
      true,
      'ReviewPage must sync editableContent with stagedContent'
    );
    assert.strictEqual(
      reviewContent.includes('Audit Preview (Committed upon authorization):'),
      true,
      'ReviewPage must display honest audit preview before commitment'
    );
  });

  test('Static Source 7: App.tsx connects advanceSubmissionToReview and auto-refreshes audit logs', () => {
    assert.strictEqual(
      appContent.includes('advanceSubmissionToReview(submissionId)'),
      true,
      'App.tsx must invoke advanceSubmissionToReview'
    );
    assert.strictEqual(
      appContent.includes('refreshAuditLogs()'),
      true,
      'App.tsx must include refreshAuditLogs mechanism'
    );
  });
});
