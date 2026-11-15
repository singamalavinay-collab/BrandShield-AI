import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let parseCurrentRoute: () => { path: string; params: Record<string, string> };
let scrubUrlToken: () => void;

before(async () => {
  const routerModule = await import(pathToFileURL(path.resolve(__dirname, '../services/router.ts')).href);
  parseCurrentRoute = routerModule.parseCurrentRoute;
  scrubUrlToken = routerModule.scrubUrlToken;
});

describe('Phase 3.1 Public SaaS Landing & Native Hash Routing Invariants', () => {
  const landingPagePath = path.resolve(__dirname, '../pages/LandingPage.tsx');
  const landingHeaderPath = path.resolve(__dirname, '../components/layout/LandingHeader.tsx');
  const routerPath = path.resolve(__dirname, '../services/router.ts');
  const appPath = path.resolve(__dirname, '../App.tsx');

  const landingPageContent = fs.readFileSync(landingPagePath, 'utf-8');
  const landingHeaderContent = fs.readFileSync(landingHeaderPath, 'utf-8');
  const routerContent = fs.readFileSync(routerPath, 'utf-8');
  const appContent = fs.readFileSync(appPath, 'utf-8');

  test('Invariant 1: Public landing page displays headline, enterprise pillars, and CTAs', () => {
    assert.strictEqual(
      landingPageContent.includes('Deterministic Brand Compliance with'),
      true,
      'Landing page must feature core headline'
    );
    assert.strictEqual(
      landingPageContent.includes('AI proposes, but only authorized humans approve'),
      true,
      'Landing page must highlight the human-in-the-loop governance invariant'
    );
    assert.strictEqual(
      landingPageContent.includes('Create Organization Workspace'),
      true,
      'Landing page must provide primary CTA to create workspace'
    );
    assert.strictEqual(
      landingPageContent.includes('Sign In to Existing Tenant'),
      true,
      'Landing page must provide secondary CTA to sign in'
    );
    assert.strictEqual(
      landingPageContent.includes('Explore Interactive Demo'),
      true,
      'Landing page must provide sandbox demo action'
    );
    assert.strictEqual(
      landingPageContent.includes('The 4-Stage Governance Loop'),
      true,
      'Landing page must explain the 4-stage governance loop'
    );
  });

  test('Invariant 2: LandingHeader contains brand identity, API health badge, and action buttons', () => {
    assert.strictEqual(
      landingHeaderContent.includes('BrandShield AI'),
      true,
      'LandingHeader must display brand title'
    );
    assert.strictEqual(
      landingHeaderContent.includes('backendHealth.is_connected'),
      true,
      'LandingHeader must conditionally render live backend connection status'
    );
    assert.strictEqual(
      landingHeaderContent.includes('Interactive Demo'),
      true,
      'LandingHeader must feature an Interactive Demo entry button'
    );
    assert.strictEqual(
      landingHeaderContent.includes('Get Started'),
      true,
      'LandingHeader must feature a Get Started registration button'
    );
  });

  test('Invariant 3: Router enforces Security Rule 9 (scrubUrlToken without localStorage or logging)', () => {
    assert.strictEqual(
      routerContent.includes('window.history.replaceState'),
      true,
      'Router must use window.history.replaceState to scrub sensitive tokens'
    );
    assert.strictEqual(
      routerContent.includes('localStorage.setItem'),
      false,
      'Router must never persist raw invitation tokens into localStorage'
    );

    // Functional test with mocked window
    let replacedUrl = '';
    const mockWindow = {
      location: {
        href: 'https://brandshield.example.com/#/invite?token=test-invitation-token-12345',
        hash: '#/invite?token=test-invitation-token-12345',
        search: '',
        pathname: '/',
      },
      history: {
        replaceState: (_state: any, _title: string, url: string) => {
          replacedUrl = url;
        },
      },
      document: { title: 'BrandShield AI' },
    };

    (globalThis as any).window = mockWindow;
    (globalThis as any).document = mockWindow.document;

    // Test parseCurrentRoute
    const parsed = parseCurrentRoute();
    assert.strictEqual(parsed.path, 'invite');
    assert.strictEqual(parsed.params.token, 'test-invitation-token-12345');

    // Test scrubUrlToken
    scrubUrlToken();
    assert.strictEqual(
      replacedUrl.includes('test-invitation-token-12345'),
      false,
      'scrubUrlToken must eliminate invitation token from replaced URL'
    );
    assert.strictEqual(
      replacedUrl.includes('#/invite'),
      true,
      'scrubUrlToken must preserve path hash while stripping query params'
    );
  });

  test('Invariant 4: App.tsx conditionally protects workspace and exposes sandbox demo', () => {
    assert.strictEqual(
      appContent.includes('!currentUser && !isDemoMode'),
      true,
      'App.tsx must gate workspace behind authentication or explicit demo mode'
    );
    assert.strictEqual(
      appContent.includes('Interactive Demonstration Sandbox'),
      true,
      'App.tsx must render prominent demo banner when isDemoMode is active'
    );
    assert.strictEqual(
      appContent.includes('Exit Demo'),
      true,
      'App.tsx must provide an Exit Demo button to return to public landing view'
    );
  });
});
