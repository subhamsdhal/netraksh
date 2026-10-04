export function deriveDashboardMode(activeCameraIds = []) {
  const count = new Set(activeCameraIds.filter(Boolean)).size;
  return count === 0 ? 'EMPTY' : count === 1 ? 'SINGLE' : 'DUAL';
}

export function operationalCameraIds(cameraIds = [], sourceStates = {}, telemetryByCamera = {}, now = Date.now()) {
  return cameraIds.filter((cameraId) => {
    const source = sourceStates[cameraId] || {};
    const lifecycle = String(source.analysisState || source.runState || '').toUpperCase();
    const telemetryState = telemetryStatusAt(telemetryByCamera[cameraId], now);
    if (telemetryState === 'COMPLETED') return false;
    if (['STARTING', 'WAKING', 'ACTIVE', 'LIVE', 'RUNNING', 'STOPPING'].includes(lifecycle)) return true;
    if (['COMPLETED', 'FAILED', 'PAUSED', 'READY', 'IDLE'].includes(lifecycle)) return false;
    return ['LIVE', 'STALE'].includes(telemetryState);
  });
}

export function preferredOperationalCamera(selectedCameraId, operationalIds = [], visibleIds = []) {
  if (operationalIds.length === 1) return operationalIds[0];
  if (selectedCameraId && visibleIds.includes(selectedCameraId)) return selectedCameraId;
  return operationalIds[0] || visibleIds[0] || null;
}

export function mostRecentTelemetryCamera(cameraIds = [], telemetryByCamera = {}) {
  return cameraIds.reduce((latest, cameraId) => {
    const telemetry = telemetryByCamera[cameraId];
    if (!telemetry) return latest;
    const observedAt = Number(telemetry.processed_timestamp ?? telemetry.timestamp ?? 0);
    return !latest || observedAt > latest.observedAt ? { cameraId, observedAt } : latest;
  }, null)?.cameraId || null;
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
  // No source is an honest idle analysis state. Node availability is rendered
  // independently and OFFLINE is reserved for a genuinely unavailable node.
  return sourceState?.sourceMode ? 'PAUSED' : 'IDLE';
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
  if (!sourceState.sourceId || sourceSession !== sourceState.sourceId) return null;
  if (sourceState.analysisGeneration != null
      && Number(telemetry.analysis_generation) !== Number(sourceState.analysisGeneration)) return null;
  if (sourceState.latestAnalysisSessionId
      && telemetry.analysis_session_id !== sourceState.latestAnalysisSessionId) return null;
  return telemetry;
}

// A completed durable source can outlive the process-local telemetry cache.
// Its control record retains the last real run identity; source identity is
// deliberately not a fallback for that value.
export function analysisSessionIdForSource(telemetry, sourceState) {
  return telemetry?.analysis_session_id || sourceState?.latestAnalysisSessionId || null;
}

export function filterLiveEvents(events = [], activeCameraIds = [], cameraFilter = 'ALL') {
  const contexts = Array.isArray(activeCameraIds) ? null : activeCameraIds;
  const active = new Set(Array.isArray(activeCameraIds) ? activeCameraIds.filter(Boolean) : Object.keys(contexts || {}));
  return events.filter((event) => {
    if (!active.has(event.camera_id) || (cameraFilter !== 'ALL' && event.camera_id !== cameraFilter)) return false;
    if (!contexts) return true;
    const context = contexts[event.camera_id];
    if (!context?.streamId || event.stream_id !== context.streamId) return false;
    return !context.analysisSessionId || event.analysis_session_id === context.analysisSessionId;
  });
}

export function selectReliabilityEvent(events = [], cameraId = null, activeCameraIds = [], analysisSessionId = null, streamId = null) {
  if (activeCameraIds.length && !activeCameraIds.includes(cameraId)) return null;
  return events.find((event) => event.camera_id === cameraId
    && (!streamId || event.stream_id === streamId)
    && (!analysisSessionId || event.analysis_session_id === analysisSessionId)) || null;
}

