import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createStartupCoordinator,
  classifyStartupResponse,
  shouldRevalidateOnResume,
  RESUME_AFTER_MS,
  STARTUP_STATUS,
} from '../src/services/startupWake';

const services = {
  backend: { url: 'https://api.example/ready', wakeUrl: 'https://api.example/ready', kind: 'backend' },
  camBorder01: {
    url: 'https://border.example/health', wakeUrl: 'https://border.example/wake',
    kind: 'edge', cameraId: 'cam-border-01',
  },
  camCheckpoint01: {
    url: 'https://checkpoint.example/health', wakeUrl: 'https://checkpoint.example/wake',
    kind: 'edge', cameraId: 'cam-checkpoint-01',
  },
};

const payloads = {
  backend: { status: 'ready', database: 'connected' },
  camBorder01: { camera_id: 'cam-border-01', worker_alive: true, last_error: null },
  camCheckpoint01: { camera_id: 'cam-checkpoint-01', worker_alive: true, last_error: null },
};

function response(payload, status = 200, json = true) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (!json) throw new SyntaxError('not JSON');
      return payload;
    },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function readyFetch(url) {
  if (url.endsWith('/ready')) return Promise.resolve(response(payloads.backend));
  if (url.includes('border.example')) return Promise.resolve(response(payloads.camBorder01));
  return Promise.resolve(response(payloads.camCheckpoint01));
}

