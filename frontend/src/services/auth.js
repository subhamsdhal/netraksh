// NETRAKSH Frontend — minimal auth client.
//
// The backend has always had full JWT/RBAC infrastructure
// (backend/api/auth.py, POST /auth/token) but nothing in this frontend
// called it until GET /events/{id}/evidence-image was wired up requiring
// require_any_role. GET /events/{id} and POST /events/{id}/verify were
// later closed the same way as part of pre-deployment hardening (see
// docs/LIMITATIONS.md) — every fetch() against the backend in this
// frontend now goes through authFetch() below rather than a bare fetch(),
// kept intentionally minimal (login + token storage + an authenticated
// fetch helper), not a full auth system.

const TOKEN_KEY = 'netraksh_token';
const ROLE_KEY = 'netraksh_role';
const USERNAME_KEY = 'netraksh_username';
// Fired on every login()/logout() so any mounted component (Header, in
// particular) can react live without a full page reload. Plain
// localStorage reads are otherwise not reactive — the backend's real
// /auth/token response has always included `username` (backend/api/
// auth.py, TokenResponse.username), but nothing in this frontend stored
// or displayed it, or the real role RBAC already enforces server-side —
// there was no way to tell, from the UI, who was logged in or what they
// could do before that permission was actually attempted and rejected.
export const AUTH_CHANGE_EVENT = 'netraksh-auth-change';

// Derived from the page's own origin, not hardcoded to localhost. The
// backend serves this built frontend directly (single port, same origin —
// see backend/main.py's StaticFiles mount), so this resolves correctly
// whether the app is opened as http://localhost:8443 in dev or as a real
// https://<domain> once deployed, with no build-time config needed.
let backendUrl = import.meta.env.VITE_BACKEND_URL;
if (!backendUrl) {
  if (import.meta.env.PROD) {
    throw new Error("VITE_BACKEND_URL must be configured in production.");
  }
  // Native Windows launcher uses 8443; container builds always provide the
  // explicit backend URL (normally port 8000) through the Docker build arg.
  backendUrl = 'http://127.0.0.1:8443';
}
export const BACKEND_URL = backendUrl;

// Keep WebSocket authentication on the same backend as /auth/token.  A
// separately configured VITE_WS_URL remains supported for intentional
// split deployments, but the default now follows VITE_BACKEND_URL in both
// development and production.
const wsBaseUrl = import.meta.env.VITE_WS_URL ||
  BACKEND_URL.replace(/^http/, 'ws');
export const WS_URL = wsBaseUrl.endsWith('/ws/dashboard')
  ? wsBaseUrl
  : `${wsBaseUrl.replace(/\/$/, '')}/ws/dashboard`;

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRole() {
  return localStorage.getItem(ROLE_KEY);
}

export function getUsername() {
  return localStorage.getItem(USERNAME_KEY);
}

export function isAuthenticated() {
  return !!getToken();
}

// POST /auth/token expects OAuth2PasswordRequestForm — form-encoded, not JSON.
export async function login(username, password) {
  const body = new URLSearchParams();
  body.set('username', username);
  body.set('password', password);

  let res;
  try {
    res = await fetch(`${BACKEND_URL}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
  } catch (err) {
    throw new Error('Unable to reach the authentication server.');
  }

  if (!res.ok) {
    if (res.status === 401) {
      throw new Error('Invalid username or password.');
    }
    if (res.status === 403) {
      throw new Error('Your account is not authorized to access this system.');
    }
    if (res.status >= 500) {
      throw new Error('Authentication service error. Please try again.');
    }
    
    let detail = 'Login failed';
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch (_e) {
      // response wasn't JSON — keep the generic message
    }
    throw new Error(detail);
  }

  const data = await res.json();
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(ROLE_KEY, data.role);
  localStorage.setItem(USERNAME_KEY, data.username);
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
  return data;
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
  localStorage.removeItem(USERNAME_KEY);
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
}

// fetch() against the backend with the stored token attached, if any.
// Callers still need to check res.status themselves for 403 (wrong role),
// 404/409, etc. However, 401 (Unauthorized) is now caught globally:
// it triggers a logout to redirect the user to the central login page.
export async function authFetch(path, options = {}) {
  const token = getToken();
  const headers = { ...(options.headers || {}) };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const response = await fetch(`${BACKEND_URL}${path}`, { ...options, headers });
  
  if (response.status === 401) {
    // Token is missing, invalid, or expired.
    // Force a global logout which triggers the AUTH_CHANGE_EVENT.
    // The ProtectedRoute component will detect this and redirect to /login.
    logout();
  }
  
  return response;
}
