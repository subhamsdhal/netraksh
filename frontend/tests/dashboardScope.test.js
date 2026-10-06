import { describe, expect, it } from 'vitest';
import {
  deriveDashboardMode, filterLiveEvents, selectReliabilityEvent,
  shouldAcceptTelemetry, shouldDispatchAnalyzedSample, telemetryStatusAt, latestEventForSession, formatLatestEvent,
  frameResponseMatchesTelemetry,
  isActiveTelemetry,
  telemetryForSource,
  analysisSessionIdForSource,
  completedRunSummaryIdentity,
  completedRunMetrics,
  uploadedRunComparison,
  eventsForCameraRun,
  latestFaceEventForSession,
  latestPlateEventForSession,
  latestEventAtOrBeforeFrame,
  selectedRunContext,
  lifecycleStatus,
  operationalCameraIds,
  preferredOperationalCamera,
  mostRecentTelemetryCamera,
  restoredRunCamera,
  currentRunEventEmptyState,
  cameraInventoryIsRestoring,
} from '../src/utils/dashboardScope';

describe('completed Command Center data', () => {
  const sourceA = { sourceMode: 'durable', sourceId: 'stream-a', latestAnalysisSessionId: 'run-a', runState: 'COMPLETED', sourceName: 'vid 1.mp4' };
  const sourceB = { sourceMode: 'durable', sourceId: 'stream-b', latestAnalysisSessionId: 'run-b', runState: 'COMPLETED', sourceName: 'vid 2.mp4' };
  const summaryA = { camera_id: 'cam-border-01', stream_id: 'stream-a', analysis_session_id: 'run-a', final_frame_index: 90, final_video_time: 3, track_count: 4, person_count: 3, completed_at: 100 };
  const summaryB = { camera_id: 'cam-checkpoint-01', stream_id: 'stream-b', analysis_session_id: 'run-b', final_frame_index: 50, track_count: 2, completed_at: 101 };

  it('restores final values after completion and prefers an exact displayed frame', () => {
    expect(completedRunMetrics('cam-border-01', sourceA, null, null, summaryA).sample).toBe(summaryA);
    const displayed = { camera_id: 'cam-border-01', stream_id: 'stream-a', analysis_session_id: 'run-a', frame_index: 42, track_count: 2 };
    expect(completedRunMetrics('cam-border-01', sourceA, null, displayed, summaryA).sample).toBe(displayed);
    expect(completedRunMetrics('cam-border-01', sourceA, null, { ...displayed, analysis_session_id: 'old-run' }, summaryA).sample).toBe(summaryA);
  });

  it('compares two uploaded runs without mixing old events or claiming a shared clock', () => {
    const comparison = uploadedRunComparison(
      ['cam-border-01', 'cam-checkpoint-01'],
      { 'cam-border-01': sourceA, 'cam-checkpoint-01': sourceB },
      {},
      { 'cam-border-01': summaryA, 'cam-checkpoint-01': summaryB },
      [
        { camera_id: 'cam-border-01', stream_id: 'stream-a', analysis_session_id: 'run-a', event_type: 'LOITERING' },
        { camera_id: 'cam-border-01', stream_id: 'old-stream', analysis_session_id: 'old-run', event_type: 'INTRUSION' },
      ],
    );
    expect(comparison).toHaveLength(2);
    expect(comparison[0].sourceName).toBe('vid 1.mp4');
    expect(comparison[0].events).toHaveLength(1);
    expect(comparison[0].eventTypes).toEqual(['LOITERING']);
    expect(comparison[1].events).toHaveLength(0);
    expect(uploadedRunComparison(['cam-border-01'], { 'cam-border-01': sourceA }, {}, { 'cam-border-01': { ...summaryA, stream_id: 'old-stream' } }, [])).toHaveLength(0);
  });
});