export function shouldAcceptTelemetry(current, incoming) {
  if (!current) return true;
  if (current.stream_id === incoming.stream_id
      && current.analysis_generation != null && incoming.analysis_generation != null
      && Number(current.analysis_generation) !== Number(incoming.analysis_generation)) {
    return Number(incoming.analysis_generation) > Number(current.analysis_generation);
  }
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

function eventTimestampMs(value) {
  if (value == null || value === '') return Number.NEGATIVE_INFINITY;
  if (typeof value === 'number') return value < 1_000_000_000_000 ? value * 1000 : value;
  const numeric = Number(value);
  if (Number.isFinite(numeric)) return numeric < 1_000_000_000_000 ? numeric * 1000 : numeric;
  const raw = String(value);
  const parsed = Date.parse(/[zZ]$|[+-]\d\d:\d\d$/.test(raw) ? raw : `${raw}Z`);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function compareEventRecency(left, right) {
  const timestampDelta = eventTimestampMs(left?.timestamp) - eventTimestampMs(right?.timestamp);
  if (timestampDelta) return timestampDelta;
  const createdDelta = eventTimestampMs(left?.created_at) - eventTimestampMs(right?.created_at);
  if (createdDelta) return createdDelta;
  return String(left?.event_id || left?.id || '').localeCompare(String(right?.event_id || right?.id || ''));
}

export function eventsForCameraRun(events = [], cameraId, analysisSessionId, streamId) {
  if (!cameraId || !analysisSessionId || !streamId) return [];
  return events.filter((event) => event.camera_id === cameraId
    && event.stream_id === streamId
    && event.analysis_session_id === analysisSessionId);
}

export function latestEventForSession(events = [], cameraId, analysisSessionId, streamId) {
  const scopedEvents = eventsForCameraRun(events, cameraId, analysisSessionId, streamId);
  return scopedEvents.reduce((latest, event) => (
    !latest || compareEventRecency(event, latest) > 0 ? event : latest
  ), null);
}

export function latestPlateEventForSession(events = [], cameraId, analysisSessionId, streamId) {
  return latestEventForSession(
    events.filter((event) => event.normalized_plate_text || event.plate_text),
    cameraId,
    analysisSessionId,
    streamId,
  );
}

export function latestFaceEventForSession(events = [], cameraId, analysisSessionId, streamId) {
  return latestEventForSession(
    events.filter((event) => String(event.event_type || '').toUpperCase() === 'FACE_DETECTED'
      || event.face_match_status || event.face_match_person_id || event.recognition_state),
    cameraId,
    analysisSessionId,
    streamId,
  );
}

export function formatLatestEvent(event, now = Date.now()) {
  if (!event || !event.timestamp) return 'None recorded';
  const eventType = String(event.event_type || '').trim();
  const decisionState = String(event.decision_state || event.decision || '').toUpperCase();
  const label = decisionState === 'ABSTAIN' && (!eventType || eventType.toLowerCase() === 'unknown')
    ? 'SYSTEM ABSTAIN'
    : (eventType ? eventType.replace(/_/g, ' ') : 'EVENT TYPE NOT REPORTED');
  const eventMs = eventTimestampMs(event.timestamp);
  if (!Number.isFinite(eventMs)) return label;
  const ageMs = Math.max(0, now - eventMs);
  if (ageMs < 60_000) return `${label} · ${Math.round(ageMs / 1000)}s ago`;
  return `${label} · ${new Date(eventMs).toLocaleTimeString()}`;
}

export function frameResponseMatchesTelemetry(telemetry, headers) {
  if (!telemetry || !headers?.get) return false;
  const sessionId = telemetry.analysis_session_id || telemetry.stream_id;
  if (['person_count', 'vehicle_count', 'track_count'].some((field) => telemetry[field] == null)) return false;
  return headers.get('X-Analysis-Session') === sessionId
    && Number(headers.get('X-Frame-Index')) === Number(telemetry.frame_index)
    && Number(headers.get('X-Person-Count')) === Number(telemetry.person_count)
    && Number(headers.get('X-Vehicle-Count')) === Number(telemetry.vehicle_count)
    && Number(headers.get('X-Track-Count')) === Number(telemetry.track_count);
}
