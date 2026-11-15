import { test, describe, before, beforeEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import type { OnboardCredentials, ContentSubmission } from '../types/index';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let onboardWorkspace: (credentials: OnboardCredentials) => Promise<any>;
let logout: () => Promise<void>;
let getAuthToken: () => string | null;
let getCurrentUser: () => any;

describe('Phase 3.2 Multi-Tenant Onboarding & Data Isolation Invariants', () => {
  before(async () => {
    const apiModule = await import(pathToFileURL(path.resolve(__dirname, '../services/api.ts')).href);
    onboardWorkspace = apiModule.onboardWorkspace;
    logout = apiModule.logout;
    getAuthToken = apiModule.getAuthToken;
    getCurrentUser = apiModule.getCurrentUser;
  });
  const typesPath = path.resolve(__dirname, '../types/index.ts');
  const apiPath = path.resolve(__dirname, '../services/api.ts');
  const loginModalPath = path.resolve(__dirname, '../components/auth/LoginModal.tsx');
  const navbarPath = path.resolve(__dirname, '../components/layout/Navbar.tsx');
  const dashboardPath = path.resolve(__dirname, '../pages/DashboardPage.tsx');
  const reviewPath = path.resolve(__dirname, '../pages/ReviewPage.tsx');
  const appPath = path.resolve(__dirname, '../App.tsx');

  const typesContent = fs.readFileSync(typesPath, 'utf-8');
  const apiContent = fs.readFileSync(apiPath, 'utf-8');
  const loginModalContent = fs.readFileSync(loginModalPath, 'utf-8');
  const navbarContent = fs.readFileSync(navbarPath, 'utf-8');
  const dashboardContent = fs.readFileSync(dashboardPath, 'utf-8');
  const reviewContent = fs.readFileSync(reviewPath, 'utf-8');
  const appContent = fs.readFileSync(appPath, 'utf-8');

  // Storage mock for behavioral tests
  const storage: Record<string, string> = {};
  const mockLocalStorage = {
    getItem: (key: string) => storage[key] || null,
    setItem: (key: string, value: string) => { storage[key] = value; },
    removeItem: (key: string) => { delete storage[key]; },
    clear: () => { Object.keys(storage).forEach((k) => delete storage[k]); },
  };

  beforeEach(() => {
    mockLocalStorage.clear();
    (globalThis as any).localStorage = mockLocalStorage;
    (globalThis as any).window = {
      dispatchEvent: () => true,
    };
  });

  test('Invariant 1: Behavioral test - onboardWorkspace() calls POST /api/v1/auth/onboard and sets session', async () => {
    let capturedUrl = '';
    let capturedOptions: any = null;

    (globalThis as any).fetch = async (url: string, options: any) => {
      capturedUrl = url;
      capturedOptions = options;
      return {
        ok: true,
        status: 201,
        json: async () => ({
          access_token: 'jwt-test-token-onboard-12345',
          token_type: 'bearer',
          expires_in: 86400,
          user: {
            id: 'uuid-admin-1',
            organization_id: 'uuid-org-1',
            email: 'admin@starlight.io',
            full_name: 'Dr. Sarah Starlight',
            role: 'ADMIN',
            is_active: true,
            organization_name: 'Starlight Media',
          },
        }),
      };
    };

    const payload: OnboardCredentials = {
      organization_name: 'Starlight Media',
      full_name: 'Dr. Sarah Starlight',
      email: 'admin@starlight.io',
      password: 'SecurePassword123!',
    };

    const session = await onboardWorkspace(payload);

    assert.strictEqual(capturedUrl.endsWith('/api/v1/auth/onboard'), true);
    assert.strictEqual(capturedOptions.method, 'POST');
    const sentBody = JSON.parse(capturedOptions.body);
    assert.strictEqual(sentBody.organization_name, 'Starlight Media');
    assert.strictEqual(sentBody.full_name, 'Dr. Sarah Starlight');
    assert.strictEqual(sentBody.email, 'admin@starlight.io');
    assert.strictEqual(sentBody.password, 'SecurePassword123!');

    assert.strictEqual(session.user.role, 'ADMIN');
    assert.strictEqual(session.user.organization_name, 'Starlight Media');
    assert.strictEqual(getAuthToken(), 'jwt-test-token-onboard-12345');
    assert.strictEqual(getCurrentUser()?.organization_name, 'Starlight Media');
    assert.strictEqual(apiContent.includes('export async function onboardWorkspace'), true);
  });

  test('Invariant 2: Behavioral test - onboardWorkspace() maps duplicate email errors cleanly', async () => {
    (globalThis as any).fetch = async () => ({
      ok: false,
      status: 400,
      json: async () => ({
        detail: "An account with email 'existing@company.com' already exists.",
      }),
    });

    await assert.rejects(
      async () => {
        await onboardWorkspace({
          organization_name: 'Acme Corp',
          full_name: 'John Doe',
          email: 'existing@company.com',
          password: 'Password123!',
        });
      },
      (err: Error) => {
        assert.strictEqual(
          err.message.includes("An account with email 'existing@company.com' already exists."),
          true
        );
        return true;
      }
    );
  });

  test('Invariant 3: Behavioral test - logout() clears local credentials even on network failure', async () => {
    mockLocalStorage.setItem('brandshield_auth_token', 'sample-token');
    mockLocalStorage.setItem('brandshield_auth_user', JSON.stringify({ email: 'test@example.com' }));

    (globalThis as any).fetch = async () => {
      throw new Error('Network offline or backend unreachable');
    };

    await logout();

    assert.strictEqual(getAuthToken(), null, 'Local auth token must be cleared even if network fails');
    assert.strictEqual(getCurrentUser(), null, 'Local auth user profile must be cleared even if network fails');
  });

  test('Invariant 4: Dynamic Organization Identity - Eliminates hardcoded BrandShield Primary Org', () => {
    assert.strictEqual(
      navbarContent.includes("'BrandShield Primary Org'"),
      false,
      'Navbar must not hardcode BrandShield Primary Org'
    );
    assert.strictEqual(
      navbarContent.includes('currentUser?.organization_name'),
      true,
      'Navbar must dynamically render currentUser?.organization_name'
    );
    assert.strictEqual(
      typesContent.includes('organization_name?: string'),
      true,
      'AuthUser interface must include organization_name'
    );
  });

  test('Invariant 5: Profile Popover & Sign Out UI Integration', () => {
    assert.strictEqual(
      navbarContent.includes('isProfileOpen'),
      true,
      'Navbar must maintain profile popover open state'
    );
    assert.strictEqual(
      navbarContent.includes('Sign Out of Workspace'),
      true,
      'Navbar profile popover must include Sign Out of Workspace action'
    );
    assert.strictEqual(
      navbarContent.includes('Role: {currentUser.role}'),
      true,
      'Navbar profile popover must display user role'
    );
  });

  test('Invariant 6: Registration UI - Collects organization_name and supports initialTab=register', () => {
    assert.strictEqual(
      loginModalContent.includes('initialTab = \'signin\''),
      true,
      'LoginModal must accept initialTab prop'
    );
    assert.strictEqual(
      loginModalContent.includes('regOrgName'),
      true,
      'LoginModal must maintain state for organization / workspace name'
    );
    assert.strictEqual(
      loginModalContent.includes('onboardWorkspace'),
      true,
      'LoginModal registration flow must call onboardWorkspace'
    );
    assert.strictEqual(
      loginModalContent.includes('Organization / Brand Workspace Name'),
      true,
      'LoginModal must render an input label for organization name'
    );
    assert.strictEqual(
      loginModalContent.includes('Initial Workspace Administrator (ADMIN)'),
      true,
      'LoginModal must disclose initial ADMIN role provisioning'
    );
  });

  test('Invariant 7: Data Isolation & Empty Workspace Handling - DashboardPage & ReviewPage', () => {
    // 1. DashboardPage does NOT return isAllDemo = true when submissions is empty
    const checkEmptyIsAllDemo = (subs: ContentSubmission[]) => subs.length > 0 && subs.every((s) => s.is_demo);
    assert.strictEqual(checkEmptyIsAllDemo([]), false, 'Empty submissions array must not evaluate to isAllDemo: true');

    assert.strictEqual(
      dashboardContent.includes('submissions.length > 0 && submissions.every((s) => s.is_demo)'),
      true,
      'DashboardPage must guard isAllDemo with submissions.length > 0'
    );
    assert.strictEqual(
      dashboardContent.includes('No Content Submissions Yet'),
      true,
      'DashboardPage must render empty state when submissions are empty'
    );

    // 2. ReviewPage guards against undefined pendingSubmission
    assert.strictEqual(
      reviewContent.includes('if (!pendingSubmission)'),
      true,
      'ReviewPage must guard against undefined pendingSubmission in clean workspaces'
    );
    assert.strictEqual(
      reviewContent.includes('Review Queue is Empty'),
      true,
      'ReviewPage must display empty state when no submissions are pending review'
    );
  });

  test('Invariant 8: Unauthenticated API request suppression & strict state decoupling in App.tsx', () => {
    // 1. Protected calls are gated behind currentUser
    assert.strictEqual(
      appContent.includes('if (diag.database.connected && currentUser)'),
      true,
      'App.tsx must gate fetchGuidelines and fetchSubmissions behind currentUser'
    );

    // 2. Zero mock items merged into live submissions
    assert.strictEqual(
      appContent.includes('remaining.filter'),
      false,
      'App.tsx must not merge fallback remaining items into live submissions'
    );

    // 3. Clear workspace state utility exists
    assert.strictEqual(
      appContent.includes('clearWorkspaceState'),
      true,
      'App.tsx must define clearWorkspaceState to wipe memory on logout and session switches'
    );
  });
});