describe('dynamic dashboard camera scope', () => {
  it('uses restored durable run identity but never substitutes stream identity', () => {
    expect(analysisSessionIdForSource(null, { sourceId: 'stream-1', latestAnalysisSessionId: 'run-1' })).toBe('run-1');
    expect(analysisSessionIdForSource(null, { sourceId: 'stream-1' })).toBeNull();
    expect(analysisSessionIdForSource({ analysis_session_id: 'fresh-run' }, { latestAnalysisSessionId: 'old-run' })).toBe('fresh-run');
  });
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
  it('keeps an authoritative running source operational while telemetry is stale', () => {
    const now = 30_000;
    const ids = operationalCameraIds(
      ['cam-border-01', 'cam-checkpoint-01'],
      {
        'cam-border-01': { analysisState: 'COMPLETED' },
        'cam-checkpoint-01': { analysisState: 'ACTIVE' },
      },
      {
        'cam-border-01': { timestamp: now - 100 },
        'cam-checkpoint-01': { timestamp: now - 20_000, expected_interval_ms: 2_000 },
      },
      now,
    );
    expect(ids).toEqual(['cam-checkpoint-01']);
    expect(preferredOperationalCamera('cam-border-01', ids, ['cam-border-01', 'cam-checkpoint-01']))
      .toBe('cam-checkpoint-01');
  });

  it('lets authoritative completion terminate a stale local ACTIVE control state', () => {
    expect(operationalCameraIds(
      ['cam-checkpoint-01'],
      { 'cam-checkpoint-01': { analysisState: 'ACTIVE' } },
      { 'cam-checkpoint-01': { timestamp: 10_000, analysis_state: 'COMPLETED' } },
      10_100,
    )).toEqual([]);
  });

  it('does not let completed or paused cameras override an explicit selection', () => {
    expect(operationalCameraIds(
      ['cam-border-01', 'cam-checkpoint-01'],
      { 'cam-border-01': { analysisState: 'COMPLETED' }, 'cam-checkpoint-01': { analysisState: 'PAUSED' } },
      {},
    )).toEqual([]);
    expect(preferredOperationalCamera('cam-checkpoint-01', [], ['cam-border-01', 'cam-checkpoint-01']))
      .toBe('cam-checkpoint-01');
  });

  it('restores the presentation scope to the most recently observed completed run', () => {
    const cameraIds = ['cam-border-01', 'cam-checkpoint-01'];
    const sources = {
      'cam-border-01': { latestAnalysisSessionId: 'run-1' },
      'cam-checkpoint-01': { latestAnalysisSessionId: 'run-2' },
    };
    const cameraOneOnly = {
      'cam-border-01': { analysis_session_id: 'run-1', analysis_state: 'COMPLETED', timestamp: 1000, processed_timestamp: 1000 },
    };
    expect(restoredRunCamera(cameraIds, sources, cameraOneOnly, 3000)).toBeNull();
    expect(restoredRunCamera(cameraIds, sources, {
      ...cameraOneOnly,
      'cam-checkpoint-01': { analysis_session_id: 'run-2', analysis_state: 'COMPLETED', timestamp: 2000, processed_timestamp: 2000 },
    }, 3000, {
      'cam-border-01': { analysis_session_id: 'run-1', camera_id: 'cam-border-01', completed_at: 1000 },
      'cam-checkpoint-01': { analysis_session_id: 'run-2', camera_id: 'cam-checkpoint-01', completed_at: 2000 },
    })).toBe('cam-checkpoint-01');
    expect(mostRecentTelemetryCamera(cameraIds, {
      ...cameraOneOnly,
      'cam-checkpoint-01': { processed_timestamp: 2000 },
    })).toBe('cam-checkpoint-01');
  });

  it('uses persisted run summaries when a backend restart has no in-memory completion telemetry', () => {
    const cameraIds = ['cam-border-01', 'cam-checkpoint-01'];
    const sources = {
      'cam-border-01': { latestAnalysisSessionId: 'run-1' },
      'cam-checkpoint-01': { latestAnalysisSessionId: 'run-2' },
    };
    const telemetry = {
      'cam-border-01': {
        analysis_session_id: 'run-1', analysis_state: 'COMPLETED',
        timestamp: 1000, processed_timestamp: 1000,
      },
    };
    expect(restoredRunCamera(cameraIds, sources, telemetry, 3000, {})).toBeNull();
    expect(restoredRunCamera(cameraIds, sources, telemetry, 3000, {
      'cam-checkpoint-01': {
        analysis_session_id: 'run-2', camera_id: 'cam-checkpoint-01', completed_at: 2000,
      },
    })).toBeNull();
    expect(restoredRunCamera(cameraIds, sources, telemetry, 3000, {
      'cam-border-01': {
        analysis_session_id: 'run-1', camera_id: 'cam-border-01', completed_at: 1000,
      },
      'cam-checkpoint-01': {
        analysis_session_id: 'run-2', camera_id: 'cam-checkpoint-01', completed_at: 2000,
      },
    })).toBe('cam-checkpoint-01');
    expect(restoredRunCamera(cameraIds, sources, telemetry, 3000, {
      'cam-border-01': {
        analysis_session_id: 'run-1', camera_id: 'cam-border-01', completed_at: 1000,
      },
      'cam-checkpoint-01': {
        analysis_session_id: 'run-previous', camera_id: 'cam-checkpoint-01', completed_at: 2000,
      },
    })).toBe('cam-checkpoint-01');
  });

  it('waits for every visible source response before restoring presentation scope', () => {
    const cameraIds = ['cam-border-01', 'cam-checkpoint-01'];
    expect(cameraInventoryIsRestoring(cameraIds, {
      'cam-border-01': { restoring: false, latestAnalysisSessionId: 'run-1' },
    }, true)).toBe(true);
    expect(cameraInventoryIsRestoring(cameraIds, {
      'cam-border-01': { restoring: false, latestAnalysisSessionId: 'run-1' },
      'cam-checkpoint-01': { restoring: true },
    }, true)).toBe(true);
    expect(cameraInventoryIsRestoring(cameraIds, {
      'cam-border-01': { restoring: false, latestAnalysisSessionId: 'run-1' },
      'cam-checkpoint-01': { restoring: false, latestAnalysisSessionId: 'run-2' },
    }, true)).toBe(false);
  });
  it('rejects older frames in the same analysis session', () => {
    const current = { analysis_session_id: 's1', frame_index: 12, sequence: 4, processed_timestamp: 100 };
    expect(shouldAcceptTelemetry(current, { ...current, frame_index: 11, sequence: 5 })).toBe(false);
    expect(shouldAcceptTelemetry(current, { ...current, frame_index: 13, sequence: 1 })).toBe(true);
  });

  it('rejects a delayed packet from an older session', () => {
    const current = { analysis_session_id: 'new', processed_timestamp: 200 };
    expect(shouldAcceptTelemetry(current, { analysis_session_id: 'old', processed_timestamp: 199 })).toBe(false);
  });

  it('delivers a late exact-frame detector sample without regressing latest card telemetry', () => {
    const current = { camera_id: 'cam-border-01', stream_id: 'source-1', analysis_session_id: 'run-1',
      analysis_generation: 1, source_generation: 2, frame_index: 100, sequence: 10, processed_timestamp: 200 };
    const detector = { ...current, frame_index: 80, sequence: 11, visualization_only: true };
    expect(shouldAcceptTelemetry(current, detector)).toBe(false);
    expect(shouldDispatchAnalyzedSample(current, detector)).toBe(true);
    expect(shouldDispatchAnalyzedSample(current, { ...detector, analysis_session_id: 'old-run', processed_timestamp: 199 })).toBe(false);
    expect(shouldDispatchAnalyzedSample(current, { ...detector, source_generation: 1 })).toBe(false);
    expect(shouldDispatchAnalyzedSample(current, { ...detector, camera_id: 'cam-checkpoint-01' })).toBe(false);
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

  it('keeps configured paused/completed sources distinct from live telemetry', () => {
    expect(lifecycleStatus({ sourceMode: 'durable', runState: 'PAUSED' }, null)).toBe('PAUSED');
    expect(lifecycleStatus({ sourceMode: 'durable', runState: 'WAKING' }, null)).toBe('WAKING');
    expect(lifecycleStatus({ sourceMode: 'durable', runState: 'COMPLETED' }, null)).toBe('COMPLETED');
    expect(lifecycleStatus({ sourceMode: 'durable', runState: 'LIVE' }, null)).toBe('WAITING');
    expect(lifecycleStatus({ sourceMode: 'durable', runState: 'PAUSED' }, { timestamp: 1000 }, 1001)).toBe('ONLINE');
    expect(lifecycleStatus(null, null)).toBe('IDLE');
  });

  it('does not describe an active restored camera as paused while telemetry is still recovering', () => {
    expect(currentRunEventEmptyState({
      operationalIds: ['cam-checkpoint-01'],
      configuredIds: ['cam-border-01', 'cam-checkpoint-01'],
      sourceStates: {
        'cam-border-01': { runState: 'PAUSED' },
        'cam-checkpoint-01': { runState: 'LIVE' },
      },
    })).toBe('PROCESSING — NO VERIFIED SECURITY EVENT YET.');
  });

  it('binds durable telemetry to source stream_id, not analyzed-frame session id', () => {
    const source = { sourceMode: 'durable', sourceId: 'new-upload', runState: 'WAKING' };
    expect(telemetryForSource({
      stream_id: 'old-upload',
      analysis_session_id: 'frame-generation-newer',
    }, source)).toBeNull();
    expect(telemetryForSource({
      stream_id: 'new-upload',
      analysis_session_id: 'frame-generation-1',
      frame_index: 1,
    }, source)?.frame_index).toBe(1);
    expect(telemetryForSource({
      stream_id: 'new-upload',
      analysis_session_id: 'frame-generation-2',
    }, { ...source, runState: 'UPLOADING' })).toBeNull();
  });

  it('fetches completed run history from exact telemetry identity while the source pointer lags', () => {
    expect(completedRunSummaryIdentity(
      'cam-checkpoint-01',
      { sourceMode: 'durable', sourceId: 'stream-current', analysisGeneration: 6 },
      { analysis_session_id: 'run-current', stream_id: 'stream-current', analysis_generation: 6 },
    )).toEqual({
      cameraId: 'cam-checkpoint-01',
      streamId: 'stream-current',
      analysisSessionId: 'run-current',
      analysisGeneration: 6,
    });
  });

  it('does not invent a completed run summary identity without a real run session', () => {
    expect(completedRunSummaryIdentity(
      'cam-checkpoint-01',
      { sourceMode: 'durable', sourceId: 'stream-current', analysisGeneration: 6 },
      { stream_id: 'stream-current', analysis_generation: 6 },
    )).toBeNull();
  });

  it('rejects an older replay generation even when the durable stream is unchanged', () => {
    const source = {
      sourceMode: 'durable', sourceId: 'same-upload', analysisGeneration: 2,
      latestAnalysisSessionId: 'run-2', runState: 'ACTIVE',
    };
    expect(telemetryForSource({
      camera_id: 'cam-border-01', stream_id: 'same-upload',
      analysis_session_id: 'run-1', analysis_generation: 1,
    }, source, 'cam-border-01')).toBeNull();
    expect(telemetryForSource({
      camera_id: 'cam-border-01', stream_id: 'same-upload',
      analysis_session_id: 'run-2', analysis_generation: 2,
    }, source, 'cam-border-01')).not.toBeNull();
  });

  it('filters current-view events by camera, stream, and authoritative run', () => {
    const scoped = filterLiveEvents([
      { event_id: 'old-source', camera_id: 'cam-border-01', stream_id: 'stream-a', analysis_session_id: 'run-a' },
      { event_id: 'old-replay', camera_id: 'cam-border-01', stream_id: 'stream-b', analysis_session_id: 'run-b1' },
      { event_id: 'current', camera_id: 'cam-border-01', stream_id: 'stream-b', analysis_session_id: 'run-b2' },
    ], { 'cam-border-01': { streamId: 'stream-b', analysisSessionId: 'run-b2' } });
    expect(scoped.map(event => event.event_id)).toEqual(['current']);
  });

  it('keeps explicit zero distinct from a missing frame count', () => {
    const headers = new Headers({
      'X-Analysis-Session': 'run', 'X-Frame-Index': '1',
      'X-Person-Count': '0', 'X-Vehicle-Count': '0', 'X-Track-Count': '0',
    });
    expect(frameResponseMatchesTelemetry({
      analysis_session_id: 'run', frame_index: 1,
      person_count: 0, vehicle_count: 0, track_count: 0,
    }, headers)).toBe(true);
    expect(frameResponseMatchesTelemetry({
      analysis_session_id: 'run', frame_index: 1,
      person_count: null, vehicle_count: null, track_count: null,
    }, headers)).toBe(false);
  });

  it('selects and labels only the latest event from the current session', () => {
    const now = Date.parse('2026-09-24T10:00:08Z');
    const events = [
      { camera_id: 'cam-border-01', stream_id: 'same-upload', analysis_session_id: 'old-run', event_type: 'LOITERING', timestamp: '2026-09-24T09:59:59Z' },
      { camera_id: 'cam-border-01', stream_id: 'same-upload', analysis_session_id: 'current-run', event_type: 'LINE_CROSSING', timestamp: '2026-09-24T10:00:00Z' },
    ];
    const event = latestEventForSession(events, 'cam-border-01', 'current-run', 'same-upload');
    expect(event.event_type).toBe('LINE_CROSSING');
    expect(formatLatestEvent(event, now)).toBe('LINE CROSSING · 8s ago');
    expect(latestEventForSession(events, 'cam-border-01', 'missing', 'same-upload')).toBeNull();
    expect(latestEventForSession(events, 'cam-border-01', 'current-run', 'other-upload')).toBeNull();
  });

  it('restores the latest event from all nine exact current-run events', () => {
    const events = Array.from({ length: 9 }, (_, index) => ({
      event_id: `event-${index}`,
      camera_id: 'cam-border-01',
      stream_id: 'stream-current',
      analysis_session_id: 'run-current',
      event_type: index === 8 ? 'VIRTUAL_FENCE_CROSSING' : 'LOITERING',
      timestamp: `2026-10-02T14:${String(index).padStart(2, '0')}:00Z`,
    }));
    expect(latestEventForSession(events, 'cam-border-01', 'run-current', 'stream-current')?.event_id).toBe('event-8');
  });

  it('keeps card selection independent of the ten-row display limit', () => {
    const latestCameraOne = {
      event_id: 'camera-one-latest', camera_id: 'cam-border-01', stream_id: 'stream-1',
      analysis_session_id: 'run-1', event_type: 'LINE_CROSSING', timestamp: '2026-10-02T14:30:00Z',
    };
    const authoritative = [
      ...Array.from({ length: 11 }, (_, index) => ({
        event_id: `camera-two-${index}`, camera_id: 'cam-checkpoint-01', stream_id: 'stream-2',
        analysis_session_id: 'run-2', event_type: 'LOITERING', timestamp: `2026-10-02T15:${String(index).padStart(2, '0')}:00Z`,
      })),
      latestCameraOne,
    ];
    const displayEvents = authoritative.slice(0, 10);
    expect(displayEvents).not.toContain(latestCameraOne);
    expect(latestEventForSession(authoritative, 'cam-border-01', 'run-1', 'stream-1')).toBe(latestCameraOne);
  });

  it('keeps card selection independent of the event table camera filter', () => {
    const authoritative = [
      { event_id: 'cam-1', camera_id: 'cam-border-01', stream_id: 'stream-1', analysis_session_id: 'run-1', timestamp: '2026-10-02T14:00:00Z' },
      { event_id: 'cam-2', camera_id: 'cam-checkpoint-01', stream_id: 'stream-2', analysis_session_id: 'run-2', timestamp: '2026-10-02T14:01:00Z' },
    ];
    const cameraTwoTable = authoritative.filter((event) => event.camera_id === 'cam-checkpoint-01');
    expect(cameraTwoTable.some((event) => event.camera_id === 'cam-border-01')).toBe(false);
    expect(latestEventForSession(authoritative, 'cam-border-01', 'run-1', 'stream-1')?.event_id).toBe('cam-1');
  });

  it('isolates two cameras and a replay of the same stream', () => {
    const events = [
      { event_id: 'cam-1-old-run', camera_id: 'cam-border-01', stream_id: 'stream-1', analysis_session_id: 'run-1', timestamp: '2026-10-02T15:00:00Z' },
      { event_id: 'cam-1-current', camera_id: 'cam-border-01', stream_id: 'stream-1', analysis_session_id: 'run-2', timestamp: '2026-10-02T14:00:00Z' },
      { event_id: 'cam-2-current', camera_id: 'cam-checkpoint-01', stream_id: 'stream-2', analysis_session_id: 'run-3', timestamp: '2026-10-02T16:00:00Z' },
    ];
    expect(latestEventForSession(events, 'cam-border-01', 'run-2', 'stream-1')?.event_id).toBe('cam-1-current');
    expect(latestEventForSession(events, 'cam-checkpoint-01', 'run-3', 'stream-2')?.event_id).toBe('cam-2-current');
  });

  it('orders out-of-order events by timestamp, created_at, then stable id', () => {
    const events = [
      { event_id: 'older', camera_id: 'cam-border-01', stream_id: 'stream', analysis_session_id: 'run', timestamp: '2026-10-02T14:05:00Z' },
      { event_id: 'tie-a', camera_id: 'cam-border-01', stream_id: 'stream', analysis_session_id: 'run', timestamp: '2026-10-02T14:10:00Z', created_at: '2026-10-02T14:10:01Z' },
      { event_id: 'tie-b', camera_id: 'cam-border-01', stream_id: 'stream', analysis_session_id: 'run', timestamp: '2026-10-02T14:10:00Z', created_at: '2026-10-02T14:10:02Z' },
    ];
    expect(latestEventForSession(events, 'cam-border-01', 'run', 'stream')?.event_id).toBe('tie-b');
  });

  it('formats an unknown ABSTAIN truthfully and preserves a genuine no-event state', () => {
    const event = {
      event_id: 'abstain', camera_id: 'cam-border-01', stream_id: 'stream', analysis_session_id: 'run',
      decision_state: 'ABSTAIN', event_type: 'unknown', timestamp: '2026-10-02T14:00:00Z',
    };
    expect(formatLatestEvent(event, Date.parse('2026-10-02T14:00:05Z'))).toBe('SYSTEM ABSTAIN · 5s ago');
    expect(latestEventForSession([], 'cam-border-01', 'run', 'stream')).toBeNull();
    expect(formatLatestEvent(null)).toBe('None recorded');
  });

  it('selects ANPR and face results from exact current-run events', () => {
    const events = [
      { event_id: 'old-plate', camera_id: 'cam-border-01', stream_id: 'stream', analysis_session_id: 'old-run', normalized_plate_text: 'OLD', timestamp: '2026-10-02T15:00:00Z' },
      { event_id: 'plate', camera_id: 'cam-border-01', stream_id: 'stream', analysis_session_id: 'run', normalized_plate_text: 'CURRENT', timestamp: '2026-10-02T14:00:00Z' },
      { event_id: 'face', camera_id: 'cam-border-01', stream_id: 'stream', analysis_session_id: 'run', event_type: 'FACE_DETECTED', face_match_status: 'KNOWN', timestamp: '2026-10-02T14:01:00Z' },
      { event_id: 'other-camera', camera_id: 'cam-checkpoint-01', stream_id: 'other', analysis_session_id: 'other-run', normalized_plate_text: 'OTHER', face_match_status: 'KNOWN', timestamp: '2026-10-02T16:00:00Z' },
    ];
    expect(eventsForCameraRun(events, 'cam-border-01', 'run', 'stream').map((event) => event.event_id)).toEqual(['plate', 'face']);
    expect(latestPlateEventForSession(events, 'cam-border-01', 'run', 'stream')?.event_id).toBe('plate');
    expect(latestFaceEventForSession(events, 'cam-border-01', 'run', 'stream')?.event_id).toBe('face');
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

  it('builds one selected-run and frame context without leaking another camera or generation', () => {
    const context = selectedRunContext(
      'cam-border-01',
      {
        'cam-border-01': { sourceId: 'stream-1', latestAnalysisSessionId: 'run-2', sourceGeneration: 5, analysisGeneration: 8 },
        'cam-checkpoint-01': { sourceId: 'stream-2', latestAnalysisSessionId: 'run-9' },
      },
      {
        'cam-border-01': { stream_id: 'stream-1', analysis_session_id: 'run-2' },
        'cam-checkpoint-01': { stream_id: 'stream-2', analysis_session_id: 'run-9' },
      },
      { 'cam-border-01': { frame_index: 120, video_time: 4.8 } },
    );
    expect(context).toMatchObject({
      cameraId: 'cam-border-01', streamId: 'stream-1', analysisSessionId: 'run-2',
      sourceGeneration: 5, analysisGeneration: 8, frameIndex: 120, videoTime: 4.8,
    });
  });

  it('selects a reliability event only from the selected run at or before the visible frame', () => {
    const context = {
      cameraId: 'cam-border-01', streamId: 'stream-1', analysisSessionId: 'run-2', videoTime: 4.8,
    };
    const events = [
      { event_id: 'old-run', camera_id: 'cam-border-01', stream_id: 'stream-1', analysis_session_id: 'run-1', video_time: 4.7 },
      { event_id: 'visible', camera_id: 'cam-border-01', stream_id: 'stream-1', analysis_session_id: 'run-2', video_time: 4.5 },
      { event_id: 'future', camera_id: 'cam-border-01', stream_id: 'stream-1', analysis_session_id: 'run-2', video_time: 5.0 },
      { event_id: 'camera-2', camera_id: 'cam-checkpoint-01', stream_id: 'stream-2', analysis_session_id: 'run-9', video_time: 4.6 },
    ];
    expect(latestEventAtOrBeforeFrame(events, context)?.event_id).toBe('visible');
    expect(latestEventAtOrBeforeFrame(events, { ...context, videoTime: 4.0 })).toBeNull();
  });
});
