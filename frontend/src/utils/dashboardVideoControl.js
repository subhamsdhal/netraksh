export function sourceStateFromCurrentVideo(state) {
  if (!state?.available) return null;
  if (state.source_mode === 'bundled') {
    return {
      sourceMode: 'bundled',
      sourceId: null,
      sourceName: state.source_name || 'BUNDLED CLOUD DEMO',
      runState: state.scenario === 'normal' ? 'ACTIVE' : 'PAUSED',
    };
  }
  if (state.source_mode === 'durable' && state.session_id) {
    return {
      sourceMode: 'durable',
      sourceId: state.session_id,
      sourceName: state.source_name || 'Configured video source',
      runState: state.scenario === 'normal' ? 'ACTIVE' : 'PAUSED',
    };
  }
  return null;
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
