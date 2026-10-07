import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  resetCameraContext: vi.fn(),
  refreshEventsForContext: vi.fn(),
  refreshTelemetryForContext: vi.fn(),
}));

vi.mock('../src/services/auth', () => ({
  WS_URL: 'wss://example.invalid',
  BACKEND_URL: 'https://example.invalid',
  authFetch: mocks.authFetch,
  authUpload: vi.fn(),
}));
vi.mock('../src/hooks/useAuth', () => ({ default: () => ({ role: 'ADMIN' }) }));
vi.mock('../src/hooks/useDemoScenario', () => ({ default: () => ({ scenario: 'normal' }) }));
vi.mock('../src/hooks/useStartupReadiness', () => ({
  default: () => ({ camBorder01: { status: 'READY' }, camCheckpoint01: { status: 'READY' } }),
}));
vi.mock('../src/hooks/useWebSocket', () => ({
  default: () => ({
    events: [], health: {}, metrics: {}, liveTracks: {}, isConnected: true,
    connectionStatus: 'CONNECTED',
    cameras: [
      { camera_id: 'cam-border-01', name: 'Border Post Alpha' },
      { camera_id: 'cam-checkpoint-01', name: 'Checkpoint Bravo' },
    ],
    resetCameraContext: mocks.resetCameraContext,
    refreshEventsForContext: mocks.refreshEventsForContext,
    refreshTelemetryForContext: mocks.refreshTelemetryForContext,
  }),
}));
vi.mock('../src/components/VideoFeed', () => ({ default: () => null }));

import Dashboard from '../src/pages/Dashboard';

const sourceId = '22222222-2222-4222-8222-222222222222';
const camera2SourceId = '44444444-4444-4444-8444-444444444444';
const runId = '33333333-3333-4333-8333-333333333333';

function response(body, ok = true) {
  return { ok, status: ok ? 200 : 409, json: async () => body };
}

