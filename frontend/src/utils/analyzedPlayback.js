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

const finite = value => value !== null && value !== undefined && value !== ''
  && Number.isFinite(Number(value));

export function analyzedTrackBoxIsValid(track) {
  if (!track || !['bbox_x', 'bbox_y', 'bbox_w', 'bbox_h'].every(key => finite(track[key]))) return false;
  const x = Number(track.bbox_x);
  const y = Number(track.bbox_y);
  const width = Number(track.bbox_w);
  const height = Number(track.bbox_h);
  if (width <= 0 || height <= 0 || width > 1.05 || height > 1.05) return false;
  if (x >= 1 || y >= 1 || x + width <= 0 || y + height <= 0) return false;
  const visibleWidth = Math.min(1, x + width) - Math.max(0, x);
  const visibleHeight = Math.min(1, y + height) - Math.max(0, y);
  if (visibleWidth <= 0 || visibleHeight <= 0) return false;
  const area = width * height;
  const aspect = width / height;
  return area >= 0.00001 && area <= 1.05 && aspect >= 0.03 && aspect <= 33;
}

export function analyzedSampleAcceptance(sample, scope = {}, { detectorConfirmedOnly = true } = {}) {
  if (!analyzedSampleMatchesScope(sample, scope)) return { accepted: false, reason: 'scope' };
  if (!finite(sample.frame_index) || Number(sample.frame_index) < 0) return { accepted: false, reason: 'frame' };
  if (!finite(sample.video_time) || Number(sample.video_time) < 0) return { accepted: false, reason: 'time' };
  if (!finite(sample.frame_width) || Number(sample.frame_width) <= 0
      || !finite(sample.frame_height) || Number(sample.frame_height) <= 0) {
    return { accepted: false, reason: 'dimensions' };
  }
  if ((sample.bbox_format ?? 'XYWH') !== 'XYWH'
      || (sample.coordinate_space ?? 'NORMALIZED_FRAME') !== 'NORMALIZED_FRAME') {
    return { accepted: false, reason: 'bbox-contract' };
  }
  if (!Array.isArray(sample.tracks) || !sample.tracks.every(analyzedTrackBoxIsValid)) {
    return { accepted: false, reason: 'bbox' };
  }
  if (sample.tracks.some(track => !finite(track.track_id))) {
    return { accepted: false, reason: 'track-identity' };
  }
  const detectionMethod = String(sample.detection_method || '').toUpperCase();
  if (detectorConfirmedOnly
      && (!detectionMethod.includes('YOLO') || sample.tracks.some(track => track.detector_confirmed !== true))) {
    return { accepted: false, reason: 'detector-confirmation' };
  }
  const className = track => String(
    track.object_class || track.class_name || track.detection_class || '',
  ).toLowerCase();
  const vehicleClasses = new Set(['vehicle', 'car', 'truck', 'bus', 'motorcycle', 'motorbike']);
  const people = sample.tracks.filter(track => className(track) === 'person').length;
  const vehicles = sample.tracks.filter(track => vehicleClasses.has(className(track))).length;
  const ids = new Set(sample.tracks.map(track => String(track.track_id)));
  if ([sample.person_count, sample.vehicle_count, sample.track_count].some(value => !finite(value))) {
    return { accepted: false, reason: 'counts' };
  }
  if (Number(sample.person_count) !== people || Number(sample.vehicle_count) !== vehicles
      || Number(sample.track_count) !== ids.size) {
    return { accepted: false, reason: 'count-mismatch' };
  }
  return {
    accepted: true,
    sample: {
      ...sample,
      frame_index: Number(sample.frame_index),
      analyzed_frame_index: Number(sample.frame_index),
      source_frame_index: Number(sample.frame_index),
      video_time: Number(sample.video_time),
      frame_width: Number(sample.frame_width),
      frame_height: Number(sample.frame_height),
      bbox_format: 'XYWH',
      coordinate_space: 'NORMALIZED_FRAME',
    },
  };
}

export function acceptedAnalyzedTimeline(timeline, scope = {}, options = {}) {
  const accepted = new Map();
  (Array.isArray(timeline) ? timeline : []).forEach(item => {
    const result = analyzedSampleAcceptance(item, scope, options);
    if (!result.accepted) return;
    const key = `${result.sample.frame_index}:${result.sample.video_time}`;
    const previous = accepted.get(key);
    if (!previous || Number(result.sample.sequence || 0) > Number(previous.sequence || 0)) {
      accepted.set(key, result.sample);
    }
  });
  return [...accepted.values()].sort((left, right) => (
    left.video_time - right.video_time || left.frame_index - right.frame_index
  )).slice(-1800);
}

// acceptedAnalyzedTimeline is ordered by source time. A source-to-analyzed
// switch must select its nearest authoritative sample, never the final one.
export function nearestAnalyzedSampleIndex(timeline, sourceTime) {
  if (!timeline?.length) return 0;
  if (!Number.isFinite(sourceTime) || sourceTime <= Number(timeline[0].video_time)) return 0;
  let low = 0;
  let high = timeline.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (Number(timeline[mid].video_time) < sourceTime) low = mid + 1;
    else high = mid;
  }
  if (low >= timeline.length) return timeline.length - 1;
  if (low === 0) return 0;
  return sourceTime - Number(timeline[low - 1].video_time)
    <= Number(timeline[low].video_time) - sourceTime ? low - 1 : low;
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
