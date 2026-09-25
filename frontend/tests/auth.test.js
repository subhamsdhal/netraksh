import { beforeEach, describe, expect, it, vi } from 'vitest';
import { authFetch, getRole, getToken, getUsername, login } from '../src/services/auth';

describe('authentication client', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it('stores the authenticated session and sends its bearer token', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ access_token: 'jwt-test', role: 'OPERATOR', username: 'operator' }),
    });
    await login('operator', 'not-recorded-by-test');
    expect(getToken()).toBe('jwt-test');
    expect(getRole()).toBe('OPERATOR');
    expect(getUsername()).toBe('operator');

    fetch.mockResolvedValueOnce({ ok: true, status: 200 });
    await authFetch('/health');
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer jwt-test');
  });

  it('clears a rejected session on a protected 401 response', async () => {
    localStorage.setItem('netraksh_token', 'expired');
    fetch.mockResolvedValueOnce({ ok: false, status: 401 });
    await authFetch('/events');
    expect(getToken()).toBeNull();
  });
});
