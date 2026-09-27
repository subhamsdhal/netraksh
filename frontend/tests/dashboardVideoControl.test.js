import { describe, expect, it } from 'vitest';
import { applyReplayResult, bundledSourceState, durableHeartbeat, lifecycleAction, restoringSourceState, scenarioAction, sourceStateFromCurrentVideo } from '../src/utils/dashboardVideoControl';

describe('dashboard video control ownership', () => {
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
      runState: 'PAUSED',
      analysisState: 'PAUSED',
      analysisGeneration: 0,
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
      analysis_state: 'COMPLETED', analysis_generation: 4, scenario: 'paused',
    });
    expect(backendSource).toMatchObject({ sourceId: '94efecfd', sourceName: 'cam 2.mp4', analysisState: 'COMPLETED', analysisGeneration: 4 });
    expect(backendSource).not.toEqual(staleBrowserSource);
    expect(restoringSourceState()).toEqual({ restoring: true, runState: 'RESTORING' });
  });

  it('keeps durable source identity unchanged through replay and preview-only state', () => {
    const source = { sourceMode: 'durable', sourceId: '94efecfd', sourceName: 'cam 2.mp4', runState: 'COMPLETED', analysisState: 'COMPLETED', analysisGeneration: 4 };
    const replayed = applyReplayResult(source, { analysis_state: 'WAKING', analysis_generation: 5 });
    expect(replayed).toMatchObject({ sourceId: '94efecfd', sourceName: 'cam 2.mp4', analysisState: 'WAKING', analysisGeneration: 5 });
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
});
