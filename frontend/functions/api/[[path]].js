/**
 * Cloudflare Pages Function: API Reverse Proxy
 * 
 * Proxies /api/* calls to your deployed Python FastAPI backend
 * (e.g., on Render, Railway, Fly.io, or VPS).
 * 
 * Setup in Cloudflare Pages dashboard:
 * Settings -> Environment variables -> Add variable:
 * Variable name: BACKEND_URL
 * Value: https://your-backend-app.onrender.com
 */

export async function onRequest(context) {
  const { request, env } = context;
  const backendUrl = env.BACKEND_URL;

  if (!backendUrl) {
    return new Response(
      JSON.stringify({
        detail: "Cloudflare Pages: BACKEND_URL environment variable is not configured. Since Python FastAPI cannot run directly on Cloudflare Pages, please host the Python backend (e.g. on Render, Railway, Fly.io) and set BACKEND_URL in Cloudflare Pages Settings -> Environment variables, or configure Backend Server URL in the web app's Settings modal."
      }),
      {
        status: 502,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        }
      }
    );
  }

  const url = new URL(request.url);
  const cleanBackend = backendUrl.trim().replace(/\/+$/, "");
  const targetUrl = new URL(url.pathname + url.search, cleanBackend + "/");

  // Clone headers and update Host to target backend host
  const forwardHeaders = new Headers(request.headers);
  try {
    forwardHeaders.set("Host", new URL(cleanBackend).host);
  } catch (_) {}

  try {
    const response = await fetch(targetUrl.toString(), {
      method: request.method,
      headers: forwardHeaders,
      body: request.body,
      redirect: "follow"
    });
    return response;
  } catch (err) {
    return new Response(
      JSON.stringify({
        detail: `Cloudflare Pages proxy error connecting to backend at ${cleanBackend}: ${err.message}`
      }),
      {
        status: 502,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        }
      }
    );
  }
}
