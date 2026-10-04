export function sourceStateFromCurrentVideo(state) {
  if (!state?.available) return null;
  const lifecycle = String(state.analysis_state || '').toUpperCase();
  const runState = lifecycle || (state.scenario === 'normal' ? 'ACTIVE' : 'PAUSED');
  const lifecycleFields = {
    restoring: false,
    analysisState: lifecycle || runState,
    analysisGeneration: Number.isFinite(Number(state.analysis_generation)) ? Number(state.analysis_generation) : 0,
    scenario: String(state.scenario || 'paused').toLowerCase(),
  };
  if (state.source_mode === 'bundled') {
    return {
      sourceMode: 'bundled',
      sourceId: null,
      sourceName: state.source_name || 'BUNDLED CLOUD DEMO',
      runState,
      ...lifecycleFields,
    };
  }
  if (state.source_mode === 'durable' && state.session_id) {
    return {
      sourceMode: 'durable',
      sourceId: state.session_id,
      sourceName: state.source_name || 'Configured video source',
      latestAnalysisSessionId: state.latest_analysis_session_id || null,
      runState,
      ...lifecycleFields,
    };
  }
  return null;
}

// Durable source identity comes only from GET /video/current.  Browser
// storage may remember layout choices, but must never choose a cloud source.
export function restoringSourceState() {
  return { restoring: true, runState: 'RESTORING' };
}

export function lifecycleAction(sourceState) {
  const lifecycle = String(sourceState?.analysisState || sourceState?.runState || '').toUpperCase();
  // A stale WAKING/paused record is repaired by START / ANALYZE. STOP would
  // merely preserve the contradictory control pair and never wake the worker.
  if (sourceState?.scenario && sourceState.scenario !== 'normal' && ['WAKING', 'ACTIVE'].includes(lifecycle)) return 'START';
  return ['WAKING', 'ACTIVE', 'LIVE'].includes(lifecycle) ? 'STOP' : 'START';
}

// A successful replay changes lifecycle fields only.  Source identity is an
// invariant across replay and preview hydration.
export function applyReplayResult(sourceState, result) {
  if (!sourceState) return sourceState;
  return {
    ...sourceState,
    restoring: false,
    runState: String(result?.analysis_state || 'WAKING').toUpperCase(),
    analysisState: String(result?.analysis_state || 'WAKING').toUpperCase(),
    scenario: String(result?.scenario || 'normal').toLowerCase(),
    latestAnalysisSessionId: null,
    analysisGeneration: Number.isFinite(Number(result?.analysis_generation))
      ? Number(result.analysis_generation)
      : sourceState.analysisGeneration,
  };
}

export function bundledSourceState(scenario = 'paused') {
  return {
    sourceMode: 'bundled',
    sourceId: null,
    sourceName: 'BUNDLED CLOUD DEMO',
    runState: scenario === 'normal' ? 'ACTIVE' : 'PAUSED',
  };
}

export function scenarioAction(cameraId, sourceState, scenario, wakeEdge = false) {
  if (!cameraId || !sourceState?.sourceMode) return null;
  const payload = {
    camera_id: cameraId,
    source_mode: sourceState.sourceMode,
    scenario,
    video_time: 0,
  };
  if (wakeEdge) payload.wake_edge = true;
  if (scenario === 'paused' || scenario === 'stopped') payload.control_action = 'stop';
  if (sourceState.sourceMode === 'durable') {
    if (!sourceState.sourceId) return null;
    payload.video_session_id = sourceState.sourceId;
  }
  return payload;
}

export function durableHeartbeat(cameraId, sourceState, sessionId, videoTime) {
  if (
    !cameraId
    || sourceState?.sourceMode !== 'durable'
    || !sourceState.sourceId
    || sessionId !== sourceState.sourceId
  ) return null;
  return {
    camera_id: cameraId,
    source_mode: 'durable',
    video_session_id: sourceState.sourceId,
    video_time: Number(videoTime) || 0,
  };
}
