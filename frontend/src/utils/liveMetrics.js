import { telemetryStatusAt } from './dashboardScope';

const STARTUP_EDGE_KEYS = ['camBorder01', 'camCheckpoint01'];

export function startupEdgeReadiness(startup = null) {
  const eligible = STARTUP_EDGE_KEYS.length;
  const ready = startup
    ? STARTUP_EDGE_KEYS.filter((key) => startup[key]?.status === 'READY').length
    : 0;
  return {
    eligible,
    ready,
    revalidating: Boolean(startup?.revalidating),
    lastReady: Number(startup?.lastReadyEdgeCount || 0),
    hasSnapshot: Boolean(startup),
    hasTimeout: Boolean(startup && STARTUP_EDGE_KEYS.some((key) => startup[key]?.status === 'TIMEOUT')),
  };
}

export function deriveGlobalEdgeStatus({ analysisStates = [], lastTelemetryAt = 0, edgeWakeUntil = 0, prewarm = null, startup = null, startupWakeRequested = false, now = Date.now() }) {
  const edgeWaking = Number(edgeWakeUntil) > now;
  const freshTelemetry = Number(lastTelemetryAt) > 0 && now - Number(lastTelemetryAt) < 30_000;
  const prewarmWarming = Number(prewarm?.warming || 0) > 0;
  const prewarmReady = Number(prewarm?.eligible || 0) > 0
    && Number(prewarm?.ready || 0) === Number(prewarm?.eligible || 0);
  const prewarmTerminal = Number(prewarm?.eligible || 0) > 0
    && Number(prewarm?.ready || 0) < Number(prewarm?.eligible || 0)
    && Number(prewarm?.terminal || 0) >= Number(prewarm?.eligible || 0) - Number(prewarm?.ready || 0);
  const startupEdges = startupEdgeReadiness(startup);
  const startupReady = startupEdges.ready === startupEdges.eligible;
  const startupRequested = Boolean(startup?.requested || startupWakeRequested);
  // Worker/service readiness is independent from analysis telemetry. Once the
  // authoritative startup probes confirm both expected workers are reachable,
  // alive, correctly identified, and error-free, stale or fresh frame data
  // must not rewrite EDGE into ONLINE/STALE/OFFLINE.
  if (startupEdges.revalidating) return 'RECHECKING';
  if (startupReady) return 'READY';
  if (startupEdges.hasTimeout) return 'UNAVAILABLE';
  if (!analysisStates.length) {
    if (freshTelemetry) return 'ONLINE';
    if (edgeWaking) return 'WAKING';
    if (startupEdges.hasSnapshot && startupRequested) return 'WARMING';
    if (prewarmWarming || (startupRequested && !prewarm)) return 'WARMING';
    if (prewarmTerminal) return 'UNAVAILABLE';
    return prewarmReady ? 'READY' : 'IDLE';
  }
  const anyActive = analysisStates.some((state) => state.intent === 'ACTIVE');
  const anyWaking = analysisStates.some((state) => state.intent === 'WAKING') || edgeWaking;
  // Current-session telemetry is definitive proof the edge is online, and
  // must outrank a stale local wake timer or a delayed lifecycle intent.
  if (analysisStates.some((state) => state.hasFreshCurrentTelemetry)) return 'ONLINE';
  if (!anyActive && !anyWaking) {
    if (startupEdges.hasSnapshot && startupRequested) return 'WARMING';
    if (prewarmWarming || (startupRequested && !prewarm)) return 'WARMING';
    if (prewarmTerminal) return 'UNAVAILABLE';
    return prewarmReady ? 'READY' : 'IDLE';
  }
  if (anyWaking) return 'WAKING';
  return now - Number(lastTelemetryAt || 0) < 120_000 ? 'STALE' : 'OFFLINE';
}

export function processingFpsForTelemetry(telemetry, now = Date.now()) {
  if (telemetryStatusAt(telemetry, now) !== 'LIVE') return null;
  const fps = Number(telemetry?.processing_fps);
  return Number.isFinite(fps) && fps >= 0 ? fps : null;
}

export function sourceFpsForTelemetry(telemetry) {
  const fps = Number(telemetry?.source_fps ?? telemetry?.fps_declared);
  return Number.isFinite(fps) && fps > 0 ? fps : null;
}
