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
