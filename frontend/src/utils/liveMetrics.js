import { telemetryStatusAt } from './dashboardScope';

export function deriveGlobalEdgeStatus({ analysisStates = [], lastTelemetryAt = 0, edgeWakeUntil = 0, now = Date.now() }) {
  const freshTelemetry = Number(lastTelemetryAt) > 0 && now - Number(lastTelemetryAt) < 30_000;
  const edgeWaking = Number(edgeWakeUntil) > now;
  if (!analysisStates.length) return freshTelemetry ? 'ONLINE' : edgeWaking ? 'WAKING' : 'OFFLINE';
  const anyActive = analysisStates.some((state) => state.intent === 'ACTIVE');
  const anyWaking = analysisStates.some((state) => state.intent === 'WAKING') || edgeWaking;
  // Current-session telemetry is definitive proof the edge is online, and
  // must outrank a stale local wake timer or a delayed lifecycle intent.
  if (freshTelemetry && (anyActive || anyWaking)) return 'ONLINE';
  if (!anyActive && !anyWaking) return 'IDLE';
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
