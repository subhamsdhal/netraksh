import { describe, expect, it } from 'vitest';
import {
  analyzedSampleIdentity,
  analyzedSampleIsNewer,
  analyzedSampleMatchesScope,
  analyzedSampleMetrics,
  containedMediaRect,
} from '../src/utils/analyzedPlayback';

const sample = (overrides = {}) => ({
  camera_id: 'cam-checkpoint-01',
  stream_id: 'source-2',
  analysis_session_id: 'run-2',
  source_generation: 3,
  analysis_generation: 7,
  frame_index: 42,
  sequence: 10,
  video_time: 1.75,
  processing_fps: 0.8,
  source_fps: 24,
  person_count: 1,
  vehicle_count: 0,
  track_count: 1,
  ...overrides,
});

describe('authoritative analyzed playback samples', () => {
  it('keys every frame by camera, source, run, generation and frame', () => {
    expect(analyzedSampleIdentity(sample())).toBe('cam-checkpoint-01:source-2:run-2:3:7:42');
    expect(analyzedSampleIdentity(sample({ analysis_session_id: null }))).toBeNull();
  });

  it('rejects cross-camera, cross-source, cross-run and cross-generation samples', () => {
    const scope = { cameraId: 'cam-checkpoint-01', streamId: 'source-2', analysisSessionId: 'run-2', analysisGeneration: 7, sourceGeneration: 3 };
    expect(analyzedSampleMatchesScope(sample(), scope)).toBe(true);
    expect(analyzedSampleMatchesScope(sample({ camera_id: 'cam-border-01' }), scope)).toBe(false);
    expect(analyzedSampleMatchesScope(sample({ stream_id: 'old-source' }), scope)).toBe(false);
    expect(analyzedSampleMatchesScope(sample({ analysis_session_id: 'old-run' }), scope)).toBe(false);
    expect(analyzedSampleMatchesScope(sample({ analysis_generation: 6 }), scope)).toBe(false);
    expect(analyzedSampleMatchesScope(sample({ source_generation: 2 }), scope)).toBe(false);
  });

  it('does not let an out-of-order frame replace the displayed sample', () => {
    expect(analyzedSampleIsNewer(sample({ frame_index: 42 }), sample({ frame_index: 43 }))).toBe(true);
    expect(analyzedSampleIsNewer(sample({ frame_index: 42 }), sample({ frame_index: 41, sequence: 99 }))).toBe(false);
    expect(analyzedSampleIsNewer(sample({ frame_index: 42, sequence: 10 }), sample({ frame_index: 42, sequence: 9 }))).toBe(false);
  });

  it('keeps displayed counts and timing from one coherent sample including zero', () => {
    expect(analyzedSampleMetrics(sample())).toEqual({
      processing_fps: 0.8, source_fps: 24, person_count: 1, vehicle_count: 0,
      track_count: 1, frame_index: 42, video_time: 1.75, processed_timestamp: null,
    });
  });

  it('computes letterbox and pillarbox geometry from real dimensions', () => {
    expect(containedMediaRect(1000, 1000, 1920, 1080)).toEqual({
      left: 0, top: 218.75, width: 1000, height: 562.5,
    });
    expect(containedMediaRect(1200, 600, 800, 600)).toEqual({
      left: 200, top: 0, width: 800, height: 600,
    });
  });
});
