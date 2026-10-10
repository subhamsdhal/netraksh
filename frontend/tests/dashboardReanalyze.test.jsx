import React from 'react';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  authUpload: vi.fn(),
  resetCameraContext: vi.fn(),
  refreshEventsForContext: vi.fn(),
  refreshTelemetryForContext: vi.fn(),
}));

vi.mock('../src/services/auth', () => ({
  WS_URL: 'wss://example.invalid',
  BACKEND_URL: 'https://example.invalid',
  authFetch: mocks.authFetch,
  authUpload: mocks.authUpload,
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
  mocks.authUpload.mockReset();
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
  vi.useRealTimers();
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe('Command Center restored-source reanalysis', () => {
  it('restores both completed sources when readiness fails during an authoritative lookup', async () => {
    vi.useFakeTimers();
    const readiness = [];
    vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => readiness.push(resolve))));
    const originalFetch = mocks.authFetch.getMockImplementation();
    let finishCurrent;
    mocks.authFetch.mockImplementation((path, options) => {
      if (path.startsWith('/api/dashboard/video/current?camera_id=cam-border-01')) {
        return new Promise(resolve => { finishCurrent = resolve; });
      }
      return originalFetch(path, options);
    });
    render(<Dashboard />);
    await act(async () => { readiness[0]({ ok: true }); });
    expect(finishCurrent).toBeTypeOf('function');
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    await act(async () => { readiness[1]({ ok: false }); });
    await act(async () => {
      finishCurrent(response({
        available: true, source_mode: 'durable', camera_id: 'cam-border-01',
        session_id: sourceId, source_name: 'vid 1.mp4', analysis_state: 'COMPLETED',
        analysis_generation: 4, source_generation: 2, scenario: 'paused',
        latest_analysis_session_id: runId, preview_url: null,
      }));
    });
    expect(screen.getByText('SOURCE: vid 1.mp4')).toBeInTheDocument();
    expect(screen.getByText('SOURCE: vid 2.mp4')).toBeInTheDocument();
    expect(screen.queryByText('NO VIDEO SOURCE')).not.toBeInTheDocument();
    expect(mocks.authFetch.mock.calls.some(([path, options]) =>
      path === '/api/dashboard/video/reanalyze'
      || (path === '/api/dashboard/video/scenario' && options?.method === 'POST'))).toBe(false);
  });

  it('shows restoring state until backend readiness and both persisted sources are confirmed', async () => {
    let resolveReady;
    vi.stubGlobal('fetch', vi.fn(() => new Promise((resolve) => { resolveReady = resolve; })));
    render(<Dashboard />);

    expect(screen.getAllByText('RESTORING CLOUD SOURCE...')).toHaveLength(2);
    expect(screen.getAllByText('RESTORING CAMERA STATE').length).toBeGreaterThan(0);
    expect(screen.queryByText('NO VIDEO SOURCE')).not.toBeInTheDocument();
    expect(screen.queryAllByRole('button', { name: 'ADD VIDEO' })).toHaveLength(0);

    resolveReady({ ok: true });
    await screen.findAllByRole('button', { name: 'REANALYZE' });
    expect(screen.getByText('SOURCE: vid 1.mp4')).toBeInTheDocument();
    expect(screen.getByText('SOURCE: vid 2.mp4')).toBeInTheDocument();
    expect(screen.getAllByText('ANALYSIS COMPLETED').length).toBeGreaterThanOrEqual(2);
    expect(mocks.authFetch.mock.calls.some(([path, options]) =>
      path === '/api/dashboard/video/scenario'
      && options?.method === 'POST')).toBe(false);
    expect(mocks.authFetch.mock.calls.some(([path]) => path === '/api/dashboard/video/reanalyze')).toBe(false);
  });

  it('keeps an in-flight authoritative source restore alive through a readiness-probe failure', async () => {
    vi.useFakeTimers();
    const readyResolvers = [];
    vi.stubGlobal('fetch', vi.fn(() => new Promise((resolve) => readyResolvers.push(resolve))));
    let resolveCamera1Current;
    mocks.authFetch.mockImplementation(async (path) => {
      if (path === '/api/nodes/health') return response([]);
      if (path.includes('/api/dashboard/video/preparation/current?')) return response({});
      if (path.startsWith('/api/dashboard/video/current?camera_id=cam-border-01')) {
        return new Promise((resolve) => { resolveCamera1Current = resolve; });
      }
      if (path.startsWith('/api/dashboard/video/current?camera_id=cam-checkpoint-01')) {
        return response({
          available: true, source_mode: 'durable', camera_id: 'cam-checkpoint-01',
          session_id: camera2SourceId, source_name: 'vid 2.mp4', analysis_state: 'COMPLETED',
          analysis_generation: 3, source_generation: 1, scenario: 'paused', preview_url: null,
        });
      }
      if (path.startsWith('/system/analysis-runs/')) return response({});
      return response({});
    });

    render(<Dashboard />);
    expect(screen.getAllByText('RESTORING CAMERA STATE').length).toBeGreaterThan(0);
    await act(async () => {
      readyResolvers[0]({ ok: true });
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(resolveCamera1Current).toBeTypeOf('function');

    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(readyResolvers).toHaveLength(2);
    await act(async () => {
      readyResolvers[1]({ ok: false });
      await Promise.resolve();
    });
    await act(async () => {
      resolveCamera1Current(response({
        available: true, source_mode: 'durable', camera_id: 'cam-border-01',
        session_id: sourceId, source_name: 'vid 1.mp4', analysis_state: 'COMPLETED',
        analysis_generation: 4, source_generation: 2, scenario: 'paused',
        latest_analysis_session_id: runId, preview_url: null,
      }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('SOURCE: vid 1.mp4')).toBeInTheDocument();
    expect(screen.getByText('SOURCE: vid 2.mp4')).toBeInTheDocument();
    expect(screen.getAllByText('ANALYSIS COMPLETED').length).toBeGreaterThanOrEqual(2);
    expect(mocks.authFetch.mock.calls.some(([path]) =>
      path.includes('/api/dashboard/video/preparation/current?'))).toBe(true);
    expect(mocks.authFetch.mock.calls.some(([path]) =>
      path.startsWith('/api/dashboard/video/current?camera_id=cam-border-01'))).toBe(true);
    expect(mocks.authFetch.mock.calls.some(([path]) =>
      path.startsWith(`/system/analysis-runs/${runId}?`))).toBe(true);
    vi.useRealTimers();
  });

  it('automatically starts exactly one analysis after a new Camera 1 upload is ready', async () => {
    const user = userEvent.setup();
    let uploadedSourceId;
    mocks.authUpload.mockImplementation(async (_path, formData) => {
      uploadedSourceId = formData.get('upload_intent_id');
      return response({
        available: true,
        status: 'accepted',
        state: 'READY',
        source_state: 'READY',
        camera_id: 'cam-border-01',
        preparation_job_id: uploadedSourceId,
        upload_intent_id: uploadedSourceId,
        session_id: uploadedSourceId,
        source_name: 'vid 1.mp4',
        source_generation: 7,
      }, true);
    });
    render(<Dashboard />);

    await screen.findAllByRole('button', { name: 'REANALYZE' });
    const file = new File(['video-bytes'], 'vid 1.mp4', { type: 'video/mp4' });
    await user.upload(document.querySelector('input[type="file"][data-camera-id="cam-border-01"]'), file);

    await waitFor(() => {
      expect(mocks.authUpload).toHaveBeenCalledTimes(1);
      const starts = mocks.authFetch.mock.calls.filter(([path, options]) =>
        path === '/api/dashboard/video/scenario'
        && options?.method === 'POST'
        && JSON.parse(options.body).scenario === 'normal',
      );
      expect(starts).toHaveLength(1);
    });
    const starts = mocks.authFetch.mock.calls.filter(([path, request]) =>
      path === '/api/dashboard/video/scenario'
      && request?.method === 'POST'
      && JSON.parse(request.body).scenario === 'normal',
    );
    const [, options] = starts[0];
    expect(JSON.parse(options.body)).toMatchObject({
      camera_id: 'cam-border-01',
      source_mode: 'durable',
      video_session_id: uploadedSourceId,
      scenario: 'normal',
      wake_edge: true,
    });
    expect(starts).toHaveLength(1);
  });

  it('clears the upload spinner and blocks analysis for an ephemeral local-file response', async () => {
    const user = userEvent.setup();
    mocks.authUpload.mockImplementation(async (_path, formData) => {
      const intent = formData.get('upload_intent_id');
      return response({
        status: 'ok', source_state: 'READY', camera_id: 'cam-border-01',
        session_id: intent, upload_intent_id: intent, source_name: 'vid 1.mp4',
        source_generation: null,
      });
    });
    render(<Dashboard />);
    await screen.findAllByRole('button', { name: 'REANALYZE' });
    const file = new File(['video-bytes'], 'vid 1.mp4', { type: 'video/mp4' });
    await user.upload(document.querySelector('input[type="file"][data-camera-id="cam-border-01"]'), file);

    expect(await screen.findByText('FAILED')).toBeInTheDocument();
    expect(screen.queryByText('UPLOADING 100%')).not.toBeInTheDocument();
    const startRequests = mocks.authFetch.mock.calls.filter(([path, options]) =>
      path === '/api/dashboard/video/scenario'
      && options?.method === 'POST'
      && JSON.parse(options.body).scenario === 'normal',
    );
    expect(startRequests).toHaveLength(0);
  });

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
