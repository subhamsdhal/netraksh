import { afterEach, describe, expect, it, vi } from 'vitest';

describe('startup wake fanout', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('is a one-shot, wake-only best-effort request', async () => {
    vi.resetModules();
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    const { __resetStartupWakeForTests, createStartupWakeRequests, requestStartupWake } = await import('../src/services/startupWake');
    __resetStartupWakeForTests();

    const requests = createStartupWakeRequests({
      backend: 'https://api.example.test',
      edges: ['https://edge-1.example.test', 'https://edge-2.example.test'],
    });
    expect(requests).toHaveLength(3);
    await Promise.all([requestStartupWake(), requestStartupWake(), Promise.allSettled(requests)]);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.filter(([url]) => /\/ready$/.test(url))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => /\/wake$/.test(url))).toHaveLength(2);
    expect(fetchMock.mock.calls.every(([url]) => !/scenario|start|stop|upload|events/i.test(url))).toBe(true);
    expect(fetchMock.mock.calls[0][1]).toEqual({ cache: 'no-store' });
  });
});
