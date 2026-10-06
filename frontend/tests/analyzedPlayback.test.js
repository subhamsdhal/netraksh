import { describe, expect, it } from 'vitest';
import {
  acceptedAnalyzedTimeline,
  analyzedSampleAcceptance,
  analyzedSampleIdentity,
  analyzedSampleIsNewer,
  analyzedSampleMatchesScope,
  analyzedSampleMetrics,
  analyzedTrackBoxIsValid,
  containedMediaRect,
  nearestAnalyzedSampleIndex,
} from '../src/utils/analyzedPlayback';

it('selects the nearest source-time sample with ordered binary search, including boundaries', () => {
  const timeline = [0.1, 1.1, 2.1, 5.1, 9.9].map(video_time => ({ video_time }));
  expect(nearestAnalyzedSampleIndex(timeline, Number.NaN)).toBe(0);
  expect(nearestAnalyzedSampleIndex(timeline, 0)).toBe(0);
  expect(nearestAnalyzedSampleIndex(timeline, 1.8)).toBe(2);
  expect(nearestAnalyzedSampleIndex(timeline, 5.0)).toBe(3);
  expect(nearestAnalyzedSampleIndex(timeline, 90)).toBe(4);
});

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
  frame_width: 1280,
  frame_height: 720,
  bbox_format: 'XYWH',
  coordinate_space: 'NORMALIZED_FRAME',
  detection_method: 'YOLO_BYTE_TRACK',
  tracks: [{
    track_id: 8, class_name: 'person', detection_class: 'person', detector_confirmed: true,
    bbox_x: 0.2, bbox_y: 0.1, bbox_w: 0.25, bbox_h: 0.5,
  }],
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

  it('accepts only canonical detector-confirmed samples with coherent counts', () => {
    const scope = { cameraId: 'cam-checkpoint-01', streamId: 'source-2', analysisSessionId: 'run-2', analysisGeneration: 7, sourceGeneration: 3 };
    expect(analyzedSampleAcceptance(sample(), scope).accepted).toBe(true);
    expect(analyzedSampleAcceptance(sample({ detection_method: 'OPTICAL_FLOW' }), scope)).toMatchObject({ accepted: false, reason: 'detector-confirmation' });
    expect(analyzedSampleAcceptance(sample({ person_count: 0 }), scope)).toMatchObject({ accepted: false, reason: 'count-mismatch' });
    expect(analyzedSampleAcceptance(sample({ bbox_format: 'XYXY' }), scope)).toMatchObject({ accepted: false, reason: 'bbox-contract' });
    expect(analyzedSampleAcceptance(sample({ frame_index: null }), scope)).toMatchObject({ accepted: false });
    expect(analyzedSampleAcceptance(sample({ tracks: [{ ...sample().tracks[0], detector_confirmed: undefined }] }), scope)).toMatchObject({ accepted: false, reason: 'detector-confirmation' });
  });

  it('rejects collapsed, off-frame and implausible boxes', () => {
    expect(analyzedTrackBoxIsValid(sample().tracks[0])).toBe(true);
    expect(analyzedTrackBoxIsValid({ bbox_x: 0.2, bbox_y: 0.2, bbox_w: 0, bbox_h: 0.3 })).toBe(false);
    expect(analyzedTrackBoxIsValid({ bbox_x: 1.2, bbox_y: 0.2, bbox_w: 0.1, bbox_h: 0.3 })).toBe(false);
    expect(analyzedTrackBoxIsValid({ bbox_x: 0.2, bbox_y: 0.2, bbox_w: 0.001, bbox_h: 0.9 })).toBe(false);
  });

  it('filters, deduplicates and source-orders accepted replay samples', () => {
    const scope = { cameraId: 'cam-checkpoint-01', streamId: 'source-2', analysisSessionId: 'run-2', analysisGeneration: 7, sourceGeneration: 3 };
    const timeline = acceptedAnalyzedTimeline([
      sample({ frame_index: 44, video_time: 2 }),
      sample({ frame_index: 43, video_time: 1.9 }),
      sample({ frame_index: 45, video_time: 2.1, detection_method: 'OPTICAL_FLOW' }),
    ], scope);
    expect(timeline.map(item => item.frame_index)).toEqual([43, 44]);
    expect(timeline[0]).toMatchObject({ analyzed_frame_index: 43, source_frame_index: 43 });
  });
});
