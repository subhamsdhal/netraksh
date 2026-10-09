export function sourceStateFromCurrentVideo(state) {
  if (!state?.available) return null;
  const lifecycle = String(state.analysis_state || '').toUpperCase();
  const runState = lifecycle || (state.scenario === 'normal' ? 'ACTIVE' : 'PAUSED');
  const lifecycleFields = {
    restoring: false,
    analysisState: lifecycle || runState,
    analysisGeneration: Number.isFinite(Number(state.analysis_generation)) ? Number(state.analysis_generation) : 0,
    sourceGeneration: Number.isFinite(Number(state.source_generation)) ? Number(state.source_generation) : null,
    uploadIntentId: state.upload_intent_id || null,
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

// Only a terminal backend control response for the same exact source and
// generation may settle a locally live card. Old responses cannot reclaim a
// newer generation or change another camera's presentation.
export function reconcileTerminalCameraSource(current, response) {
  const terminal = String(response?.analysis_state || '').toUpperCase();
  if (!['INTERRUPTED', 'COMPLETED'].includes(terminal)
      || current?.sourceMode !== 'durable'
      || response?.session_id !== current.sourceId
      || Number(response?.analysis_generation) !== Number(current.analysisGeneration)) return current;
  if (current.analysisState === terminal && current.runState === terminal) return current;
  return {
    ...current,
    analysisState: terminal,
    runState: terminal,
    scenario: String(response.scenario || 'paused').toLowerCase(),
    latestAnalysisSessionId: response.latest_analysis_session_id || current.latestAnalysisSessionId || null,
  };
}

export async function fetchWithTimeout(fetcher, path, timeoutMs = 5000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetcher(path, { signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

// Preparation state is an optimization for an in-flight upload, not source
// authority. A transient failure here must not prevent the caller from asking
// GET /video/current for the authoritative durable source.
export async function fetchPreparationForRestore(fetcher, path, onDiagnostic = () => {}) {
  try {
    const response = await fetchWithTimeout(fetcher, path, 5000);
    onDiagnostic({ stage: 'PREPARATION_CHECK_COMPLETE', http_status: response.status });
    return response;
  } catch (error) {
    if (error?.name === 'AbortError') {
      onDiagnostic({ stage: 'PREPARATION_CHECK_TIMEOUT', timeout_ms: 5000 });
    } else {
      onDiagnostic({ stage: 'PREPARATION_CHECK_ERROR', preparation_error_name: error?.name || 'Error' });
    }
    return null;
  }
}

export async function fetchReadOnlyWithRetry(
  fetcher,
  path,
  { timeoutMs = 10000, attempts = 3, retryDelayMs = 350, onRetry = () => {} } = {},
) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetchWithTimeout(fetcher, path, timeoutMs);
      if (response.status < 500 || attempt === attempts) return response;
      onRetry({ attempt, http_status: response.status });
    } catch (error) {
      lastError = error;
      if (attempt === attempts) throw error;
      onRetry({ attempt, error_name: error?.name || 'Error' });
    }
    await new Promise(resolve => setTimeout(resolve, retryDelayMs * attempt));
  }
  throw lastError || new Error('Read-only request did not complete');
}

export function sourceStateFromPreparation(job) {
  if (!job?.available || !job?.preparation_job_id || !job?.camera_id) return null;
  const preparationState = String(job.state || 'UPLOADED').toUpperCase();
  const analysisState = String(job.analysis_state || '').toUpperCase();
  const ready = preparationState === 'READY';
  return {
    restoring: false,
    sourceMode: 'durable',
    sourceId: job.session_id || job.preparation_job_id,
    sourceName: job.source_name || 'Uploaded video',
    runState: ready && analysisState ? analysisState : preparationState,
    analysisState: ready && analysisState ? analysisState : preparationState,
    analysisGeneration: Number.isFinite(Number(job.analysis_generation)) ? Number(job.analysis_generation) : 0,
    sourceGeneration: Number.isFinite(Number(job.source_generation)) ? Number(job.source_generation) : null,
    uploadIntentId: job.upload_intent_id || job.preparation_job_id,
    preparationJobId: job.preparation_job_id,
    preparationState,
    scenario: ready ? 'normal' : 'paused',
  };
}

export function lifecycleAction(sourceState) {
  const lifecycle = String(sourceState?.analysisState || sourceState?.runState || '').toUpperCase();
  // A stale WAKING/paused record is repaired by START / ANALYZE. STOP would
  // merely preserve the contradictory control pair and never wake the worker.
  if (sourceState?.scenario && sourceState.scenario !== 'normal' && ['WAKING', 'ACTIVE'].includes(lifecycle)) return 'START';
  return ['WAKING', 'ACTIVE', 'LIVE'].includes(lifecycle) ? 'STOP' : 'START';
}

export function analysisLifecyclePresentation(sourceState, mediaState = {}, controlPending = false, options = {}) {
  const lifecycle = String(sourceState?.analysisState || sourceState?.runState || '').toUpperCase();
  const uploadStage = String(mediaState?.uploadStage || '').toUpperCase();

  if (lifecycle === 'UPLOADED' || uploadStage === 'UPLOADED') {
    return { label: 'UPLOAD COMPLETE', badge: 'UPLOADED', tone: 'active', retry: false };
  }
  if (lifecycle === 'VALIDATING' || uploadStage === 'VALIDATING') {
    return { label: 'VALIDATING VIDEO...', badge: 'VALIDATING', tone: 'active', retry: false };
  }
  if (['PREPARING', 'QUEUED_FOR_NORMALIZATION', 'NORMALIZING'].includes(lifecycle)
    || ['PREPARING', 'NORMALIZING'].includes(uploadStage)) {
    return { label: 'PREPARING VIDEO...', badge: 'PREPARING', tone: 'active', retry: false };
  }
  if (lifecycle === 'STORING' || uploadStage === 'STORING') {
    return { label: 'STORING VIDEO...', badge: 'STORING', tone: 'active', retry: false };
  }
  if (['FINALIZING', 'ACTIVATING'].includes(lifecycle) || ['FINALIZING', 'ACTIVATING'].includes(uploadStage)) {
    return { label: 'FINALIZING VIDEO...', badge: 'FINALIZING', tone: 'active', retry: false };
  }
  if (mediaState?.isUploading || ['UPLOADING', 'SELECTING'].includes(lifecycle) || uploadStage === 'UPLOADING') {
    return { label: 'UPLOADING...', badge: 'UPLOADING', tone: 'active', retry: false };
  }
  if (mediaState?.analysisStartFailed) {
    return { label: 'ANALYSIS START FAILED', badge: 'START FAILED', tone: 'failed', retry: true };
  }
  if (controlPending || lifecycle === 'STARTING') {
    return { label: 'STARTING ANALYSIS...', badge: 'STARTING', tone: 'active', retry: false };
  }
  if (lifecycle === 'WAKING') {
    return { label: 'WAKING AI WORKER...', badge: 'WAKING', tone: 'active', retry: false };
  }
  if (['ACTIVE', 'LIVE', 'RUNNING'].includes(lifecycle)) {
    return { label: 'ANALYZING...', badge: 'ONLINE / ANALYZING', tone: 'active', retry: false };
  }
  if (lifecycle === 'STOPPING') {
    return { label: 'FINISHING ANALYSIS...', badge: 'FINISHING', tone: 'active', retry: false };
  }
  if (lifecycle === 'COMPLETED') {
    return { label: 'ANALYSIS COMPLETED', badge: 'COMPLETED', tone: 'completed', retry: false };
  }
  if (lifecycle === 'INTERRUPTED') {
    if (options.hideInterrupted) {
      return { label: 'SOURCE READY', badge: 'SOURCE READY', tone: 'ready', retry: false };
    }
    return { label: 'ANALYSIS INTERRUPTED', badge: 'INTERRUPTED', tone: 'failed', retry: false };
  }
  if (['FAILED', 'ERROR'].includes(lifecycle) || uploadStage === 'ERROR') {
    return { label: 'ANALYSIS FAILED', badge: 'FAILED', tone: 'failed', retry: false };
  }
  if (sourceState?.restoring) {
    return { label: 'RESTORING SOURCE...', badge: 'RESTORING', tone: 'active', retry: false };
  }
  if (sourceState?.sourceMode) {
    return { label: 'SOURCE READY', badge: 'SOURCE READY', tone: 'ready', retry: false };
  }
  return { label: 'ADD / REPLACE VIDEO', badge: 'IDLE', tone: 'ready', retry: false };
}

export function canReanalyzeSource(cameraId, sourceState) {
  return ['cam-border-01', 'cam-checkpoint-01'].includes(cameraId)
    && sourceState?.sourceMode === 'durable'
    && Boolean(sourceState.sourceId)
    && ['COMPLETED', 'INTERRUPTED'].includes(String(sourceState.analysisState || sourceState.runState || '').toUpperCase());
}

export function reanalyzeRequestPayload(cameraId, sourceState, requestId) {
  if (!canReanalyzeSource(cameraId, sourceState) || !requestId) return null;
  return {
    camera_id: cameraId,
    video_session_id: sourceState.sourceId,
    request_id: requestId,
  };
}

// Auto-start authority exists only inside the browser event that completed a
// new upload. Restored/polled READY sources never have an uploadRequestId, so
// they cannot accidentally create a run after refresh or reconnect.
export function uploadAutoStartIdentity(cameraId, sourceState, uploadRequestId) {
  const lifecycle = String(sourceState?.analysisState || sourceState?.runState || '').toUpperCase();
  if (
    !cameraId
    || !uploadRequestId
    || sourceState?.sourceMode !== 'durable'
    || !sourceState?.sourceId
    || lifecycle !== 'READY'
  ) return null;
  return `${cameraId}:${sourceState.sourceId}:${uploadRequestId}`;
}

export function claimUploadAutoStart(claims, identity) {
  if (!claims || !identity || claims.has(identity)) return false;
  claims.add(identity);
  return true;
}

export async function runUploadAutoStart({ claims, cameraId, sourceState, uploadRequestId, start }) {
  const identity = uploadAutoStartIdentity(cameraId, sourceState, uploadRequestId);
  if (!claimUploadAutoStart(claims, identity)) return { attempted: false, duplicate: Boolean(identity) };
  const outcome = await start(cameraId, sourceState, 'new-upload');
  return { attempted: true, identity, outcome };
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