beforeEach(() => {
  localStorage.setItem('netraksh.cameraSlots', JSON.stringify(['cam-border-01', 'cam-checkpoint-01']));
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
  mocks.authFetch.mockReset();
  mocks.authFetch.mockImplementation(async (path, options = {}) => {
    if (path.startsWith('/api/dashboard/video/current?camera_id=cam-border-01')) {
      return response({
        available: true, source_mode: 'durable', camera_id: 'cam-border-01',
        session_id: sourceId, source_name: 'vid 1.mp4', analysis_state: 'COMPLETED',
        analysis_generation: 4, source_generation: 2, scenario: 'paused',
        latest_analysis_session_id: runId, preview_url: null,
      });
    }
    if (path.startsWith('/api/dashboard/video/current?camera_id=cam-checkpoint-01')) {
      return response({
        available: true, source_mode: 'durable', camera_id: 'cam-checkpoint-01',
        session_id: camera2SourceId, source_name: 'vid 2.mp4',
        analysis_state: 'COMPLETED', analysis_generation: 3, source_generation: 1,
        scenario: 'paused', latest_analysis_session_id: null, preview_url: null,
      });
    }
    if (path === '/api/dashboard/edge/prewarm/status') return response({ status: 'ready' });
    if (path === '/api/dashboard/edge/prewarm') return response({ status: 'ready' });
    if (path.startsWith('/api/nodes/health')) return response([]);
    if (path.startsWith('/system/analysis-runs/')) return response({}, false);
    if (path.startsWith('/api/dashboard/video/reanalyze')) {
      const payload = JSON.parse(options.body);
      return response({
        status: 'success', camera_id: payload.camera_id, source_mode: 'durable',
        source_session_id: payload.video_session_id, analysis_generation: 5, analysis_state: 'WAKING',
        analysis_session_id: null, scenario: 'normal', edge_status: 'waking',
        request_id: payload.request_id, idempotent_replay: false,
      });
    }
    return response({});
  });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe('Command Center restored-source reanalysis', () => {
  it('does not start a run on restore, then sends exactly one explicit Camera 1 reanalyze request', async () => {
    const user = userEvent.setup();
    render(<Dashboard />);

    await screen.findAllByRole('button', { name: 'REANALYZE' });
    const reanalyze = document.querySelector('[data-action="reanalyze-existing-source"][data-camera-id="cam-border-01"]');
    expect(screen.getByText('SOURCE: vid 1.mp4')).toBeInTheDocument();
    expect(reanalyze).toHaveTextContent('REANALYZE');
    expect(document.querySelector('[data-action="reanalyze-existing-source"][data-camera-id="cam-checkpoint-01"]')).toHaveTextContent('REANALYZE');
    expect(mocks.authFetch.mock.calls.some(([path]) => path === '/api/dashboard/video/reanalyze')).toBe(false);
    expect(mocks.authFetch.mock.calls.some(([path, options]) => path === '/api/dashboard/video/scenario' && options?.method === 'POST')).toBe(false);

    await user.click(reanalyze);
    await waitFor(() => expect(mocks.authFetch.mock.calls.filter(([path]) => path === '/api/dashboard/video/reanalyze')).toHaveLength(1));
    const [, options] = mocks.authFetch.mock.calls.find(([path]) => path === '/api/dashboard/video/reanalyze');
    const payload = JSON.parse(options.body);
    expect(payload.camera_id).toBe('cam-border-01');
    expect(payload.video_session_id).toBe(sourceId);
    expect(payload.request_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(payload).not.toHaveProperty('file');
    await waitFor(() => expect(reanalyze).toHaveTextContent('ANALYZING…'));
    expect(reanalyze).toBeDisabled();
    expect(mocks.authFetch.mock.calls.filter(([path]) => path === '/api/dashboard/video/reanalyze')).toHaveLength(1);
  });

  it('reanalyzes Camera 2 only after an explicit click on its completed source', async () => {
    const user = userEvent.setup();
    render(<Dashboard />);
    await screen.findAllByRole('button', { name: 'REANALYZE' });
    expect(mocks.authFetch.mock.calls.some(([path]) => path === '/api/dashboard/video/reanalyze')).toBe(false);

    const camera2Reanalyze = document.querySelector('[data-action="reanalyze-existing-source"][data-camera-id="cam-checkpoint-01"]');
    await user.click(camera2Reanalyze);

    await waitFor(() => expect(mocks.authFetch.mock.calls.filter(([path]) => path === '/api/dashboard/video/reanalyze')).toHaveLength(1));
    const [, options] = mocks.authFetch.mock.calls.find(([path]) => path === '/api/dashboard/video/reanalyze');
    expect(JSON.parse(options.body)).toMatchObject({ camera_id: 'cam-checkpoint-01', video_session_id: camera2SourceId });
    expect(camera2Reanalyze).toHaveTextContent('ANALYZING…');
    expect(camera2Reanalyze).toBeDisabled();
    expect(document.querySelector('[data-action="reanalyze-existing-source"][data-camera-id="cam-border-01"]')).toHaveTextContent('REANALYZE');
  });

  it('reports a failed start and retries the same idempotency request', async () => {
    const user = userEvent.setup();
    render(<Dashboard />);
    const originalFetch = mocks.authFetch.getMockImplementation();
    const attempts = [];
    mocks.authFetch.mockImplementation(async (path, options = {}) => {
      if (path === '/api/dashboard/video/reanalyze') {
        const payload = JSON.parse(options.body);
        attempts.push(payload);
        return attempts.length === 1
          ? response({ detail: 'temporary worker wake failure' }, false)
          : originalFetch(path, options);
      }
      return originalFetch(path, options);
    });

    await screen.findAllByRole('button', { name: 'REANALYZE' });
    const camera1Reanalyze = document.querySelector('[data-action="reanalyze-existing-source"][data-camera-id="cam-border-01"]');
    await user.click(camera1Reanalyze);
    const retry = await screen.findByRole('button', { name: 'RETRY REANALYZE' });
    expect(screen.getAllByText('REANALYZE FAILED')).toHaveLength(2);
    await user.click(retry);

    expect(await screen.findByRole('button', { name: 'ANALYZING…' })).toBeDisabled();
    expect(attempts).toHaveLength(2);
    expect(attempts[1].request_id).toBe(attempts[0].request_id);
    expect(attempts[1].video_session_id).toBe(sourceId);
  });
});
