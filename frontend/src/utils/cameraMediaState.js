export const DEFAULT_CAMERA_MEDIA = Object.freeze({
  mediaUrl: null,
  mediaType: 'video',
  isUploading: false,
  sessionId: null,
  sessionStartTime: 0,
  uploadError: null,
  playbackEnded: false,
});

export function updateCameraMediaState(state, cameraId, patch) {
  if (!cameraId) return state;
  return {
    ...state,
    [cameraId]: {
      ...DEFAULT_CAMERA_MEDIA,
      ...(state[cameraId] || {}),
      ...patch,
    },
  };
}

