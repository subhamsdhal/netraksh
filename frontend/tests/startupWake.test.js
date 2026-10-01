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
  if (url.includes('api.example')) return Promise.resolve(response(payloads.backend));
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
  it('dispatches all three first probes before awaiting any response', async () => {
    const resolvers = [];
    const fetchImpl = vi.fn(() => new Promise((resolve) => resolvers.push(resolve)));
    const coordinator = createStartupCoordinator({ services, fetchImpl });

    const startup = coordinator.start();
    expect(fetchImpl).toHaveBeenCalledTimes(3);

    resolvers[0](response(payloads.backend));
    resolvers[1](response(payloads.camBorder01));
    resolvers[2](response(payloads.camCheckpoint01));
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
      services,
      fetchImpl,
      maxStartupMs: 0,
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
    const coordinator = createStartupCoordinator({ services, fetchImpl });

    const first = coordinator.start();
    const second = coordinator.start();
    expect(first).toBe(second);
    await Promise.all([first, second]);

    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('stops every timer and does not poll after all services are ready', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(readyFetch);
    const coordinator = createStartupCoordinator({
      services,
      fetchImpl,
      pollIntervalMs: 10,
      requestTimeoutMs: 100,
    });

    await coordinator.start();
    expect(coordinator.getSnapshot().allReady).toBe(true);
    expect(coordinator.pendingTimerCount()).toBe(0);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(coordinator.pendingTimerCount()).toBe(0);
  });

  it('bounds transient retries and ends unfinished services at TIMEOUT', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const fetchImpl = vi.fn(() => Promise.resolve(response({ status: 'starting' }, 503)));
    const coordinator = createStartupCoordinator({
      services,
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
    expect(fetchImpl.mock.calls.length).toBeGreaterThanOrEqual(6);
    expect(fetchImpl.mock.calls.length).toBeLessThanOrEqual(12);
    expect(coordinator.pendingTimerCount()).toBe(0);
  });

  it('retries all three services after a timed-out cycle', async () => {
    const fetchImpl = vi.fn(() => Promise.resolve(response({ status: 'starting' }, 503)));
    const coordinator = createStartupCoordinator({
      services,
      fetchImpl,
      maxStartupMs: 0,
    });

    await coordinator.start();
    expect(fetchImpl).toHaveBeenCalledTimes(3);

    fetchImpl.mockImplementation(readyFetch);
    await coordinator.start({ force: true });

    expect(fetchImpl).toHaveBeenCalledTimes(6);
    expect(coordinator.getSnapshot().allReady).toBe(true);
  });
});
