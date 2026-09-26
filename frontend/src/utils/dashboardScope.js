export function deriveDashboardMode(activeCameraIds = []) {
  const count = new Set(activeCameraIds.filter(Boolean)).size;
  return count === 0 ? 'EMPTY' : count === 1 ? 'SINGLE' : 'DUAL';
}

export function isActiveTelemetry(telemetry, now = Date.now()) {
  return telemetryStatusAt(telemetry, now) === 'LIVE';
}

export function filterLiveEvents(events = [], activeCameraIds = [], cameraFilter = 'ALL') {
  const active = new Set(activeCameraIds.filter(Boolean));
  return events.filter((event) => active.has(event.camera_id)
    && (cameraFilter === 'ALL' || event.camera_id === cameraFilter));
}

export function selectReliabilityEvent(events = [], cameraId = null, activeCameraIds = []) {
  if (activeCameraIds.length && !activeCameraIds.includes(cameraId)) return null;
  return events.find((event) => event.camera_id === cameraId) || null;
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
  return events.find((event) => event.camera_id === cameraId && event.stream_id === analysisSessionId) || null;
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
