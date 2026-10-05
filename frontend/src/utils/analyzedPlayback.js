export function analyzedSampleIdentity(sample) {
  if (!sample?.camera_id || !sample?.stream_id || !sample?.analysis_session_id) return null;
  if (!Number.isFinite(Number(sample.frame_index))) return null;
  return [sample.camera_id, sample.stream_id, sample.analysis_session_id,
    sample.source_generation ?? 'source-generation',
    sample.analysis_generation ?? 'generation', Number(sample.frame_index)].join(':');
}

export function analyzedSampleMatchesScope(sample, {
  cameraId, streamId, analysisSessionId = null, analysisGeneration = null, sourceGeneration = null,
} = {}) {
  if (!analyzedSampleIdentity(sample) || !cameraId || !streamId) return false;
  if (sample.camera_id !== cameraId || sample.stream_id !== streamId) return false;
  if (analysisSessionId && sample.analysis_session_id !== analysisSessionId) return false;
  if (analysisGeneration != null && Number(sample.analysis_generation) !== Number(analysisGeneration)) return false;
  if (sourceGeneration != null && Number(sample.source_generation) !== Number(sourceGeneration)) return false;
  return true;
}

export function analyzedSampleIsNewer(current, incoming) {
  if (!analyzedSampleIdentity(incoming)) return false;
  if (!current) return true;
  const run = sample => [sample.camera_id, sample.stream_id, sample.analysis_session_id,
    sample.source_generation, sample.analysis_generation].join(':');
  if (run(current) !== run(incoming)) return true;
  const currentFrame = Number(current.frame_index);
  const incomingFrame = Number(incoming.frame_index);
  if (incomingFrame !== currentFrame) return incomingFrame > currentFrame;
  return Number(incoming.sequence || 0) > Number(current.sequence || 0);
}

export function analyzedSampleMetrics(sample) {
  if (!sample) return null;
  return {
    processing_fps: Number.isFinite(Number(sample.processing_fps)) ? Number(sample.processing_fps) : null,
    source_fps: Number.isFinite(Number(sample.source_fps ?? sample.fps_declared))
      ? Number(sample.source_fps ?? sample.fps_declared) : null,
    person_count: sample.person_count ?? null,
    vehicle_count: sample.vehicle_count ?? null,
    track_count: sample.track_count ?? null,
    frame_index: Number.isFinite(Number(sample.frame_index)) ? Number(sample.frame_index) : null,
    video_time: Number.isFinite(Number(sample.video_time)) ? Number(sample.video_time) : null,
    processed_timestamp: sample.processed_timestamp ?? sample.timestamp ?? null,
  };
}

export function containedMediaRect(containerWidth, containerHeight, mediaWidth, mediaHeight) {
  if (![containerWidth, containerHeight, mediaWidth, mediaHeight].every(value => Number(value) > 0)) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }
  const containerRatio = containerWidth / containerHeight;
  const mediaRatio = mediaWidth / mediaHeight;
  if (containerRatio > mediaRatio) {
    const height = containerHeight;
    const width = height * mediaRatio;
    return { left: (containerWidth - width) / 2, top: 0, width, height };
  }
  const width = containerWidth;
  const height = width / mediaRatio;
  return { left: 0, top: (containerHeight - height) / 2, width, height };
}
