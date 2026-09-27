import { describe, expect, it } from 'vitest';
import {
  deriveDashboardMode, filterLiveEvents, selectReliabilityEvent,
  shouldAcceptTelemetry, telemetryStatusAt, latestEventForSession, formatLatestEvent,
  frameResponseMatchesTelemetry,
  isActiveTelemetry,
  telemetryForSource,
} from '../src/utils/dashboardScope';

describe('dynamic dashboard camera scope', () => {
  const events = [
    { event_id: 'a', camera_id: 'cam-border-01', event_type: 'LINE_CROSSING' },
    { event_id: 'b', camera_id: 'cam-checkpoint-01', event_type: 'INTRUSION' },
    { event_id: 'old', camera_id: 'inactive-camera', event_type: 'LOITERING' },
  ];

  it('derives empty, single, and dual modes', () => {
    expect(deriveDashboardMode([])).toBe('EMPTY');
    expect(deriveDashboardMode(['cam-border-01'])).toBe('SINGLE');
    expect(deriveDashboardMode(['cam-border-01', 'cam-checkpoint-01'])).toBe('DUAL');
  });

  it('keeps single-camera timelines isolated', () => {
    expect(filterLiveEvents(events, ['cam-border-01']).map((event) => event.event_id)).toEqual(['a']);
    expect(filterLiveEvents(events, ['cam-checkpoint-01']).map((event) => event.event_id)).toEqual(['b']);
  });

  it('supports dual-camera filtering without admitting inactive history', () => {
    expect(filterLiveEvents(events, ['cam-border-01', 'cam-checkpoint-01']).map((event) => event.event_id)).toEqual(['a', 'b']);
    expect(filterLiveEvents(events, ['cam-border-01', 'cam-checkpoint-01'], 'cam-checkpoint-01').map((event) => event.event_id)).toEqual(['b']);
  });

  it('selects reliability from the active camera only', () => {
    expect(selectReliabilityEvent(events, 'cam-checkpoint-01').event_id).toBe('b');
    expect(selectReliabilityEvent(events, 'inactive-camera', ['cam-border-01', 'cam-checkpoint-01'])).toBeNull();
  });
});

describe('camera telemetry correctness', () => {
  it('rejects older frames in the same analysis session', () => {
    const current = { analysis_session_id: 's1', frame_index: 12, sequence: 4, processed_timestamp: 100 };
    expect(shouldAcceptTelemetry(current, { ...current, frame_index: 11, sequence: 5 })).toBe(false);
    expect(shouldAcceptTelemetry(current, { ...current, frame_index: 13, sequence: 1 })).toBe(true);
  });

  it('rejects a delayed packet from an older session', () => {
    const current = { analysis_session_id: 'new', processed_timestamp: 200 };
    expect(shouldAcceptTelemetry(current, { analysis_session_id: 'old', processed_timestamp: 199 })).toBe(false);
  });

  it('uses measured cadence for live, stale, and offline transitions', () => {
    const telemetry = { timestamp: 10_000, expected_interval_ms: 2_000 };
    expect(telemetryStatusAt(telemetry, 16_999)).toBe('LIVE');
    expect(telemetryStatusAt(telemetry, 18_000)).toBe('STALE');
    expect(telemetryStatusAt(telemetry, 41_000)).toBe('OFFLINE');
  });

  it('does not treat stale telemetry as an active camera source', () => {
    const telemetry = { timestamp: 10_000, expected_interval_ms: 2_000 };
    expect(isActiveTelemetry(telemetry, 16_999)).toBe(true);
    expect(isActiveTelemetry(telemetry, 18_000)).toBe(false);
  });

  it('rejects telemetry from a previous durable upload session', () => {
    const source = { sourceMode: 'durable', sourceId: 'new-session', runState: 'WAKING' };
    expect(telemetryForSource({ analysis_session_id: 'old-session' }, source)).toBeNull();
    expect(telemetryForSource({ analysis_session_id: 'new-session', frame_index: 1 }, source)?.frame_index).toBe(1);
    expect(telemetryForSource({ analysis_session_id: 'new-session' }, { ...source, runState: 'UPLOADING' })).toBeNull();
  });

  it('selects and labels only the latest event from the current session', () => {
    const now = Date.parse('2026-09-24T10:00:08Z');
    const events = [
      { camera_id: 'cam-border-01', stream_id: 'old', event_type: 'LOITERING', timestamp: '2026-09-24T09:59:59Z' },
      { camera_id: 'cam-border-01', stream_id: 'current', event_type: 'LINE_CROSSING', timestamp: '2026-09-24T10:00:00Z' },
    ];
    const event = latestEventForSession(events, 'cam-border-01', 'current');
    expect(event.event_type).toBe('LINE_CROSSING');
    expect(formatLatestEvent(event, now)).toBe('LINE CROSSING · 8s ago');
    expect(latestEventForSession(events, 'cam-border-01', 'missing')).toBeNull();
  });

  it('pairs an image only with matching session, frame, and counts', () => {
    const telemetry = {
      analysis_session_id: 'session-1', frame_index: 42,
      person_count: 5, vehicle_count: 2, track_count: 7,
    };
    const coherent = new Headers({
      'X-Analysis-Session': 'session-1', 'X-Frame-Index': '42',
      'X-Person-Count': '5', 'X-Vehicle-Count': '2', 'X-Track-Count': '7',
    });
    expect(frameResponseMatchesTelemetry(telemetry, coherent)).toBe(true);
    coherent.set('X-Frame-Index', '41');
    expect(frameResponseMatchesTelemetry(telemetry, coherent)).toBe(false);
  });
});
