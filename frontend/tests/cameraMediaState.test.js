import { describe, expect, it } from 'vitest';

import { updateCameraMediaState } from '../src/utils/cameraMediaState';

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
});

