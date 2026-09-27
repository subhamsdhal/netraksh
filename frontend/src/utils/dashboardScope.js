export function deriveDashboardMode(activeCameraIds = []) {
  const count = new Set(activeCameraIds.filter(Boolean)).size;
  return count === 0 ? 'EMPTY' : count === 1 ? 'SINGLE' : 'DUAL';
}

export function lifecycleStatus(sourceState, telemetry, now = Date.now()) {
  const telemetryStatus = telemetryStatusAt(telemetry, now);
  if (telemetryStatus === 'LIVE') return 'ONLINE';
  if (telemetryStatus === 'STALE') return 'STALE';
  if (telemetryStatus === 'COMPLETED') return 'COMPLETED';
  const state = String(sourceState?.analysisState || sourceState?.runState || '').toUpperCase();
  if (state === 'WAKING') return 'WAKING';
  if (state === 'PAUSED' || state === 'READY') return 'PAUSED';
  if (state === 'COMPLETED') return 'COMPLETED';
  return sourceState?.sourceMode ? 'PAUSED' : 'OFFLINE';
}

export function isActiveTelemetry(telemetry, now = Date.now()) {
  return telemetryStatusAt(telemetry, now) === 'LIVE';
}

export function telemetryForSource(telemetry, sourceState, cameraId = null) {
  if (!telemetry) return null;
  if (cameraId && telemetry.camera_id && telemetry.camera_id !== cameraId) return null;
  if (['UPLOADING', 'SELECTING', 'VALIDATING', 'QUEUED_FOR_NORMALIZATION', 'NORMALIZING', 'ACTIVATING'].includes(sourceState?.runState)) return null;
  if (sourceState?.sourceMode !== 'durable') return telemetry;

  // Durable media identity and analyzed-frame identity are deliberately
  // different concepts. stream_id is the selected upload/source session and
  // analysis_session_id identifies the concrete pipeline/frame generation.
  // Comparing the selected upload against analysis_session_id can make a
  // perfectly healthy new upload look offline and can let an older analyzed
  // frame remain visible. Bind the card to the source session only.
  const sourceSession = telemetry.stream_id || null;
  return Boolean(sourceState.sourceId && sourceSession === sourceState.sourceId) ? telemetry : null;
}

export function filterLiveEvents(events = [], activeCameraIds = [], cameraFilter = 'ALL') {
  const active = new Set(activeCameraIds.filter(Boolean));
  return events.filter((event) => active.has(event.camera_id)
    && (cameraFilter === 'ALL' || event.camera_id === cameraFilter));
}

export function selectReliabilityEvent(events = [], cameraId = null, activeCameraIds = [], analysisSessionId = null) {
  if (activeCameraIds.length && !activeCameraIds.includes(cameraId)) return null;
  return events.find((event) => event.camera_id === cameraId
    && (!analysisSessionId || event.analysis_session_id === analysisSessionId)) || null;
}

export function shouldAcceptTelemetry(current, incoming) {
  if (!current) return true;
  const currentSession = current.analysis_session_id || current.stream_id;
  const incomingSession = incoming.analysis_session_id || incoming.stream_id;
  if (currentSession !== incomingSession) {
    return Number(incoming.processed_timestamp || incoming.timestamp || 0)
      > Number(current.processed_timestamp || current.source_timestamp || 0);
  }
  if (currentSession == null && incomingSession == null) {
    return Number(incoming.processed_timestamp || incoming.timestamp || 0)
      > Number(current.processed_timestamp || current.source_timestamp || current.timestamp || 0);
  }
  if (Number.isFinite(incoming.frame_index) && Number.isFinite(current.frame_index)
      && incoming.frame_index !== current.frame_index) {
    return incoming.frame_index > current.frame_index;
  }
  return Number(incoming.sequence || 0) > Number(current.sequence || 0);
}

export function telemetryThresholds(telemetry) {
  const measured = Number(telemetry?.expected_interval_ms);
  const interval = Number.isFinite(measured) && measured > 0 ? measured : 2000;
  const staleAfterMs = Math.max(5000, Math.min(15000, interval * 3 + 1000));
  return { staleAfterMs, offlineAfterMs: Math.max(30000, staleAfterMs * 3) };
}

export function telemetryStatusAt(telemetry, now = Date.now()) {
  if (!telemetry?.timestamp) return 'OFFLINE';
  if (telemetry.analysis_state === 'COMPLETED') return 'COMPLETED';
  const age = Math.max(0, now - telemetry.timestamp);
  const { staleAfterMs, offlineAfterMs } = telemetryThresholds(telemetry);
  return age <= staleAfterMs ? 'LIVE' : age <= offlineAfterMs ? 'STALE' : 'OFFLINE';
}

export function latestEventForSession(events = [], cameraId, analysisSessionId) {
  if (!cameraId || !analysisSessionId) return null;
  return events.find((event) => event.camera_id === cameraId
    && event.analysis_session_id === analysisSessionId) || null;
}

export function formatLatestEvent(event, now = Date.now()) {
  if (!event?.event_type || !event?.timestamp) return 'None recorded';
  const raw = String(event.timestamp);
  const eventMs = Date.parse(/[zZ]$|[+-]\d\d:\d\d$/.test(raw) ? raw : `${raw}Z`);
  const label = String(event.event_type).replace(/_/g, ' ');
  if (!Number.isFinite(eventMs)) return label;
  const ageMs = Math.max(0, now - eventMs);
  if (ageMs < 60_000) return `${label} · ${Math.round(ageMs / 1000)}s ago`;
  return `${label} · ${new Date(eventMs).toLocaleTimeString()}`;
}

export function frameResponseMatchesTelemetry(telemetry, headers) {
  if (!telemetry || !headers?.get) return false;
  const sessionId = telemetry.analysis_session_id || telemetry.stream_id;
  return headers.get('X-Analysis-Session') === sessionId
    && Number(headers.get('X-Frame-Index')) === Number(telemetry.frame_index)
    && Number(headers.get('X-Person-Count')) === Number(telemetry.person_count)
    && Number(headers.get('X-Vehicle-Count')) === Number(telemetry.vehicle_count)
    && Number(headers.get('X-Track-Count')) === Number(telemetry.track_count);
}