async function poll() {
  await vi.advanceTimersByTimeAsync(5);
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('startup response classification', () => {
  it('requires backend HTTP 200 JSON with database connected', () => {
    expect(classifyStartupResponse(services.backend, response(payloads.backend), payloads.backend)).toBe(STARTUP_STATUS.READY);
    expect(classifyStartupResponse(services.backend, response({ status: 'ready' }), { status: 'ready' })).toBe(STARTUP_STATUS.WAKING);
    expect(classifyStartupResponse(services.backend, response(payloads.backend, 200, false), null)).toBe(STARTUP_STATUS.WAKING);
    expect(classifyStartupResponse(services.backend, response(payloads.backend, 503), payloads.backend)).toBe(STARTUP_STATUS.WAKING);
  });

  it('requires the expected camera identity and live worker state', () => {
    expect(classifyStartupResponse(services.camBorder01, response(payloads.camBorder01), payloads.camBorder01)).toBe(STARTUP_STATUS.READY);
    expect(classifyStartupResponse(services.camBorder01, response({ ...payloads.camBorder01, camera_id: 'cam-checkpoint-01' }), { ...payloads.camBorder01, camera_id: 'cam-checkpoint-01' })).toBe(STARTUP_STATUS.WAKING);
    expect(classifyStartupResponse(services.camBorder01, response({ ...payloads.camBorder01, worker_alive: false }), { ...payloads.camBorder01, worker_alive: false })).toBe(STARTUP_STATUS.WAKING);
  });
});

describe('startup coordinator', () => {
  it('launches backend and both camera wake requests in the same turn', async () => {
    vi.useFakeTimers();
    const pending = [deferred(), deferred(), deferred()];
    const fetchImpl = vi.fn(() => pending[fetchImpl.mock.calls.length - 1].promise);
    const coordinator = createStartupCoordinator({ services, fetchImpl, pollIntervalMs: 5 });
    const startup = coordinator.start();

    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      services.backend.wakeUrl,
      services.camBorder01.wakeUrl,
      services.camCheckpoint01.wakeUrl,
    ]);
    expect(fetchImpl.mock.calls).toHaveLength(3);
    pending[0].resolve(response(payloads.backend));
    pending[1].resolve(response(payloads.camBorder01));
    pending[2].resolve(response(payloads.camCheckpoint01));
    await poll();
    await startup;
    expect(coordinator.getSnapshot().allReady).toBe(true);
  });

  it('tracks backend and Camera 1 readiness while waiting for Camera 2', async () => {
    vi.useFakeTimers();
    let backendReady = false;
    let camera1Ready = false;
    let camera2Ready = false;
    const fetchImpl = vi.fn((url) => {
      if (url.includes('api.example')) return Promise.resolve(response(backendReady ? payloads.backend : { status: 'starting' }, backendReady ? 200 : 503));
      if (url.includes('border.example')) return Promise.resolve(response({ ...payloads.camBorder01, worker_alive: camera1Ready }));
      return Promise.resolve(response({ ...payloads.camCheckpoint01, worker_alive: camera2Ready }));
    });
    const coordinator = createStartupCoordinator({ services, fetchImpl, pollIntervalMs: 5, maxStartupMs: 100 });
    const observed = [];
    coordinator.subscribe((state) => observed.push([state.backend.status, state.camBorder01.status, state.camCheckpoint01.status]));
    const startup = coordinator.start();
    await poll();

    backendReady = true;
    camera1Ready = true;
    await poll();
    expect(coordinator.getSnapshot().camBorder01.status).toBe(STARTUP_STATUS.READY);
    await poll();
    expect(coordinator.getSnapshot().backend.status).toBe(STARTUP_STATUS.READY);
    expect(coordinator.getSnapshot().camCheckpoint01.status).toBe(STARTUP_STATUS.WAKING);
    expect(observed).toContainEqual([STARTUP_STATUS.READY, STARTUP_STATUS.READY, STARTUP_STATUS.WAKING]);
    expect(coordinator.getSnapshot().allReady).toBe(false);

    camera2Ready = true;
    await poll();
    await poll();
    await startup;
    expect(coordinator.getSnapshot().allReady).toBe(true);
  });

  it('keeps Camera 2 READY when it responds before the backend', async () => {
    vi.useFakeTimers();
    let backendReady = false;
    const fetchImpl = vi.fn((url) => {
      if (url.includes('api.example')) return Promise.resolve(response(backendReady ? payloads.backend : { status: 'starting' }, backendReady ? 200 : 503));
      return readyFetch(url);
    });
    const coordinator = createStartupCoordinator({ services, fetchImpl, pollIntervalMs: 5, maxStartupMs: 100 });
    const startup = coordinator.start();
    await poll();
    expect(coordinator.getSnapshot().camCheckpoint01.status).toBe(STARTUP_STATUS.READY);
    expect(coordinator.getSnapshot().backend.status).toBe(STARTUP_STATUS.RETRYING);

    backendReady = true;
    await poll();
    await poll();
    await poll();
    await startup;
    expect(coordinator.getSnapshot().camCheckpoint01.status).toBe(STARTUP_STATUS.READY);
    expect(coordinator.getSnapshot().allReady).toBe(true);
    expect(fetchImpl.mock.calls.filter(([url]) => url === services.camCheckpoint01.wakeUrl || url === services.camCheckpoint01.url)).toHaveLength(1);
  });

  it('bounds one timed out request, then continues polling the healthy services', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn((url, { signal } = {}) => {
      if (url.includes('checkpoint.example')) {
        return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))));
      }
      return readyFetch(url);
    });
    const coordinator = createStartupCoordinator({ services, fetchImpl, pollIntervalMs: 5, requestTimeoutMs: 3, maxStartupMs: 100 });
    const startup = coordinator.start();
    await poll();
    expect(coordinator.getSnapshot().backend.status).toBe(STARTUP_STATUS.READY);
    expect(coordinator.getSnapshot().camBorder01.status).toBe(STARTUP_STATUS.READY);
    expect(coordinator.getSnapshot().camCheckpoint01.status).toBe(STARTUP_STATUS.RETRYING);
    expect(coordinator.getSnapshot().camCheckpoint01.detail).toMatch(/timed out/);
    expect(coordinator.hasActiveCycle()).toBe(true);
    coordinator.reset();
    await startup;
  });

  it('does not accept an opaque or CORS-blocked camera response as READY', async () => {
    vi.useFakeTimers();
    let camera2Ready = false;
    const fetchImpl = vi.fn((url) => {
      if (url.includes('checkpoint.example') && !camera2Ready) return Promise.reject(new TypeError('Failed to fetch'));
      if (url.includes('checkpoint.example')) return Promise.resolve(response(payloads.camCheckpoint01));
      return readyFetch(url);
    });
    const coordinator = createStartupCoordinator({ services, fetchImpl, pollIntervalMs: 5, maxStartupMs: 100 });
    const startup = coordinator.start();
    await poll();
    expect(coordinator.getSnapshot().camCheckpoint01.status).toBe(STARTUP_STATUS.RETRYING);
    expect(coordinator.getSnapshot().allReady).toBe(false);
    camera2Ready = true;
    await poll();
    await poll();
    await startup;
    expect(coordinator.getSnapshot().allReady).toBe(true);
  });

  it('keeps READY services and retries only the unavailable service after timeout', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn((url) => {
      if (url.includes('checkpoint.example')) return Promise.resolve(response({ ...payloads.camCheckpoint01, worker_alive: false }));
      return readyFetch(url);
    });
    const coordinator = createStartupCoordinator({ services, fetchImpl, pollIntervalMs: 5, maxStartupMs: 10 });
    const first = coordinator.start();
    await vi.advanceTimersByTimeAsync(10);
    await first;
    const beforeRetry = fetchImpl.mock.calls.length;
    expect(coordinator.getSnapshot().backend.status).toBe(STARTUP_STATUS.READY);
    expect(coordinator.getSnapshot().camBorder01.status).toBe(STARTUP_STATUS.READY);
    expect(coordinator.getSnapshot().camCheckpoint01.status).toBe(STARTUP_STATUS.TIMEOUT);

    fetchImpl.mockImplementation(readyFetch);
    const retry = coordinator.start({ force: true });
    expect(fetchImpl.mock.calls.slice(beforeRetry).map(([url]) => url)).toEqual([services.camCheckpoint01.wakeUrl]);
    await poll();
    await retry;
    expect(coordinator.getSnapshot().allReady).toBe(true);
  });

  it('cancels an obsolete cycle so an old response cannot overwrite reset state', async () => {
    vi.useFakeTimers();
    const pending = deferred();
    const fetchImpl = vi.fn(() => pending.promise);
    const coordinator = createStartupCoordinator({ services, fetchImpl, pollIntervalMs: 5 });
    const startup = coordinator.start();
    coordinator.reset();
    pending.resolve(response(payloads.backend));
    await vi.advanceTimersByTimeAsync(5);
    await startup;
    expect(coordinator.getSnapshot().backend.status).toBe(STARTUP_STATUS.UNKNOWN);
    expect(coordinator.getSnapshot().allReady).toBe(false);
  });

  it('revalidates after a long tab switch, but not after a short one', () => {
    const state = { readyAt: 10_000, lastReadyAt: 10_000, startedAt: 1_000 };
    expect(shouldRevalidateOnResume(state, 10_000 + RESUME_AFTER_MS - 1)).toBe(false);
    expect(shouldRevalidateOnResume(state, 10_000 + RESUME_AFTER_MS)).toBe(true);
  });
});
