import { describe, expect, it } from 'vitest';

import {
  sourceIsReady,
  updateCameraMediaState,
  uploadResultIsCurrent,
  visibleUploadState,
} from '../src/utils/cameraMediaState';

const CAM1 = 'cam-border-01';
const CAM2 = 'cam-checkpoint-01';

describe('camera media state isolation', () => {
  it('keeps source IDs, sessions, previews, loading and errors camera-scoped', () => {
    let state = {};
    state = updateCameraMediaState(state, CAM1, {
      mediaUrl: 'blob:camera-1', sessionId: 'session-1', isUploading: true,
      uploadError: 'camera-1-only', playbackEnded: false,
    });
    state = updateCameraMediaState(state, CAM2, {
      mediaUrl: 'blob:camera-2', sessionId: 'session-2', isUploading: false,
      uploadError: null, playbackEnded: true,
    });

    expect(state[CAM1]).toMatchObject({
      mediaUrl: 'blob:camera-1', sessionId: 'session-1', isUploading: true,
      uploadError: 'camera-1-only', playbackEnded: false,
    });
    expect(state[CAM2]).toMatchObject({
      mediaUrl: 'blob:camera-2', sessionId: 'session-2', isUploading: false,
      uploadError: null, playbackEnded: true,
    });
  });

  it('isolates replace, start, stop and same-file independent sessions', () => {
    let state = updateCameraMediaState({}, CAM1, { mediaUrl: 'blob:same-file-a', sessionId: 'session-a' });
    state = updateCameraMediaState(state, CAM2, { mediaUrl: 'blob:same-file-b', sessionId: 'session-b' });
    const camera2BeforeReplace = state[CAM2];

    state = updateCameraMediaState(state, CAM1, {
      mediaUrl: 'blob:same-file-a-reselected', sessionId: 'session-a-2', playbackEnded: false,
    });
    expect(state[CAM2]).toEqual(camera2BeforeReplace);
    expect(state[CAM1].sessionId).not.toBe(state[CAM2].sessionId);

    state = updateCameraMediaState(state, CAM1, { playbackEnded: true });
    expect(state[CAM1].playbackEnded).toBe(true);
    expect(state[CAM2].playbackEnded).toBe(false);
  });

  it('clears stale upload presentation as soon as the exact source is READY', () => {
    const media = { isUploading: true, uploadStage: 'PREPARING', uploadProgress: 100 };
    const source = { sourceMode: 'durable', sourceId: 'source-1', runState: 'READY' };
    expect(sourceIsReady(source)).toBe(true);
    expect(visibleUploadState(media, source)).toEqual({ isUploading: false, stage: null, progress: null });
  });

  it('does not regress a restored READY source to UPLOADING during background polling', () => {
    const restored = { sourceMode: 'durable', sourceId: 'stored-source', runState: 'PAUSED' };
    expect(visibleUploadState({ isUploading: true, uploadStage: 'UPLOADING' }, restored).isUploading).toBe(false);
  });

  it('keeps real stage and byte progress camera-scoped', () => {
    let state = updateCameraMediaState({}, CAM1, { isUploading: true, uploadStage: 'UPLOADING', uploadProgress: 63 });
    state = updateCameraMediaState(state, CAM2, { isUploading: false, uploadStage: null, uploadProgress: null });
    expect(visibleUploadState(state[CAM1], { sourceMode: 'durable', runState: 'UPLOADING' })).toEqual({
      isUploading: true, stage: 'UPLOADING', progress: 63,
    });
    expect(visibleUploadState(state[CAM2], { sourceMode: 'durable', sourceId: 'ready-2', runState: 'READY' }).isUploading).toBe(false);
  });

  it('rejects an older upload completion after a replacement request begins', () => {
    const active = { id: 'new-request' };
    expect(uploadResultIsCurrent(active, 'old-request')).toBe(false);
    expect(uploadResultIsCurrent(active, 'new-request')).toBe(true);
  });

  it('clears progress and errors without changing the other camera', () => {
    let state = updateCameraMediaState({}, CAM1, {
      isUploading: true, uploadStage: 'PREPARING', uploadProgress: 100, uploadError: null,
    });
    state = updateCameraMediaState(state, CAM2, { sessionId: 'camera-2-source', isUploading: false });
    state = updateCameraMediaState(state, CAM1, {
      isUploading: false, uploadStage: null, uploadProgress: null, uploadError: 'INVALID / UNSUPPORTED VIDEO',
    });
    expect(state[CAM1]).toMatchObject({ isUploading: false, uploadStage: null, uploadProgress: null });
    expect(state[CAM2].sessionId).toBe('camera-2-source');
  });
});

