import { describe, expect, it, vi } from 'vitest';
import { analysisLifecyclePresentation, applyReplayResult, bundledSourceState, canReanalyzeSource, claimUploadAutoStart, durableHeartbeat, fetchWithTimeout, lifecycleAction, reanalyzeRequestPayload, restoringSourceState, runUploadAutoStart, scenarioAction, sourceStateFromCurrentVideo, sourceStateFromPreparation, uploadAutoStartIdentity } from '../src/utils/dashboardVideoControl';

describe('dashboard video control ownership', () => {
  it('offers reanalysis for either completed durable camera source', () => {
    const completed = { sourceMode: 'durable', sourceId: 'stored-camera-1-video', analysisState: 'COMPLETED' };
    expect(canReanalyzeSource('cam-border-01', completed)).toBe(true);
    expect(reanalyzeRequestPayload('cam-border-01', completed, 'request-1')).toEqual({
      camera_id: 'cam-border-01',
      video_session_id: 'stored-camera-1-video',
      request_id: 'request-1',
    });
    expect(reanalyzeRequestPayload('cam-border-01', completed, 'request-1')).not.toHaveProperty('file');
    expect(canReanalyzeSource('cam-checkpoint-01', completed)).toBe(true);
    expect(reanalyzeRequestPayload('cam-checkpoint-01', completed, 'request-2')).toEqual({
      camera_id: 'cam-checkpoint-01',
      video_session_id: 'stored-camera-1-video',
      request_id: 'request-2',
    });
    expect(canReanalyzeSource('cam-unknown-01', completed)).toBe(false);
    expect(canReanalyzeSource('cam-border-01', { ...completed, analysisState: 'ACTIVE' })).toBe(false);
    expect(canReanalyzeSource('cam-border-01', { ...completed, sourceMode: 'bundled' })).toBe(false);
    expect(canReanalyzeSource('cam-border-01', { ...completed, sourceId: null })).toBe(false);
    expect(reanalyzeRequestPayload('cam-border-01', completed, '')).toBeNull();
  });

  it('aborts a stalled read-only restore preflight after the timeout', async () => {
    let requestSignal;
    const fetcher = vi.fn((_path, { signal }) => new Promise((_resolve, reject) => {
      requestSignal = signal;
      signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    }));

    await expect(fetchWithTimeout(fetcher, '/read-only', 5)).rejects.toMatchObject({ name: 'AbortError' });
    expect(requestSignal.aborted).toBe(true);
  });

  it('replaces a stale browser session with the bundled source contract', () => {
    expect(sourceStateFromCurrentVideo({
      available: true,
      source_mode: 'bundled',
      source_name: 'BUNDLED CLOUD DEMO',
      session_id: null,
      scenario: 'paused',
    })).toEqual({
      sourceMode: 'bundled',
      sourceId: null,
      sourceName: 'BUNDLED CLOUD DEMO',
      restoring: false,
      runState: 'PAUSED',
      analysisState: 'PAUSED',
      analysisGeneration: 0,
      sourceGeneration: null,
      uploadIntentId: null,
      scenario: 'paused',
    });
  });

  it('builds bundled START without a fake durable session', () => {
    const payload = scenarioAction('cam-checkpoint-01', { sourceMode: 'bundled', sourceId: null }, 'normal', true);
    expect(payload).toEqual({
      camera_id: 'cam-checkpoint-01',
      source_mode: 'bundled',
      scenario: 'normal',
      video_time: 0,
      wake_edge: true,
    });
    expect(payload).not.toHaveProperty('video_session_id');
  });

  it('provides an explicit bundled fallback when durable preview hydration fails', () => {
    expect(bundledSourceState('paused')).toEqual({
      sourceMode: 'bundled',
      sourceId: null,
      sourceName: 'BUNDLED CLOUD DEMO',
      runState: 'PAUSED',
    });
  });

  it('keeps durable session validation in explicit actions', () => {
    expect(scenarioAction('cam-border-01', { sourceMode: 'durable', sourceId: null }, 'normal', true)).toBeNull();
    expect(scenarioAction('cam-border-01', { sourceMode: 'durable', sourceId: 'session-1' }, 'paused')).toMatchObject({
      source_mode: 'durable',
      video_session_id: 'session-1',
      scenario: 'paused',
      control_action: 'stop',
    });
  });

  it('emits a time-only heartbeat only for the mounted current durable source', () => {
    const source = { sourceMode: 'durable', sourceId: 'session-1' };
    expect(durableHeartbeat('cam-border-01', source, 'stale-session', 5)).toBeNull();
    expect(durableHeartbeat('cam-border-01', { sourceMode: 'bundled' }, null, 5)).toBeNull();
    const payload = durableHeartbeat('cam-border-01', source, 'session-1', 5);
    expect(payload).toEqual({
      camera_id: 'cam-border-01',
      source_mode: 'durable',
      video_session_id: 'session-1',
      video_time: 5,
    });
    expect(payload).not.toHaveProperty('wake_edge');
    expect(payload).not.toHaveProperty('scenario');
  });

  it('uses backend current as the only durable source authority', () => {
    const staleBrowserSource = { sourceMode: 'durable', sourceId: 'stale', sourceName: 'cam 1.mp4', runState: 'COMPLETED' };
    const backendSource = sourceStateFromCurrentVideo({
      available: true, source_mode: 'durable', session_id: '94efecfd', source_name: 'cam 2.mp4',
      analysis_state: 'COMPLETED', analysis_generation: 4, latest_analysis_session_id: 'run-94efecfd',
      source_generation: 7, scenario: 'paused',
    });
    expect(backendSource).toMatchObject({
      sourceId: '94efecfd', sourceName: 'cam 2.mp4', analysisState: 'COMPLETED',
      analysisGeneration: 4, sourceGeneration: 7, latestAnalysisSessionId: 'run-94efecfd',
    });
    expect(backendSource).not.toEqual(staleBrowserSource);
    expect(restoringSourceState()).toEqual({ restoring: true, runState: 'RESTORING' });
  });

  it('preserves the durable control record run identity during restoration', () => {
    const source = sourceStateFromCurrentVideo({
      available: true, source_mode: 'durable', session_id: 'durable-stream',
      source_name: 'cam 1.mp4', analysis_state: 'COMPLETED',
      latest_analysis_session_id: 'real-completed-run',
    });
    expect(source).toMatchObject({
      sourceId: 'durable-stream', latestAnalysisSessionId: 'real-completed-run',
    });
    expect(source.latestAnalysisSessionId).not.toBe(source.sourceId);
  });

  it('keeps durable source identity unchanged through replay and preview-only state', () => {
    const source = { sourceMode: 'durable', sourceId: '94efecfd', sourceName: 'cam 2.mp4', runState: 'COMPLETED', analysisState: 'COMPLETED', analysisGeneration: 4 };
    const replayed = applyReplayResult(source, { analysis_state: 'WAKING', analysis_generation: 5 });
    expect(replayed).toMatchObject({ sourceId: '94efecfd', sourceName: 'cam 2.mp4', analysisState: 'WAKING', analysisGeneration: 5 });
    expect(replayed.latestAnalysisSessionId).toBeNull();
    expect({ ...replayed, previewUrl: '/media/signed' }).toMatchObject({ sourceId: '94efecfd', sourceName: 'cam 2.mp4' });
  });

  it('uses backend lifecycle, not stale telemetry, to derive START versus STOP', () => {
    expect(lifecycleAction({ analysisState: 'COMPLETED', runState: 'LIVE' })).toBe('START');
    expect(lifecycleAction({ analysisState: 'PAUSED' })).toBe('START');
    expect(lifecycleAction({ analysisState: 'READY' })).toBe('START');
    expect(lifecycleAction({ analysisState: 'WAKING' })).toBe('STOP');
    expect(lifecycleAction({ analysisState: 'ACTIVE' })).toBe('STOP');
    expect(lifecycleAction({ analysisState: 'WAKING', scenario: 'paused' })).toBe('START');
    expect(lifecycleAction({ analysisState: 'ACTIVE', scenario: 'paused' })).toBe('START');
  });

  it('builds a single durable START with the backend-restored session', () => {
    const payload = scenarioAction('cam-border-01', { sourceMode: 'durable', sourceId: '94efecfd' }, 'normal', true);
    expect(payload).toEqual({
      camera_id: 'cam-border-01', source_mode: 'durable', video_session_id: '94efecfd',
      scenario: 'normal', video_time: 0, wake_edge: true,
    });
  });

  it('preserves the durable source while applying only the backend lifecycle response', () => {
    const source = {
      sourceMode: 'durable', sourceId: '6179dd0f-session', sourceName: 'cam 1.mp4',
      analysisState: 'WAKING', scenario: 'paused', analysisGeneration: 2,
    };
    expect(applyReplayResult(source, {
      analysis_state: 'WAKING', analysis_generation: 3, scenario: 'normal', edge_status: 'waking',
    })).toMatchObject({
      sourceId: '6179dd0f-session', sourceName: 'cam 1.mp4', analysisState: 'WAKING',
      analysisGeneration: 3, scenario: 'normal',
    });
  });

  it('does not create a durable control payload without its server session identity', () => {
    const missing = scenarioAction('cam-border-01', { sourceMode: 'durable', sourceName: 'cam 1.mp4' }, 'normal', true);
    expect(missing).toBeNull();
  });

  it('presents authoritative analysis lifecycle independently of telemetry freshness', () => {
    expect(analysisLifecyclePresentation({ analysisState: 'STARTING' }).label).toBe('STARTING ANALYSIS...');
    expect(analysisLifecyclePresentation({ analysisState: 'WAKING' }).label).toBe('WAKING AI WORKER...');
    expect(analysisLifecyclePresentation({ analysisState: 'RUNNING' })).toMatchObject({
      label: 'ANALYZING...', badge: 'ONLINE / ANALYZING', retry: false,
    });
    expect(analysisLifecyclePresentation({ analysisState: 'ACTIVE' }, { telemetryStatus: 'STALE' }).label).toBe('ANALYZING...');
    expect(analysisLifecyclePresentation({ analysisState: 'STOPPING' }).label).toBe('FINISHING ANALYSIS...');
    expect(analysisLifecyclePresentation({ analysisState: 'COMPLETED' })).toMatchObject({
      label: 'ANALYSIS COMPLETED', badge: 'COMPLETED', retry: false,
    });
    expect(analysisLifecyclePresentation({ analysisState: 'FAILED' }).label).toBe('ANALYSIS FAILED');
  });

  it('presents upload preparation, restored readiness, and explicit start recovery truthfully', () => {
    expect(analysisLifecyclePresentation({ runState: 'UPLOADING' }, { isUploading: true, uploadStage: 'UPLOADING' }).label).toBe('UPLOADING...');
    expect(analysisLifecyclePresentation({ runState: 'UPLOADED' }).label).toBe('UPLOAD COMPLETE');
    expect(analysisLifecyclePresentation({ runState: 'VALIDATING' }).label).toBe('VALIDATING VIDEO...');
    expect(analysisLifecyclePresentation({ runState: 'UPLOADING' }, { isUploading: true, uploadStage: 'PREPARING' }).label).toBe('PREPARING VIDEO...');
    expect(analysisLifecyclePresentation({ runState: 'NORMALIZING' }, { uploadStage: 'PREPARING' }).label).toBe('PREPARING VIDEO...');
    expect(analysisLifecyclePresentation({ runState: 'STORING' }).label).toBe('STORING VIDEO...');
    expect(analysisLifecyclePresentation({ runState: 'FINALIZING' }).label).toBe('FINALIZING VIDEO...');
    expect(analysisLifecyclePresentation({ analysisState: 'READY', sourceMode: 'durable' }).label).toBe('SOURCE READY');
    expect(analysisLifecyclePresentation({ analysisState: 'READY', sourceMode: 'durable' }, {}, true).label).toBe('STARTING ANALYSIS...');
    expect(analysisLifecyclePresentation(
      { analysisState: 'READY', sourceMode: 'durable' },
      { analysisStartFailed: true },
    )).toMatchObject({ label: 'ANALYSIS START FAILED', retry: true });
  });

  it('restores a persisted preparation job without using browser-only state', () => {
    expect(sourceStateFromPreparation({
      available: true,
      preparation_job_id: 'job-1',
      upload_intent_id: 'intent-1',
      session_id: 'session-1',
      camera_id: 'cam-border-01',
      source_name: 'vid 1.mp4',
      state: 'NORMALIZING',
    })).toMatchObject({
      sourceMode: 'durable', sourceId: 'session-1', sourceName: 'vid 1.mp4',
      runState: 'NORMALIZING', preparationJobId: 'job-1', uploadIntentId: 'intent-1',
    });
    expect(sourceStateFromPreparation({
      available: true,
      preparation_job_id: 'job-1',
      session_id: 'session-1',
      camera_id: 'cam-border-01',
      state: 'READY',
      analysis_state: 'WAKING',
      analysis_generation: 3,
    })).toMatchObject({ runState: 'WAKING', analysisState: 'WAKING', analysisGeneration: 3 });
  });

  it('claims one automatic start for one authoritative new upload only', () => {
    const claims = new Set();
    const ready = { sourceMode: 'durable', sourceId: 'new-source', analysisState: 'READY' };
    const identity = uploadAutoStartIdentity('cam-checkpoint-01', ready, 'upload-request-1');
    expect(identity).toBe('cam-checkpoint-01:new-source:upload-request-1');
    expect(claimUploadAutoStart(claims, identity)).toBe(true);
    expect(claimUploadAutoStart(claims, identity)).toBe(false);
    expect(claimUploadAutoStart(claims, identity)).toBe(false);
  });

  it('never grants auto-start authority to restored, completed, running or identity-less sources', () => {
    expect(uploadAutoStartIdentity('cam-checkpoint-01', {
      sourceMode: 'durable', sourceId: 'stored-source', analysisState: 'READY',
    }, null)).toBeNull();
    expect(uploadAutoStartIdentity('cam-checkpoint-01', {
      sourceMode: 'durable', sourceId: 'stored-source', analysisState: 'COMPLETED',
    }, 'upload-request')).toBeNull();
    expect(uploadAutoStartIdentity('cam-checkpoint-01', {
      sourceMode: 'durable', sourceId: 'stored-source', analysisState: 'ACTIVE',
    }, 'upload-request')).toBeNull();
    expect(uploadAutoStartIdentity('cam-checkpoint-01', {
      sourceMode: 'durable', analysisState: 'READY',
    }, 'upload-request')).toBeNull();
  });

  it('isolates automatic start claims by camera, source and upload generation', () => {
    const claims = new Set();
    const ready = (sourceId) => ({ sourceMode: 'durable', sourceId, runState: 'READY' });
    const camera2 = uploadAutoStartIdentity('cam-checkpoint-01', ready('source-2'), 'upload-2');
    expect(claimUploadAutoStart(claims, camera2)).toBe(true);
    expect(claimUploadAutoStart(claims, uploadAutoStartIdentity('cam-border-01', ready('source-1'), 'upload-1'))).toBe(true);
    expect(claimUploadAutoStart(claims, camera2)).toBe(false);
    expect(claims).toHaveLength(2);
  });

  it('dispatches exactly one existing start path for repeated READY notifications', async () => {
    const claims = new Set();
    const start = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    const input = {
      claims, cameraId: 'cam-checkpoint-01', uploadRequestId: 'upload-2', start,
      sourceState: { sourceMode: 'durable', sourceId: 'source-2', analysisState: 'READY' },
    };
    const first = await runUploadAutoStart(input);
    const pollingRepeat = await runUploadAutoStart(input);
    const websocketRepeat = await runUploadAutoStart(input);
    expect(first).toMatchObject({ attempted: true, outcome: { ok: true } });
    expect(pollingRepeat).toEqual({ attempted: false, duplicate: true });
    expect(websocketRepeat).toEqual({ attempted: false, duplicate: true });
    expect(start).toHaveBeenCalledTimes(1);
    expect(start).toHaveBeenCalledWith('cam-checkpoint-01', input.sourceState, 'new-upload');
  });

  it('does not dispatch on restoration and returns an auto-start failure for manual recovery', async () => {
    const start = vi.fn().mockResolvedValue({ ok: false, status: 503, error: 'worker unavailable' });
    const restored = await runUploadAutoStart({
      claims: new Set(), cameraId: 'cam-checkpoint-01', uploadRequestId: null, start,
      sourceState: { sourceMode: 'durable', sourceId: 'stored-source', analysisState: 'READY' },
    });
    expect(restored).toEqual({ attempted: false, duplicate: false });
    expect(start).not.toHaveBeenCalled();
    const failed = await runUploadAutoStart({
      claims: new Set(), cameraId: 'cam-checkpoint-01', uploadRequestId: 'new-upload', start,
      sourceState: { sourceMode: 'durable', sourceId: 'new-source', analysisState: 'READY' },
    });
    expect(failed).toMatchObject({ attempted: true, outcome: { ok: false, status: 503 } });
    expect(start).toHaveBeenCalledTimes(1);
  });
});
