export const TRACKING_TIMELINE_LIMIT = 180;
export const TRACKING_SAMPLE_TOLERANCE_SECONDS = 0.16;

export function trackingSampleMatchesScope(sample, scope) {
  if (!sample || !scope?.cameraId || sample.camera_id !== scope.cameraId) return false;
  if (scope.streamId && sample.stream_id !== scope.streamId) return false;
  if (scope.analysisSessionId && sample.analysis_session_id !== scope.analysisSessionId) return false;
  if (scope.analysisGeneration != null
    && Number(sample.analysis_generation) !== Number(scope.analysisGeneration)) return false;
  if (scope.sourceGeneration != null
    && Number(sample.source_generation) !== Number(scope.sourceGeneration)) return false;
  return Number.isFinite(Number(sample.video_time)) && Number.isFinite(Number(sample.frame_index));
}

export function appendTrackingSample(timeline, sample, scope, limit = TRACKING_TIMELINE_LIMIT) {
  if (!trackingSampleMatchesScope(sample, scope)) return timeline;
  const existing = timeline.findIndex(item => (
    item.analysis_session_id === sample.analysis_session_id
    && Number(item.frame_index) === Number(sample.frame_index)
  ));
  const next = existing >= 0
    ? timeline.map((item, index) => (index === existing ? sample : item))
    : [...timeline, sample];
  next.sort((left, right) => Number(left.video_time) - Number(right.video_time));
  return next.slice(-Math.max(1, limit));
}

export function selectTrackingSample(
  timeline,
  videoTime,
  toleranceSeconds = TRACKING_SAMPLE_TOLERANCE_SECONDS,
) {
  if (!Array.isArray(timeline) || timeline.length === 0 || !Number.isFinite(videoTime)) return null;
  let closest = null;
  let closestDistance = Infinity;
  for (const sample of timeline) {
    const distance = Math.abs(Number(sample.video_time) - videoTime);
    if (distance < closestDistance) {
      closest = sample;
      closestDistance = distance;
    }
    if (Number(sample.video_time) > videoTime && distance > closestDistance) break;
  }
  return closestDistance <= toleranceSeconds ? closest : null;
}

export function trackingIntervalsMs(timeline) {
  return timeline.slice(1).map((sample, index) => (
    (Number(sample.video_time) - Number(timeline[index].video_time)) * 1000
  )).filter(value => Number.isFinite(value) && value >= 0);
}
