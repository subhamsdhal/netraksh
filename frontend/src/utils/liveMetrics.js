import { telemetryStatusAt } from './dashboardScope';

export function deriveGlobalEdgeStatus({ analysisStates = [], lastTelemetryAt = 0, edgeWakeUntil = 0, prewarm = null, startupWakeRequested = false, now = Date.now() }) {
  const edgeWaking = Number(edgeWakeUntil) > now;
  const freshTelemetry = Number(lastTelemetryAt) > 0 && now - Number(lastTelemetryAt) < 30_000;
  const prewarmWarming = Number(prewarm?.warming || 0) > 0;
  const prewarmReady = Number(prewarm?.eligible || 0) > 0
    && Number(prewarm?.ready || 0) === Number(prewarm?.eligible || 0);
  const prewarmTerminal = Number(prewarm?.eligible || 0) > 0
    && Number(prewarm?.ready || 0) < Number(prewarm?.eligible || 0)
    && Number(prewarm?.terminal || 0) >= Number(prewarm?.eligible || 0) - Number(prewarm?.ready || 0);
  if (!analysisStates.length) {
    if (freshTelemetry) return 'ONLINE';
    if (edgeWaking) return 'WAKING';
    if (prewarmWarming || (startupWakeRequested && !prewarm)) return 'WARMING';
    if (prewarmTerminal) return 'UNAVAILABLE';
    return prewarmReady ? 'READY' : 'IDLE';
  }
  const anyActive = analysisStates.some((state) => state.intent === 'ACTIVE');
  const anyWaking = analysisStates.some((state) => state.intent === 'WAKING') || edgeWaking;
  // Current-session telemetry is definitive proof the edge is online, and
  // must outrank a stale local wake timer or a delayed lifecycle intent.
  if (analysisStates.some((state) => state.hasFreshCurrentTelemetry)) return 'ONLINE';
  if (!anyActive && !anyWaking) {
    if (prewarmWarming || (startupWakeRequested && !prewarm)) return 'WARMING';
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
