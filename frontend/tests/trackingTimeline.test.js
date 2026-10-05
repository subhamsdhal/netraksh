import { describe, expect, it } from 'vitest';
import {
  appendTrackingSample,
  livePlaybackCorrection,
  replayTimelineAssessment,
  selectTrackingSample,
  trackingIntervalsMs,
  TRACKING_TIMELINE_LIMIT,
} from '../src/utils/trackingTimeline';

const scope = {
  cameraId: 'cam-checkpoint-01',
  streamId: 'source-1',
  analysisSessionId: 'run-1',
  analysisGeneration: 2,
};

const sample = (frame, time, extra = {}) => ({
  camera_id: 'cam-checkpoint-01', stream_id: 'source-1',
  analysis_session_id: 'run-1', analysis_generation: 2,
  frame_index: frame, video_time: time, tracks: [], ...extra,
});

describe('tracking timeline', () => {
  it('rejects an older source generation even when the camera and bytes-derived stream context look similar', () => {
    const scope = {
      cameraId: 'cam-checkpoint-01', streamId: 'fresh-source', analysisSessionId: 'fresh-run',
      analysisGeneration: 1, sourceGeneration: 12,
    };
    const stale = sample(1, 0.1, {
      camera_id: 'cam-checkpoint-01', stream_id: 'fresh-source', analysis_session_id: 'fresh-run',
      analysis_generation: 1, source_generation: 11,
    });
    expect(appendTrackingSample([], stale, scope)).toEqual([]);
  });
  it('keeps a bounded ordered current-run timeline and rejects wrong scope', () => {
    let timeline = [];
    for (let index = 0; index < TRACKING_TIMELINE_LIMIT + 20; index += 1) {
      timeline = appendTrackingSample(timeline, sample(index, index / 10), scope);
    }
    expect(timeline).toHaveLength(TRACKING_TIMELINE_LIMIT);
    expect(timeline[0].frame_index).toBe(20);
    expect(appendTrackingSample(timeline, sample(999, 99, { camera_id: 'cam-border-01' }), scope)).toBe(timeline);
  });

  it('selects a close source-time sample and hides stale boxes', () => {
    const timeline = [sample(0, 0), sample(3, 0.125), sample(6, 0.25)];
    expect(selectTrackingSample(timeline, 0.13)?.frame_index).toBe(3);
    expect(selectTrackingSample(timeline, 0.7)).toBeNull();
  });

  it('keeps live source playback within the exact HUD pairing tolerance', () => {
    expect(livePlaybackCorrection(6.38, 6.31)).toBeNull();
    expect(livePlaybackCorrection(10, 6.38)).toBeCloseTo(6.34, 5);
    expect(livePlaybackCorrection(0, 0.5)).toBeCloseTo(0.46, 5);
    expect(livePlaybackCorrection(0, null)).toBeNull();
  });

  it('retains actual moving coordinates and reports source-time cadence', () => {
    const timeline = [
      sample(0, 0, { tracks: [{ track_id: 7, bbox_x: 0.1 }] }),
      sample(3, 0.125, { tracks: [{ track_id: 7, bbox_x: 0.14 }] }),
    ];
    expect(timeline[1].tracks[0].track_id).toBe(7);
    expect(timeline[1].tracks[0].bbox_x).toBeGreaterThan(timeline[0].tracks[0].bbox_x);
    expect(trackingIntervalsMs(timeline)).toEqual([125]);
  });

  it('accepts only an exact-identity timeline covering the completed source duration', () => {
    const timeline = [
      sample(0, 0, { source_generation: 4 }),
      sample(24, 1, { source_generation: 4 }),
      sample(48, 2, { source_generation: 4 }),
    ];
    const summary = {
      camera_id: 'cam-checkpoint-01', stream_id: 'source-1', analysis_session_id: 'run-1',
      analysis_generation: 2, source_generation: 4, final_video_time: 2,
    };
    expect(replayTimelineAssessment(timeline, summary)).toMatchObject({
      ready: true, sampleCount: 3, cadenceHz: 1,
    });
    expect(replayTimelineAssessment(timeline.slice(0, 2), summary)).toMatchObject({
      ready: false, reason: 'incomplete_coverage',
    });
    expect(replayTimelineAssessment([
      { ...timeline[0], analysis_session_id: 'old-run' }, ...timeline.slice(1),
    ], summary)).toMatchObject({ ready: false, reason: 'identity_mismatch' });
  });
});
