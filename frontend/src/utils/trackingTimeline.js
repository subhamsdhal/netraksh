export const TRACKING_TIMELINE_LIMIT = 180;
export const TRACKING_SAMPLE_TOLERANCE_SECONDS = 0.16;
export const REPLAY_COVERAGE_TOLERANCE_SECONDS = 0.5;
export const LIVE_PLAYBACK_BUFFER_SECONDS = 0.04;

export function livePlaybackCorrection(
  currentTime,
  sampleTime,
  toleranceSeconds = TRACKING_SAMPLE_TOLERANCE_SECONDS,
) {
  if (currentTime == null || sampleTime == null) return null;
  const current = Number(currentTime);
  const sample = Number(sampleTime);
  if (!Number.isFinite(current) || !Number.isFinite(sample)) return null;
  if (Math.abs(current - sample) <= toleranceSeconds) return null;
  return Math.max(0, sample - LIVE_PLAYBACK_BUFFER_SECONDS);
}

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

export function replayTimelineAssessment(timeline, summary = {}) {
  if (!Array.isArray(timeline) || timeline.length === 0) {
    return { ready: false, reason: 'empty', sampleCount: 0, cadenceHz: null };
  }
  const expected = {
    cameraId: summary.camera_id,
    streamId: summary.stream_id,
    analysisSessionId: summary.analysis_session_id,
    analysisGeneration: summary.analysis_generation,
    sourceGeneration: summary.source_generation,
  };
  const accepted = timeline
    .filter(sample => trackingSampleMatchesScope(sample, expected))
    .sort((left, right) => Number(left.video_time) - Number(right.video_time));
  if (accepted.length !== timeline.length || accepted.length === 0) {
    return { ready: false, reason: 'identity_mismatch', sampleCount: accepted.length, cadenceHz: null };
  }
  const earliest = Number(accepted[0].video_time);
  const latest = Number(accepted[accepted.length - 1].video_time);
  const finalVideoTime = Number(summary.final_video_time);
  const duration = latest - earliest;
  const cadenceHz = accepted.length > 1 && duration > 0
    ? (accepted.length - 1) / duration
    : null;
  if (Number.isFinite(finalVideoTime) && (
    earliest > REPLAY_COVERAGE_TOLERANCE_SECONDS
    || latest < finalVideoTime - REPLAY_COVERAGE_TOLERANCE_SECONDS
  )) {
    return {
      ready: false, reason: 'incomplete_coverage', sampleCount: accepted.length,
      earliest, latest, finalVideoTime, cadenceHz,
    };
  }
  return {
    ready: true, reason: null, sampleCount: accepted.length,
    earliest, latest, finalVideoTime: Number.isFinite(finalVideoTime) ? finalVideoTime : null,
    cadenceHz,
  };
}
