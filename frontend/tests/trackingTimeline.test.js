import { describe, expect, it } from 'vitest';
import {
  appendTrackingSample,
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

  it('retains actual moving coordinates and reports source-time cadence', () => {
    const timeline = [
      sample(0, 0, { tracks: [{ track_id: 7, bbox_x: 0.1 }] }),
      sample(3, 0.125, { tracks: [{ track_id: 7, bbox_x: 0.14 }] }),
    ];
    expect(timeline[1].tracks[0].track_id).toBe(7);
    expect(timeline[1].tracks[0].bbox_x).toBeGreaterThan(timeline[0].tracks[0].bbox_x);
    expect(trackingIntervalsMs(timeline)).toEqual([125]);
  });
});
