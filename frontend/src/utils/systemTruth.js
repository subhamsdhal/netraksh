export function deriveSyncState({ isConnected, queued = 0, failed = 0, hasActivity = false } = {}) {
  if (!isConnected) return 'DISCONNECTED';
  if (Number(failed) > 0) return 'FAILED';
  if (Number(queued) > 0) return 'BUFFERING';
  return hasActivity ? 'CURRENT' : 'IDLE';
}

export function deriveCameraOperationalState({ nodeStatus, sourceState, telemetry, now = Date.now() } = {}) {
  const node = !nodeStatus ? 'NOT REPORTED' : nodeStatus === 'READY' ? 'READY' : nodeStatus === 'TIMEOUT' ? 'UNAVAILABLE' : 'WARMING';
  const source = sourceState?.sourceMode ? (sourceState.restoring ? 'LOADING' : 'READY') : 'NOT LOADED';
  const lifecycle = String(sourceState?.analysisState || sourceState?.runState || '').toUpperCase();
  const observed = Number(telemetry?.timestamp || telemetry?.processed_timestamp || 0);
  const ageMs = observed > 1e12 ? now - observed : observed > 0 ? now - (observed * 1000) : Infinity;
  const telemetryState = !telemetry ? 'NONE' : ageMs <= 30_000 ? 'LIVE' : 'STALE';
  const analysis = ['STARTING', 'WAKING'].includes(lifecycle)
    ? 'STARTING'
    : ['RUNNING', 'LIVE', 'ACTIVE'].includes(lifecycle)
      ? 'LIVE'
      : lifecycle === 'COMPLETED'
        ? 'COMPLETED'
        : lifecycle === 'FAILED'
          ? 'FAILED'
          : telemetryState === 'LIVE' ? 'LIVE' : 'IDLE';
  return { node, source, analysis, telemetry: telemetryState };
}

export function capabilityLabel(available, yes, no = 'NOT AVAILABLE') {
  return available === true ? yes : available === false ? no : 'NOT REPORTED';
}

const HEALTH_FRESHNESS_MS = 30_000;

export function formatTelemetryAge(ageMs) {
  const numericAge = Number(ageMs);
  if (!Number.isFinite(numericAge)) return null;
  const seconds = Math.floor(Math.max(0, numericAge) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function cameraHealthPresentation(camera = {}, now = Date.now()) {
  const hasSample = [camera.health_state, camera.health_reason, camera.fps_actual, camera.last_health_check]
    .some((value) => value !== null && value !== undefined && value !== '');
  if (!hasSample) {
    return { health: 'NOT REPORTED', fps: 'N/A', reason: 'N/A', sample: 'Never', stale: false };
  }

  const measuredAt = Date.parse(camera.last_health_check);
  const validTimestamp = Number.isFinite(measuredAt);
  const ageMs = validTimestamp ? Math.max(0, now - measuredAt) : null;
  const current = validTimestamp && ageMs <= HEALTH_FRESHNESS_MS;
  const measuredHealth = camera.health_state || 'NOT REPORTED';
  const numericFps = Number(camera.fps_actual);
  const measuredFps = Number.isFinite(numericFps) ? numericFps.toFixed(2) : null;
  const measuredReason = camera.health_reason || 'N/A';

  if (current) {
    return {
      health: measuredHealth,
      fps: measuredFps ?? 'N/A',
      reason: measuredReason,
      sample: formatTelemetryAge(ageMs),
      stale: false,
    };
  }

  const absoluteTimestamp = validTimestamp
    ? new Date(measuredAt).toISOString().replace('T', ' ').replace('.000Z', ' UTC').replace('Z', ' UTC')
    : 'Invalid timestamp';
  return {
    health: `STALE · LAST MEASURED ${measuredHealth}`,
    fps: 'N/A CURRENT',
    fpsDetail: measuredFps ? `Last measured: ${measuredFps} FPS` : 'Last measured: N/A',
    reason: `Last measured: ${measuredReason}`,
    sample: validTimestamp ? `${formatTelemetryAge(ageMs)} · ${absoluteTimestamp}` : `${absoluteTimestamp} · STALE`,
    stale: true,
  };
}
