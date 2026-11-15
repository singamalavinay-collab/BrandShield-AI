/**
 * Lightweight native hash router and URL parameter utility.
 * Avoids heavy router dependencies while supporting bookmarkable views,
 * query parameters, and security-critical token scrubbing.
 */

export interface ParsedRoute {
  path: string;
  params: Record<string, string>;
}

export function parseCurrentRoute(): ParsedRoute {
  try {
    const hash = window.location.hash.replace(/^#\/?/, '') || '';
    const [pathPart, queryPart] = hash.split('?');
    const path = pathPart || '';
    const params: Record<string, string> = {};

    // 1. Parse hash query parameters (e.g. #/invite?token=xyz)
    if (queryPart) {
      const searchParams = new URLSearchParams(queryPart);
      searchParams.forEach((val, key) => {
        params[key] = val;
      });
    }

    // 2. Also inspect search query parameters from window.location.search (e.g. ?token=xyz)
    if (window.location.search) {
      const searchParams = new URLSearchParams(window.location.search);
      searchParams.forEach((val, key) => {
        if (!params[key]) {
          params[key] = val;
        }
      });
    }

    return { path, params };
  } catch {
    return { path: '', params: {} };
  }
}

/**
 * Security Rule 9: Protect invitation tokens.
 * Immediately scrubs sensitive tokens from the browser URL address bar
 * via window.history.replaceState to prevent token leakage into browser history,
 * bookmarks, or Referer headers.
 */
export function scrubUrlToken(): void {
  try {
    const url = new URL(window.location.href);
    let changed = false;

    if (url.searchParams.has('token')) {
      url.searchParams.delete('token');
      changed = true;
    }

    if (url.hash && url.hash.includes('token=')) {
      const [hashPath] = url.hash.split('?');
      url.hash = hashPath;
      changed = true;
    }

    if (changed) {
      window.history.replaceState({}, document.title, url.pathname + (url.search ? url.search : '') + (url.hash ? url.hash : ''));
    }
  } catch (err) {
    console.error('Failed to scrub URL token:', err);
  }
}

export function setHashRoute(path: string): void {
  try {
    window.location.hash = path.startsWith('/') ? path : `/${path}`;
  } catch {
    // Fallback for non-browser environments
  }
}
