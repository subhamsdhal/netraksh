import { describe, expect, it } from 'vitest';
import { bundledSourceState, durableHeartbeat, scenarioAction, sourceStateFromCurrentVideo } from '../src/utils/dashboardVideoControl';

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
});
