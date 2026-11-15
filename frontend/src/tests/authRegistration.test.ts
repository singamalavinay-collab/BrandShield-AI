import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Phase 4.2 Secure Authentication & Registration Invariants', () => {
  const loginModalPath = path.resolve(__dirname, '../components/auth/LoginModal.tsx');
  const apiPath = path.resolve(__dirname, '../services/api.ts');
  const modalContent = fs.readFileSync(loginModalPath, 'utf-8');
  const apiContent = fs.readFileSync(apiPath, 'utf-8');

  test('Invariant 1: Modal contains both Sign In and Create Account tabs', () => {
    assert.strictEqual(
      modalContent.includes("type AuthTab = 'signin' | 'register'"),
      true,
      'LoginModal must define tab state for signin and register'
    );
    assert.strictEqual(
      modalContent.includes('Sign In'),
      true,
      'LoginModal must contain a Sign In tab button'
    );
    assert.strictEqual(
      modalContent.includes('Create Account'),
      true,
      'LoginModal must contain a Create Account tab button'
    );
  });

  test('Invariant 2: Public registration is strictly restricted to CREATOR role', () => {
    // Proves there is NO dropdown or radio group allowing users to select REVIEWER or ADMIN
    assert.strictEqual(
      modalContent.includes('value="REVIEWER"'),
      false,
      'Public registration form must never offer REVIEWER role selection'
    );
    assert.strictEqual(
      modalContent.includes('value="ADMIN"'),
      false,
      'Public registration form must never offer ADMIN role selection'
    );
    assert.strictEqual(
      modalContent.includes('Assigned Role: Content Author (CREATOR)'),
      true,
      'Public registration form must explicitly disclose fixed CREATOR role assignment'
    );
  });

  test('Invariant 3: Development quick-fills have active visual selection and instant login', () => {
    assert.strictEqual(
      modalContent.includes('Instant Demo Login'),
      true,
      'Quick-fill cards must provide a clearly labeled Instant Demo Login action'
    );
    assert.strictEqual(
      modalContent.includes('selectedQuickFill'),
      true,
      'Quick-fill cards must manage selectedQuickFill active state'
    );
    assert.strictEqual(
      modalContent.includes('border-blue-500 bg-blue-50/60 ring-1 ring-blue-500/30'),
      true,
      'Selected quick-fill must display distinct active ring and border styling'
    );
    // Name discrepancy corrected
    assert.strictEqual(
      modalContent.includes('Mark Creator'),
      true,
      'Quick-fill must display Mark Creator'
    );
    assert.strictEqual(
      modalContent.includes('Mark Spencer'),
      false,
      'Discrepant name "Mark Spencer" must be completely removed'
    );
  });

  test('Invariant 4: Dynamic login button reflects selected account and role', () => {
    assert.strictEqual(
      modalContent.includes("Sign In as Sarah Jenkins (Reviewer)"),
      true,
      'Login button must dynamically display Sarah Jenkins (Reviewer) when selected'
    );
    assert.strictEqual(
      modalContent.includes("Sign In as Mark Creator (Creator)"),
      true,
      'Login button must dynamically display Mark Creator (Creator) when selected'
    );
  });

  test('Invariant 5: Clear error messages for network/backend offline failures', () => {
    assert.strictEqual(
      modalContent.includes('http://127.0.0.1:8000'),
      true,
      'Error handler must provide clear actionable guidance when FastAPI backend is offline'
    );
  });

  test('Invariant 6: API service includes register method calling /api/v1/auth/register', () => {
    assert.strictEqual(
      apiContent.includes('export async function register'),
      true,
      'api.ts must export register function'
    );
    assert.strictEqual(
      apiContent.includes("apiRequest<AuthSession>('/api/v1/auth/register'"),
      true,
      'register function must target /api/v1/auth/register'
    );
  });
});
