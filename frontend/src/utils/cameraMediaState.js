export const DEFAULT_CAMERA_MEDIA = Object.freeze({
  mediaUrl: null,
  mediaType: 'video',
  isUploading: false,
  uploadStage: null,
  uploadProgress: null,
  uploadRequestId: null,
  sessionId: null,
  sessionStartTime: 0,
  uploadError: null,
  analysisStartFailed: false,
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

export function sourceIsReady(sourceState) {
  const state = String(sourceState?.runState || sourceState?.analysisState || '').toUpperCase();
  return Boolean(
    sourceState?.sourceMode
    && (sourceState.sourceMode !== 'durable' || sourceState.sourceId)
    && ['READY', 'PAUSED', 'COMPLETED', 'WAKING', 'ACTIVE', 'LIVE', 'RUNNING'].includes(state),
  );
}

export function visibleUploadState(mediaState, sourceState) {
  if (sourceIsReady(sourceState)) return { isUploading: false, stage: null, progress: null };
  return {
    isUploading: Boolean(mediaState?.isUploading),
    stage: mediaState?.uploadStage || null,
    progress: Number.isFinite(mediaState?.uploadProgress) ? mediaState.uploadProgress : null,
  };
}

export function uploadResultIsCurrent(activeRequest, requestId) {
  return Boolean(activeRequest?.id && activeRequest.id === requestId);
}

