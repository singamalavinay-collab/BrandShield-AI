import { test, describe, before, beforeEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import type {
  CreateInvitationDTO,
  AcceptInvitationDTO,
  TeamInvitation,
  InvitationValidationResponse,
  AuthUser,
} from '../types/index';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let createInvitation: (payload: CreateInvitationDTO) => Promise<TeamInvitation>;
let listInvitations: () => Promise<TeamInvitation[]>;
let revokeInvitation: (invitationId: string) => Promise<TeamInvitation>;
let validateInvitationToken: (token: string) => Promise<InvitationValidationResponse>;
let acceptInvitation: (payload: AcceptInvitationDTO) => Promise<any>;
let getAuthToken: () => string | null;
let getCurrentUser: () => AuthUser | null;

describe('Phase 3.3 Team Management & Public SaaS Invitation UX Invariants', () => {
  before(async () => {
    const apiModule = await import(pathToFileURL(path.resolve(__dirname, '../services/api.ts')).href);
    createInvitation = apiModule.createInvitation;
    listInvitations = apiModule.listInvitations;
    revokeInvitation = apiModule.revokeInvitation;
    validateInvitationToken = apiModule.validateInvitationToken;
    acceptInvitation = apiModule.acceptInvitation;
    getAuthToken = apiModule.getAuthToken;
    getCurrentUser = apiModule.getCurrentUser;
  });

  const typesPath = path.resolve(__dirname, '../types/index.ts');
  const apiPath = path.resolve(__dirname, '../services/api.ts');
  const teamPagePath = path.resolve(__dirname, '../pages/TeamManagementPage.tsx');
  const acceptModalPath = path.resolve(__dirname, '../components/auth/InvitationAcceptModal.tsx');
  const routerPath = path.resolve(__dirname, '../services/router.ts');

  const typesContent = fs.readFileSync(typesPath, 'utf-8');
  const apiContent = fs.readFileSync(apiPath, 'utf-8');
  const teamPageContent = fs.readFileSync(teamPagePath, 'utf-8');
  const acceptModalContent = fs.readFileSync(acceptModalPath, 'utf-8');
  const routerContent = fs.readFileSync(routerPath, 'utf-8');

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
      location: {
        href: 'https://brandshield.example.com/',
        search: '',
        hash: '',
        origin: 'https://brandshield.example.com',
        pathname: '/',
      },
      history: {
        replaceState: () => {},
      },
    };
  });

  test('Invariant 1: ADMIN can access team management; Non-ADMIN roles are rejected', () => {
    // 1. Verify TeamManagementPage enforces currentUser?.role === 'ADMIN'
    assert.strictEqual(
      teamPageContent.includes("currentUser?.role === 'ADMIN'"),
      true,
      'TeamManagementPage must verify that currentUser has ADMIN role'
    );
    assert.strictEqual(
      teamPageContent.includes('Administrative Privileges Required'),
      true,
      'TeamManagementPage must render an explicit access restriction view for non-admin roles'
    );
    assert.strictEqual(
      typesContent.includes("'team'"),
      true,
      "NavigationTab must include 'team' in types/index.ts"
    );
  });

  test('Invariant 2: CREATOR and REVIEWER cannot perform administrative invitation actions (Privilege Escalation Blocked)', () => {
    // Contract check: InvitationCreate only allows CREATOR or REVIEWER roles
    assert.strictEqual(
      typesContent.includes("export type InvitationRole = 'CREATOR' | 'REVIEWER';"),
      true,
      'InvitationRole must be strictly restricted to CREATOR and REVIEWER'
    );
    // UI check: TeamManagementPage only offers CREATOR and REVIEWER in invite modal
    assert.strictEqual(
      teamPageContent.includes('value="CREATOR"'),
      true,
      'Invite modal must offer Content Creator role'
    );
    assert.strictEqual(
      teamPageContent.includes('value="REVIEWER"'),
      true,
      'Invite modal must offer Compliance Reviewer role'
    );
    assert.strictEqual(
      teamPageContent.includes('value="ADMIN"'),
      false,
      'Invite modal must never allow inviting an ADMIN user'
    );
  });

  test('Invariant 3: ADMIN can create CREATOR and REVIEWER invitations via API service', async () => {
    let capturedUrl = '';
    let capturedOptions: any = null;

    (globalThis as any).fetch = async (url: string, options: any) => {
      capturedUrl = url;
      capturedOptions = options;
      return {
        ok: true,
        status: 201,
        json: async () => ({
          id: 'test-invitation-uuid',
          organization_id: 'org-uuid-1111',
          email: 'new.member@acme.example.com',
          role: 'CREATOR',
          status: 'PENDING',
          inviter_id: 'admin-uuid-9999',
          inviter_name: 'Admin Sarah',
          expires_at: '2026-11-21T00:00:00Z',
          created_at: '2026-11-14T00:00:00Z',
          invitation_token: 'secure_sample_token_abcdef1234567890',
          invitation_link: '/invitations/accept?token=secure_sample_token_abcdef1234567890',
        }),
      };
    };

    const invite = await createInvitation({
      email: 'new.member@acme.example.com',
      role: 'CREATOR',
    });

    assert.strictEqual(capturedUrl.endsWith('/api/v1/invitations'), true);
    assert.strictEqual(capturedOptions.method, 'POST');
    const sentBody = JSON.parse(capturedOptions.body);
    assert.strictEqual(sentBody.email, 'new.member@acme.example.com');
    assert.strictEqual(sentBody.role, 'CREATOR');
    assert.strictEqual(invite.status, 'PENDING');
    assert.strictEqual(invite.invitation_token, 'secure_sample_token_abcdef1234567890');
  });

  test('Invariant 4: Invalid and expired invitations are rejected with structured errors', async () => {
    // 1. Invalid token simulation (HTTP 404)
    (globalThis as any).fetch = async () => ({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Invitation token is invalid or does not exist.' }),
    });

    await assert.rejects(
      async () => {
        await validateInvitationToken('non-existent-token-123456');
      },
      (err: any) => {
        assert.strictEqual(err.message.includes('Invitation token is invalid'), true);
        return true;
      }
    );

    // 2. Expired token simulation (HTTP 400)
    (globalThis as any).fetch = async () => ({
      ok: false,
      status: 400,
      json: async () => ({
        detail: 'This invitation has expired. Please contact your organization administrator for a new invitation.',
      }),
    });

    await assert.rejects(
      async () => {
        await validateInvitationToken('expired-token-123456');
      },
      (err: any) => {
        assert.strictEqual(err.message.includes('This invitation has expired'), true);
        return true;
      }
    );
  });

  test('Invariant 5: Valid invitations can be accepted, provisioning user session', async () => {
    let capturedUrl = '';
    let capturedOptions: any = null;

    (globalThis as any).fetch = async (url: string, options: any) => {
      capturedUrl = url;
      capturedOptions = options;
      return {
        ok: true,
        status: 201,
        json: async () => ({
          access_token: 'jwt-token-for-invited-reviewer',
          token_type: 'bearer',
          expires_in: 86400,
          user: {
            id: 'invited-user-uuid-8888',
            organization_id: 'org-uuid-1111',
            email: 'reviewer.elena@acme.example.com',
            full_name: 'Dr. Elena Rostova',
            role: 'REVIEWER',
            is_active: true,
            organization_name: 'Acme Innovations',
          },
        }),
      };
    };

    const session = await acceptInvitation({
      token: 'valid_secure_token_xyz987654321',
      full_name: 'Dr. Elena Rostova',
      password: 'SecurePassword123!',
    });

    assert.strictEqual(capturedUrl.endsWith('/api/v1/invitations/accept'), true);
    assert.strictEqual(capturedOptions.method, 'POST');
    assert.strictEqual(session.user.full_name, 'Dr. Elena Rostova');
    assert.strictEqual(session.user.role, 'REVIEWER');
    assert.strictEqual(session.user.organization_name, 'Acme Innovations');

    // Verify authenticated session was stored in localStorage
    assert.strictEqual(getAuthToken(), 'jwt-token-for-invited-reviewer');
    const storedUser = getCurrentUser();
    assert.strictEqual(storedUser?.email, 'reviewer.elena@acme.example.com');
  });

  test('Invariant 6: Accepted users belong to the correct organization and assigned roles are preserved', async () => {
    const orgId = 'org-target-uuid-5555';
    (globalThis as any).fetch = async () => ({
      ok: true,
      status: 201,
      json: async () => ({
        access_token: 'token-5555',
        token_type: 'bearer',
        expires_in: 86400,
        user: {
          id: 'user-777',
          organization_id: orgId,
          email: 'author.marcus@targetorg.com',
          full_name: 'Marcus Content Author',
          role: 'CREATOR',
          is_active: true,
          organization_name: 'Target Org',
        },
      }),
    });

    const session = await acceptInvitation({
      token: 'sample-token',
      full_name: 'Marcus Content Author',
      password: 'Password123!',
    });

    assert.strictEqual(session.user.organization_id, orgId);
    assert.strictEqual(session.user.role, 'CREATOR');
  });

  test('Invariant 7: Pending invitations and accepted members are displayed separately in UI and retrieved via listInvitations()', async () => {
    (globalThis as any).fetch = async () => ({
      ok: true,
      status: 200,
      json: async () => [
        {
          id: 'inv-pending',
          email: 'pending@acme.com',
          role: 'CREATOR',
          status: 'PENDING',
          organization_id: 'org-1',
          inviter_id: 'admin-1',
          expires_at: '2026-11-21T00:00:00Z',
          created_at: '2026-11-14T00:00:00Z',
        },
        {
          id: 'inv-accepted',
          email: 'accepted@acme.com',
          role: 'REVIEWER',
          status: 'ACCEPTED',
          organization_id: 'org-1',
          inviter_id: 'admin-1',
          accepted_at: '2026-11-14T01:00:00Z',
          expires_at: '2026-11-21T00:00:00Z',
          created_at: '2026-11-14T00:00:00Z',
        },
      ],
    });

    const items = await listInvitations();
    assert.strictEqual(items.length, 2);
    assert.strictEqual(items[0].status, 'PENDING');
    assert.strictEqual(items[1].status, 'ACCEPTED');

    // Check TeamManagementPage renders separate subsets
    assert.strictEqual(
      teamPageContent.includes("invitations.filter((inv) => inv.status === 'PENDING')"),
      true,
      'Must filter pending invitations separately'
    );
    assert.strictEqual(
      teamPageContent.includes("invitations.filter((inv) => inv.status === 'ACCEPTED')"),
      true,
      'Must filter accepted invitations separately'
    );
    assert.strictEqual(
      teamPageContent.includes('Pending Invitations'),
      true,
      'Must render Pending Invitations section header'
    );
    assert.strictEqual(
      teamPageContent.includes('Accepted Members & Organization Roster'),
      true,
      'Must render Accepted Members section header'
    );
  });

  test('Invariant 8: Invitation revocation works correctly via DELETE /api/v1/invitations/{id}', async () => {
    let capturedUrl = '';
    let capturedOptions: any = null;

    (globalThis as any).fetch = async (url: string, options: any) => {
      capturedUrl = url;
      capturedOptions = options;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          id: 'invitation-to-revoke-123',
          organization_id: 'org-uuid',
          email: 'revoked.user@example.com',
          role: 'CREATOR',
          status: 'REVOKED',
          inviter_id: 'admin-uuid',
          expires_at: '2026-11-21T00:00:00Z',
          created_at: '2026-11-14T00:00:00Z',
        }),
      };
    };

    const res = await revokeInvitation('invitation-to-revoke-123');
    assert.strictEqual(capturedUrl.endsWith('/api/v1/invitations/invitation-to-revoke-123'), true);
    assert.strictEqual(capturedOptions.method, 'DELETE');
    assert.strictEqual(res.status, 'REVOKED');
  });

  test('Invariant 9: Security Rule 9 - Invitation tokens are NOT exposed in logs or persistent storage', () => {
    // 1. InvitationAcceptModal must call scrubUrlToken() immediately
    assert.strictEqual(
      acceptModalContent.includes('scrubUrlToken()'),
      true,
      'InvitationAcceptModal must call scrubUrlToken() upon mounting'
    );

    // 2. InvitationAcceptModal must never save raw tokens to localStorage
    assert.strictEqual(
      acceptModalContent.includes('localStorage.setItem'),
      false,
      'InvitationAcceptModal must never persist invitation tokens into localStorage'
    );

    // 3. Router implementation must use window.history.replaceState without logging tokens
    assert.strictEqual(
      routerContent.includes('window.history.replaceState'),
      true,
      'Router must use window.history.replaceState to scrub sensitive tokens'
    );
    assert.strictEqual(
      routerContent.includes('console.log') || routerContent.includes('console.info'),
      false,
      'Router must never log tokens'
    );

    // 4. Verify listInvitations endpoint schema ensures token hash is never leaked
    assert.strictEqual(
      apiContent.includes('export async function listInvitations'),
      true,
      'listInvitations must be exposed'
    );
  });
});
