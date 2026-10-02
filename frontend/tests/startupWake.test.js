import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createStartupCoordinator,
  classifyStartupResponse,
  STARTUP_STATUS,
} from '../src/services/startupWake';

const services = {
  backend: { url: 'https://api.example/ready', kind: 'backend' },
  camBorder01: {
    url: 'https://border.example/wake',
    kind: 'edge',
    cameraId: 'cam-border-01',
  },
  camCheckpoint01: {
    url: 'https://checkpoint.example/wake',
    kind: 'edge',
    cameraId: 'cam-checkpoint-01',
  },
};

const prewarm = {
  triggerUrl: 'https://api.example/api/dashboard/startup/prewarm',
  statusUrl: 'https://api.example/api/dashboard/startup/prewarm/status',
};

const payloads = {
  backend: { status: 'ready', database: 'connected' },
  camBorder01: {
    camera_id: 'cam-border-01',
    worker_alive: true,
    last_error: null,
  },
  camCheckpoint01: {
    camera_id: 'cam-checkpoint-01',
    worker_alive: true,
    last_error: null,
  },
};

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

function readyFetch(url) {
  if (url.endsWith('/ready')) return Promise.resolve(response(payloads.backend));
  if (url.endsWith('/startup/prewarm')) return Promise.resolve(response({ cameras: {} }));
  if (url.endsWith('/startup/prewarm/status')) return Promise.resolve(response({ cameras: {} }));
  if (url.includes('border.example')) return Promise.resolve(response(payloads.camBorder01));
  return Promise.resolve(response(payloads.camCheckpoint01));
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('startup response classification', () => {
  it('keeps a backend 503 in WAKING', () => {
    expect(classifyStartupResponse(
      services.backend,
      response({ status: 'starting' }, 503),
      { status: 'starting' },
    )).toBe(STARTUP_STATUS.WAKING);
  });

  it('keeps an edge response in WAKING while its worker is not alive', () => {
    expect(classifyStartupResponse(
      services.camBorder01,
      response({ camera_id: 'cam-border-01', worker_alive: false, last_error: null }),
      { camera_id: 'cam-border-01', worker_alive: false, last_error: null },
    )).toBe(STARTUP_STATUS.WAKING);
    expect(classifyStartupResponse(
      services.camBorder01,
      response({ camera_id: 'cam-border-01', worker_alive: true, last_error: 'worker failed' }),
      { camera_id: 'cam-border-01', worker_alive: true, last_error: 'worker failed' },
    )).toBe(STARTUP_STATUS.WAKING);
  });

  it('requires the expected camera, live worker, and no last error', () => {
    expect(classifyStartupResponse(
      services.camBorder01,
      response(payloads.camBorder01),
      payloads.camBorder01,
    )).toBe(STARTUP_STATUS.READY);

    expect(classifyStartupResponse(
      services.camBorder01,
      response({ ...payloads.camBorder01, camera_id: 'cam-checkpoint-01' }),
      { ...payloads.camBorder01, camera_id: 'cam-checkpoint-01' },
    )).toBe(STARTUP_STATUS.WAKING);
  });
});

describe('startup coordinator', () => {
  it('dispatches all three direct probes and backend prewarm before awaiting any response', async () => {
    const resolvers = [];
    const fetchImpl = vi.fn(() => new Promise((resolve) => resolvers.push(resolve)));
    const coordinator = createStartupCoordinator({ services, prewarm, fetchImpl });

    const startup = coordinator.start();
    expect(fetchImpl).toHaveBeenCalledTimes(4);
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      services.backend.url,
      services.camBorder01.url,
      services.camCheckpoint01.url,
      prewarm.triggerUrl,
    ]);
    expect(fetchImpl.mock.calls[3][1].method).toBe('POST');

    resolvers[0](response(payloads.backend));
    resolvers[1](response(payloads.camBorder01));
    resolvers[2](response(payloads.camCheckpoint01));
    resolvers[3](response({ cameras: {} }));
    await startup;

    expect(coordinator.getSnapshot().allReady).toBe(true);
    expect(coordinator.getSnapshot().camBorder01.payload.camera_id).toBe('cam-border-01');
  });

  it('does not report allReady until every service is READY', async () => {
    const fetchImpl = vi.fn((url) => {
      if (url.includes('checkpoint.example')) {
        return Promise.resolve(response({
          camera_id: 'cam-checkpoint-01',
          worker_alive: false,
          last_error: null,
        }));
      }
      return readyFetch(url);
    });
    const coordinator = createStartupCoordinator({
      services, prewarm,
      fetchImpl,
      maxStartupMs: 5,
      pollIntervalMs: 1,
    });

    await coordinator.start();
    const state = coordinator.getSnapshot();
    expect(state.backend.status).toBe(STARTUP_STATUS.READY);
    expect(state.camBorder01.status).toBe(STARTUP_STATUS.READY);
    expect(state.camCheckpoint01.status).toBe(STARTUP_STATUS.TIMEOUT);
    expect(state.allReady).toBe(false);
  });

  it('deduplicates concurrent callers into one startup cycle', async () => {
    const fetchImpl = vi.fn(readyFetch);
    const coordinator = createStartupCoordinator({ services, prewarm, fetchImpl });

    const first = coordinator.start();
    const second = coordinator.start();
    expect(first).toBe(second);
    await Promise.all([first, second]);

    expect(fetchImpl).toHaveBeenCalledTimes(5);
    [
      services.backend.url,
      services.camBorder01.url,
      services.camCheckpoint01.url,
      prewarm.triggerUrl,
      prewarm.statusUrl,
    ].forEach((url) => {
      expect(fetchImpl.mock.calls.filter(([calledUrl]) => calledUrl === url)).toHaveLength(1);
    });
  });

  it('stops every timer and does not poll after all services are ready', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(readyFetch);
    const coordinator = createStartupCoordinator({
      services, prewarm,
      fetchImpl,
      pollIntervalMs: 10,
      requestTimeoutMs: 100,
    });

    await coordinator.start();
    expect(coordinator.getSnapshot().allReady).toBe(true);
    expect(coordinator.pendingTimerCount()).toBe(0);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchImpl).toHaveBeenCalledTimes(5);
    expect(coordinator.pendingTimerCount()).toBe(0);
  });

  it('bounds transient retries and ends unfinished services at TIMEOUT', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const fetchImpl = vi.fn(() => Promise.resolve(response({ status: 'starting' }, 503)));
    const coordinator = createStartupCoordinator({
      services, prewarm,
      fetchImpl,
      maxStartupMs: 25,
      pollIntervalMs: 10,
      requestTimeoutMs: 100,
    });

    const startup = coordinator.start();
    await vi.runAllTimersAsync();
    await startup;

    const state = coordinator.getSnapshot();
    expect(state.backend.status).toBe(STARTUP_STATUS.TIMEOUT);
    expect(state.camBorder01.status).toBe(STARTUP_STATUS.TIMEOUT);
    expect(state.camCheckpoint01.status).toBe(STARTUP_STATUS.TIMEOUT);
    expect(state.allReady).toBe(false);
    expect(fetchImpl.mock.calls.length).toBeGreaterThanOrEqual(8);
    expect(fetchImpl.mock.calls.length).toBeLessThanOrEqual(20);
    expect(coordinator.pendingTimerCount()).toBe(0);
  });

  it('retries all three services after a timed-out cycle', async () => {
    const fetchImpl = vi.fn(() => Promise.resolve(response({ status: 'starting' }, 503)));
    const coordinator = createStartupCoordinator({
      services, prewarm,
      fetchImpl,
      maxStartupMs: 5,
      pollIntervalMs: 1,
    });

    vi.useFakeTimers();
    const first = coordinator.start();
    await vi.runAllTimersAsync();
    await first;
    const firstCycleCalls = fetchImpl.mock.calls.length;
    expect(firstCycleCalls).toBeGreaterThanOrEqual(4);

    fetchImpl.mockImplementation(readyFetch);
    const second = coordinator.start({ force: true });
    await vi.runAllTimersAsync();
    await second;

    expect(fetchImpl.mock.calls.length).toBeGreaterThan(firstCycleCalls);
    expect(coordinator.getSnapshot().allReady).toBe(true);
  });

  it('uses backend authority when the Camera 2 browser request stalls', async () => {
    const fetchImpl = vi.fn((url, options = {}) => {
      if (url === services.backend.url) return Promise.resolve(response(payloads.backend));
      if (url === services.camBorder01.url) return Promise.resolve(response(payloads.camBorder01));
      if (url === services.camCheckpoint01.url) {
        return new Promise((resolve, reject) => {
          options.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        });
      }
      if (url === prewarm.triggerUrl) return Promise.resolve(response({ cameras: {} }));
      return Promise.resolve(response({
        cameras: {
          'cam-checkpoint-01': { camera_id: 'cam-checkpoint-01', status: 'ready' },
        },
      }));
    });
    const coordinator = createStartupCoordinator({ services, prewarm, fetchImpl });

    const startedAt = Date.now();
    await coordinator.start();

    expect(Date.now() - startedAt).toBeLessThan(1_000);
    expect(coordinator.getSnapshot().camCheckpoint01.status).toBe(STARTUP_STATUS.READY);
    expect(coordinator.getSnapshot().camCheckpoint01.authority).toBe('backend');
    expect(coordinator.getSnapshot().allReady).toBe(true);
    expect(coordinator.pendingTimerCount()).toBe(0);
  });

  it('rejects a wrong camera identity from both direct and backend authority', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const wrong = { camera_id: 'cam-border-01', worker_alive: true, last_error: null };
    const fetchImpl = vi.fn((url) => {
      if (url === services.backend.url) return Promise.resolve(response(payloads.backend));
      if (url === services.camBorder01.url) return Promise.resolve(response(payloads.camBorder01));
      if (url === services.camCheckpoint01.url) return Promise.resolve(response(wrong));
      if (url === prewarm.triggerUrl) return Promise.resolve(response({ cameras: {} }));
      return Promise.resolve(response({
        cameras: { 'cam-checkpoint-01': { camera_id: 'cam-border-01', status: 'ready' } },
      }));
    });
    const coordinator = createStartupCoordinator({
      services, prewarm, fetchImpl, maxStartupMs: 20, pollIntervalMs: 5,
    });

    const startup = coordinator.start();
    await vi.runAllTimersAsync();
    await startup;

    expect(coordinator.getSnapshot().camCheckpoint01.status).toBe(STARTUP_STATUS.TIMEOUT);
    expect(coordinator.getSnapshot().allReady).toBe(false);
  });

  it('publishes ready services while one genuinely cold edge keeps warming', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const fetchImpl = vi.fn((url) => {
      if (url === services.backend.url) return Promise.resolve(response(payloads.backend));
      if (url === services.camBorder01.url) return Promise.resolve(response(payloads.camBorder01));
      if (url === services.camCheckpoint01.url) {
        return Promise.resolve(response({ ...payloads.camCheckpoint01, worker_alive: false }));
      }
      return Promise.resolve(response({ cameras: {} }));
    });
    const coordinator = createStartupCoordinator({
      services, prewarm, fetchImpl, maxStartupMs: 20, pollIntervalMs: 5,
    });
    const observed = [];
    coordinator.subscribe((state) => observed.push({
      backend: state.backend.status,
      camera1: state.camBorder01.status,
      camera2: state.camCheckpoint01.status,
    }));

    const startup = coordinator.start();
    await vi.runAllTimersAsync();
    await startup;

    expect(observed).toContainEqual({
      backend: STARTUP_STATUS.READY,
      camera1: STARTUP_STATUS.READY,
      camera2: STARTUP_STATUS.WAKING,
    });
    expect(coordinator.getSnapshot().camCheckpoint01.status).toBe(STARTUP_STATUS.TIMEOUT);
  });
});
