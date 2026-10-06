/**
 * SlideCraft - API Configuration & Network Helpers
 * Manages API endpoint resolution for local and Cloudflare Pages / external hosting.
 */

(function () {
  const API_STORAGE_KEY = 'slidecraft_api_url';

  /**
   * Returns configured base URL for the backend API.
   * If not set, returns empty string (meaning same-origin relative requests).
   */
  function getApiBaseUrl() {
    const stored = localStorage.getItem(API_STORAGE_KEY);
    if (stored && stored.trim()) {
      return stored.trim().replace(/\/+$/, '');
    }
    return '';
  }

  /**
   * Saves or clears custom backend API base URL.
   */
  function setApiBaseUrl(url) {
    if (url && url.trim()) {
      localStorage.setItem(API_STORAGE_KEY, url.trim().replace(/\/+$/, ''));
    } else {
      localStorage.removeItem(API_STORAGE_KEY);
    }
  }

  /**
   * Resolves a relative API endpoint into a full URL if a custom base URL is configured.
   * @param {string} endpoint - e.g. '/api/convert' or 'api/convert'
   * @returns {string} - e.g. 'https://my-backend.onrender.com/api/convert' or '/api/convert'
   */
  function getApiUrl(endpoint) {
    if (!endpoint) return '';
    // If it's already an absolute HTTP/HTTPS URL, return as-is
    if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) {
      return endpoint;
    }
    const cleanPath = endpoint.startsWith('/') ? endpoint : '/' + endpoint;
    const base = getApiBaseUrl();
    return base ? `${base}${cleanPath}` : cleanPath;
  }

  /**
   * Checks whether the current frontend is running on a static hosting provider
   * (like Cloudflare Pages, Vercel, Netlify, GitHub Pages) without a configured backend.
   */
  function isStaticHosted() {
    const host = window.location.hostname;
    return (
      host.endsWith('.pages.dev') ||
      host.endsWith('.vercel.app') ||
      host.endsWith('.netlify.app') ||
      host.endsWith('.github.io')
    );
  }

  /**
   * Safe fetch with unified error handling and single-read stream safety.
   * Prevents "Failed to execute 'text' on 'Response': body stream already read"
   * and "Unexpected end of JSON input" errors.
   */
  async function safeFetch(url, options = {}) {
    const targetUrl = getApiUrl(url);
    let response;
    try {
      response = await fetch(targetUrl, options);
    } catch (networkErr) {
      const hint = (isStaticHosted() && !getApiBaseUrl())
        ? ' On Cloudflare Pages, you must deploy your Python backend and set its URL in Settings.'
        : ' Please ensure the backend server is running.';
      throw new Error(`Failed to connect to backend (${networkErr.message}).${hint}`);
    }

    // Read the body as text ONCE so the stream cannot be locked or double-read
    const text = await response.text();
    let data = null;
    let isJson = false;

    if (text) {
      try {
        data = JSON.parse(text);
        isJson = true;
      } catch (_) {
        isJson = false;
      }
    }

    if (!response.ok) {
      let message;
      if (isJson && data) {
        message = data.detail || data.message || `Server error (${response.status})`;
      } else if (response.status === 404) {
        message = (isStaticHosted() && !getApiBaseUrl())
          ? `Backend not found (404). Frontend is hosted on Cloudflare Pages, but Python backend is not configured. Click Settings (⚙️) to enter your Backend Server URL.`
          : `API endpoint not found (404) at ${targetUrl}. Ensure the Python FastAPI server is running.`;
      } else {
        message = text && text.length < 200 ? text : `Server error (${response.status}: ${response.statusText || 'Unknown'})`;
      }
      const err = new Error(message);
      err.status = response.status;
      err.data = data;
      throw err;
    }

    return { response, data, text, isJson };
  }

  // Expose to window
  window.getApiBaseUrl = getApiBaseUrl;
  window.setApiBaseUrl = setApiBaseUrl;
  window.getApiUrl = getApiUrl;
  window.isStaticHosted = isStaticHosted;
  window.safeFetch = safeFetch;
})();
