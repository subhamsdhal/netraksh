import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTH_CHANGE_EVENT, authFetch, authUpload, getRole, getToken, getUsername, login, logout } from '../src/services/auth';

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

  it('clears all stored session fields and broadcasts the auth change on logout', () => {
    localStorage.setItem('netraksh_token', 'session-token');
    localStorage.setItem('netraksh_role', 'ADMIN');
    localStorage.setItem('netraksh_username', 'admin');
    const onAuthChange = vi.fn();
    window.addEventListener(AUTH_CHANGE_EVENT, onAuthChange);

    logout();

    expect(getToken()).toBeNull();
    expect(getRole()).toBeNull();
    expect(getUsername()).toBeNull();
    expect(onAuthChange).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_CHANGE_EVENT, onAuthChange);
  });

  it('reports real upload bytes and preserves authenticated transport', async () => {
    localStorage.setItem('netraksh_token', 'upload-token');
    const progress = [];
    class FakeUploadRequest {
      constructor() {
        this.upload = {};
        this.status = 200;
        this.responseText = '{"source_state":"READY"}';
        FakeUploadRequest.instance = this;
      }
      open(method, url) { this.method = method; this.url = url; }
      setRequestHeader(name, value) { this.header = [name, value]; }
      send(body) {
        this.body = body;
        this.upload.onprogress({ lengthComputable: true, loaded: 3, total: 4 });
        this.onload();
      }
      abort() { this.onabort?.(); }
    }
    global.XMLHttpRequest = FakeUploadRequest;
    const payload = new FormData();
    payload.append('camera_id', 'cam-checkpoint-01');

    const response = await authUpload('/api/dashboard/video/upload', payload, {
      onProgress: (value) => progress.push(value),
    });

    expect(response.ok).toBe(true);
    expect(await response.json()).toEqual({ source_state: 'READY' });
    expect(progress).toEqual([75]);
    expect(FakeUploadRequest.instance.method).toBe('POST');
    expect(FakeUploadRequest.instance.header).toEqual(['Authorization', 'Bearer upload-token']);
  });
});
