import { useState, useEffect, useCallback } from 'react';
import { getToken, getRole, getUsername, AUTH_CHANGE_EVENT } from '../services/auth';

// Plain localStorage reads (getToken/getRole/getUsername) aren't reactive —
// a component that read them once at mount would never notice a login or
// logout that happened elsewhere (e.g. Evidence.jsx's LoginPrompt) without
// a full page reload. This subscribes to the real AUTH_CHANGE_EVENT
// login()/logout() now dispatch (services/auth.js), plus the browser's own
// `storage` event for cross-tab sync, so every mounted component reflects
// the real current session live.
export default function useAuth() {
  const [state, setState] = useState(() => ({
    token: getToken(),
    role: getRole(),
    username: getUsername(),
  }));

  const refresh = useCallback(() => {
    setState({ token: getToken(), role: getRole(), username: getUsername() });
  }, []);

  useEffect(() => {
    window.addEventListener(AUTH_CHANGE_EVENT, refresh);
    window.addEventListener('storage', refresh);
    return () => {
      window.removeEventListener(AUTH_CHANGE_EVENT, refresh);
      window.removeEventListener('storage', refresh);
    };
  }, [refresh]);

  return {
    isAuthenticated: !!state.token,
    role: state.role,
    username: state.username,
  };
}
