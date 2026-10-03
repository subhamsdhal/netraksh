import React from 'react';
import { act, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Performance from '../src/pages/Performance';
import { authFetch } from '../src/services/auth';

let wsFixture;

vi.mock('../src/hooks/useWebSocket', () => ({
  default: () => ({
    metrics: wsFixture.metrics,
    liveTracks: wsFixture.liveTracks,
  }),
}));

vi.mock('../src/hooks/useStartupReadiness', () => ({
  default: () => ({
    camBorder01: { status: 'READY' },
    camCheckpoint01: { status: 'READY' },
  }),
}));

vi.mock('../src/services/auth', () => ({
  WS_URL: 'ws://test/ws/dashboard',
  authFetch: vi.fn(),
}));

const frameStats = { mean_ms: 10, p95_ms: 12, max_ms: 15, count: 4 };
const eventStats = { mean_ms: 5, p95_ms: 7, max_ms: 8, count: 2 };

function metric(cameraId = 'cam-border-01', overrides = {}) {
  return {
    edge_device_id: cameraId,
    timestamp: '2026-10-02T14:17:27.089488Z',
    uptime_seconds: 151.8,
    fps: 0.24,
    cpu_percent: 0,
    rss_mb: 365.7,
    psutil_available: true,
    alerts_generated: 9,
    telemetry_produced: 30,
    telemetry_dropped: 0,
    telemetry_errors: 0,
    frames: { total_frame_ms: frameStats },
    events: { total_event_ms: eventStats, queue_depth: 0 },
    adaptive_gate: { state: 'ACTIVE', skip_ratio: 0, frames_run: 30, frames_skipped: 0 },
    ...overrides,
  };
}

function response(payload) {
  return { ok: true, status: 200, json: async () => payload };
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('Performance production truth', () => {
  beforeEach(() => {
    wsFixture = { metrics: {}, liveTracks: {} };
    authFetch.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows an initial loader only while no valid metrics exist', () => {
    authFetch.mockReturnValue(new Promise(() => {}));
    render(<Performance />);
    expect(screen.getByText('Loading real metrics…')).toBeInTheDocument();
  });

  it('renders truthful historical semantics, counters, queue gauge, time, and provenance', async () => {
    authFetch.mockResolvedValue(response([metric()]));
    render(<Performance />);

    await screen.findByText('cam-border-01');
    expect(screen.getByText('HISTORICAL REPORT')).toBeInTheDocument();
    expect(screen.getByText(/Report process uptime 2m 31s/)).toHaveTextContent('Last report 2026-10-02 14:17:27 UTC');
    expect(screen.queryByText(/FINAL/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Uptime /i)).not.toBeInTheDocument();

    expect(screen.getByText('Evidence Events Enqueued')).toBeInTheDocument();
    expect(screen.queryByText('Alerts Generated')).not.toBeInTheDocument();
    expect(screen.getByText('Reported Queue Depth')).toBeInTheDocument();
    expect(screen.getByText('0 · report snapshot')).toBeInTheDocument();

    const eventSection = screen.getByText('Per-Event Stage Latency (evidence path)').parentElement;
    expect(within(eventSection).queryByText(/queue_depth/i)).not.toBeInTheDocument();
    expect(within(eventSection).getByText(/mean/)).toBeInTheDocument();

    expect(screen.getByText(/Latency and FPS timings use/)).toHaveTextContent('CPU and memory come from psutil process resource measurements');
    expect(screen.getByText(/Latency and FPS timings use/)).toHaveTextContent('runtime counters and gauges');
    expect(screen.queryByText(/all numbers are from/i)).not.toBeInTheDocument();

    expect(screen.getByText('NO FRESH LIVE TELEMETRY')).toBeInTheDocument();
    expect(screen.queryByText('ANALYSIS IDLE')).not.toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText((content) => content.replace(/\s+/g, '') === 'ACTIVE·skipped0%(0/30frames)')).toBeInTheDocument();
  });

  it('uses the existing authoritative completed state and never infers idle from stale telemetry', async () => {
    wsFixture.liveTracks = {
      'cam-border-01': { timestamp: Date.now() - 120_000, analysis_state: 'COMPLETED' },
    };
    authFetch.mockResolvedValue(response([metric()]));
    render(<Performance />);
    await screen.findByText('ANALYSIS COMPLETED');
    expect(screen.queryByText('ANALYSIS IDLE')).not.toBeInTheDocument();
  });

  it('keeps existing cards visible during a background refresh and after its failure', async () => {
    vi.useFakeTimers();
    let rejectRefresh;
    const pendingRefresh = new Promise((_resolve, reject) => { rejectRefresh = reject; });
    authFetch.mockResolvedValueOnce(response([metric()]));
    authFetch.mockReturnValueOnce(pendingRefresh);
    render(<Performance />);
    await settle();
    expect(screen.getByText('cam-border-01')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(screen.getByText('cam-border-01')).toBeInTheDocument();
    expect(screen.queryByText('Loading real metrics…')).not.toBeInTheDocument();
    expect(screen.getByText('Refreshing performance metrics')).toBeInTheDocument();

    rejectRefresh(new Error('temporary refresh failure'));
    await settle();
    expect(screen.getByText('cam-border-01')).toBeInTheDocument();
    expect(screen.getByText('Could not refresh performance metrics.')).toBeInTheDocument();
  });

  it('merges websocket updates by edge_device_id while keeping two independent cards', async () => {
    wsFixture.metrics = {
      'cam-border-01': metric('cam-border-01', { alerts_generated: 11 }),
      'cam-checkpoint-01': metric('cam-checkpoint-01', { alerts_generated: 19 }),
    };
    authFetch.mockResolvedValue(response([metric('cam-border-01', { alerts_generated: 9 })]));
    render(<Performance />);

    await screen.findByText('cam-border-01');
    expect(screen.getByText('cam-checkpoint-01')).toBeInTheDocument();
    expect(screen.getByText('11')).toBeInTheDocument();
    expect(screen.getByText('19')).toBeInTheDocument();
    expect(screen.getAllByText('Evidence Events Enqueued')).toHaveLength(2);
  });
});
