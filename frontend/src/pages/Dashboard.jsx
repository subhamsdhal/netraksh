import { useState, useEffect, useRef, useMemo } from 'react';
import { ShieldCheck, HelpCircle, ShieldAlert, CheckCircle, GitMerge } from 'lucide-react';
import VideoFeed from '../components/VideoFeed';
import useWebSocket from '../hooks/useWebSocket';
import useDemoScenario from '../hooks/useDemoScenario';
import { WS_URL, BACKEND_URL, authFetch } from '../services/auth';
import useAuth from '../hooks/useAuth';
import { parseUtc } from '../utils/time';
import { MAX_VISIBLE_CAMERAS, selectCameraSlots, cameraDisplayMetadata } from '../utils/cameraSlots';
import { cameraHealthPresentation, capabilityLabel, deriveCameraOperationalState, formatTelemetryAge } from '../utils/systemTruth';
import useStartupReadiness from '../hooks/useStartupReadiness';
import { analysisSessionIdForSource, deriveDashboardMode, filterLiveEvents, selectReliabilityEvent, latestEventForSession, telemetryStatusAt, formatLatestEvent, isActiveTelemetry, telemetryForSource, lifecycleStatus } from '../utils/dashboardScope';
import { updateCameraMediaState } from '../utils/cameraMediaState';
import { applyReplayResult, lifecycleAction, restoringSourceState, scenarioAction, sourceStateFromCurrentVideo } from '../utils/dashboardVideoControl';
import { processingFpsForTelemetry, sourceFpsForTelemetry } from '../utils/liveMetrics';

// Reads structured scores from the event instead of string-parsing the reason.
function parseDecisionReason(ev) {
  if (!ev) return null;
  if (ev.decision_state === 'ABSTAIN') {
    return { kind: 'abstain', healthReason: ev.decision_reason || 'unknown' };
  }

  // If the event doesn't have structured scores yet (legacy data), fallback to string parsing
  if (ev.score_r == null && ev.decision_reason) {
    const rMatch = ev.decision_reason.match(/R=([\d.]+)\s*[<>]=?\s*([\d.]+)/);
    const factorMatch = ev.decision_reason.match(/D=([\d.]+),T=([\d.]+),S=([\d.]+),H=([\d.]+)/);
    if (!rMatch || !factorMatch) return null;
    return {
      kind: 'scored',
      r: parseFloat(rMatch[1]),
      threshold: parseFloat(rMatch[2]),
      aboveThreshold: ev.decision_reason.includes('R_ABOVE_THRESHOLD'),
      degraded: ev.decision_reason.includes('DEGRADED_CAMERA'),
      d: parseFloat(factorMatch[1]),
      t: parseFloat(factorMatch[2]),
      s: parseFloat(factorMatch[3]),
      h: parseFloat(factorMatch[4]),
    };
  }

  let threshold = null;
  if (ev.decision_reason) {
    const rMatch = ev.decision_reason.match(/R=[\d.]+\s*[<>]=?\s*([\d.]+)/);
    if (rMatch) threshold = parseFloat(rMatch[1]);
  }

  return {
    kind: 'scored',
    r: ev.score_r ?? null,
    threshold: threshold,
    aboveThreshold: ev.decision_state === 'DETECTED',
    degraded: ev.camera_health_state === 'DEGRADED',
    d: ev.score_d ?? null,
    t: ev.score_t ?? null,
    s: ev.score_s ?? null,
    h: ev.score_h ?? null,
  };
}

const SCENE_CONDITION_LABELS = {
  CLEAR_DAY: 'Clear Day',
  LOW_LIGHT_NIGHT: 'Night / Low-Light',
  FOG_RAIN: 'Fog / Rain',
  GLARE: 'Glare',
};

const DECISION_META = {
  DETECTED: { label: 'DETECTED', icon: ShieldCheck, colorClass: 'text-ok border-ok bg-[rgba(74,222,128,0.1)] glow-ok' },
  UNCERTAIN: { label: 'UNCERTAIN', icon: HelpCircle, colorClass: 'text-warning border-warning bg-[rgba(251,191,36,0.1)]' },
  ABSTAIN: { label: 'ABSTAIN', icon: ShieldAlert, colorClass: 'text-danger border-danger bg-[rgba(248,113,113,0.1)]' },
};

// Builds the actual plain-English explanation from the same parsed
// decision_reason data the Reliability Decision panel already displays —
// "WHY THIS ALERT?" used to be a <span> with no onClick at all, styled to
// look like a clickable button (border, padding, hover-implying color)
// but doing nothing. Rather than just stripping that affordance, this
// wires it to something real: the exact factors that produced the
// decision, in one place, instead of requiring the viewer to read four
// separate numbers out of the Gate 3 grid themselves.
function explainDecision(parsed) {
  if (!parsed) return null;
  if (parsed.kind === 'abstain') {
    return `Camera health is FAILED (${parsed.healthReason}) — Gate 1's hard override abstained before any reliability score was computed. This is not a scoring decision; a failed camera is never trusted regardless of what a detector reports.`;
  }
  const factorNote = (label, value) => `${label}=${value == null ? 'NOT REPORTED' : value.toFixed(2)}`;
  const reportedR = parsed.r == null ? 'NOT REPORTED' : parsed.r.toFixed(3);
  const reportedThreshold = parsed.threshold == null ? 'THRESHOLD NOT REPORTED' : parsed.threshold.toFixed(3);
  const verdict = `The event recorded ${reportedR} for R and ${reportedThreshold}; its authoritative decision was ${parsed.aboveThreshold ? 'DETECTED' : 'UNCERTAIN'}`;
  const degradedNote = parsed.degraded ? ' The camera was in a DEGRADED state at the time, which is reflected in a lower H factor above.' : '';
  return `${verdict}, from: ${factorNote('Detection confidence (D)', parsed.d)}, ${factorNote('Temporal consistency (T)', parsed.t)}, ${factorNote('Scene clarity (S)', parsed.s)}, ${factorNote('Camera health (H)', parsed.h)}.${degradedNote}`;
}

export default function Dashboard() {
  const startupReadiness = useStartupReadiness();
  const {
    events, health, metrics, liveTracks, cameras, isConnected,
    connectionStatus, resetCameraContext, refreshEventsForContext, refreshTelemetryForContext,
  } = useWebSocket(WS_URL);
  const { scenario: demoScenario } = useDemoScenario();
  const [latestEvent, setLatestEvent] = useState(null);
  const [showWhy, setShowWhy] = useState(false);
  const { role } = useAuth();
  const canUpload = role && (role.toUpperCase() === 'ADMIN' || role.toUpperCase() === 'OPERATOR');

  // Every source-specific value is keyed by camera. A single media URL or
  // session shared by both cards lets one upload overwrite the other.
  const [cameraMedia, setCameraMedia] = useState({});
  const cameraMediaRef = useRef(cameraMedia);
  const [selectedCameraId, setSelectedCameraId] = useState('');
  // Source/session identity is control-plane state.  Never seed it from a
  // previous browser session: a stale localStorage value can otherwise render
  // a different uploaded file before GET /video/current has answered.
  const [slotSources, setSlotSources] = useState({});
  const [eventCameraFilter, setEventCameraFilter] = useState('ALL');
  const [reliabilityCameraId, setReliabilityCameraId] = useState(null);
  const [correlationState, setCorrelationState] = useState(null);
  const [runSummaries, setRunSummaries] = useState({});
  const [runSummaryLoading, setRunSummaryLoading] = useState({});
  const [cameraSlots, setCameraSlots] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('netraksh.cameraSlots') || localStorage.getItem('netraksh.demoCameraSlots') || '[]');
      return Array.isArray(saved) ? saved.slice(0, MAX_VISIBLE_CAMERAS) : [];
    } catch (_) { return []; }
  });
  const [now, setNow] = useState(Date.now());
  const [backendStatus, setBackendStatus] = useState('CHECKING');
  const [controlRequests, setControlRequests] = useState({});
  const fileInputRefs = useRef({});
  const wakeTimeoutsRef = useRef({});
  // This is a request lifecycle, not a mount latch.  A cold backend must not
  // consume the only prewarm attempt before it can accept the POST.
  const prewarmRequestStateRef = useRef('IDLE');

  // Remove the retired source cache once.  It contains no authority and is
  // deliberately never read; camera slot assignment is independent.
  useEffect(() => { localStorage.removeItem('netraksh.slotSources'); }, []);

  const updateCameraMedia = (cameraId, patch) => {
    if (!cameraId) return;
    setCameraMedia((current) => updateCameraMediaState(current, cameraId, patch));
  };

  const requestScenario = async (cameraId, payload, onPhase = () => {}) => {
    if (!payload) return { ok: false, status: null, error: 'CONTROL SOURCE SESSION MISSING — REFRESH SOURCE STATE' };
    const previousSourceState = cameraId ? slotSources[cameraId] : null;
    const previousMediaState = cameraId ? cameraMediaRef.current[cameraId] : null;
    try {
      onPhase('CONTROL POST DISPATCHED');
      const response = await authFetch('/api/dashboard/video/scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      onPhase(`CONTROL RESPONSE ${response.status}`);
      if (!response.ok) {
        const error = new Error(`START FAILED — HTTP ${response.status}${result.detail ? ` · ${result.detail}` : ''}`);
        error.status = response.status;
        throw error;
      }
      if (cameraId && payload.scenario === 'normal') {
        // The POST is the transaction boundary.  Do not claim WAKING, change
        // a filename, or alter a session until the backend accepted this exact
        // durable session and supplied its new lifecycle generation.
        resetCameraContext(cameraId);
        setRunSummaries(current => ({ ...current, [cameraId]: null }));
        setSlotSources((current) => ({
          ...current,
          [cameraId]: applyReplayResult(current[cameraId] || previousSourceState, result),
        }));
        updateCameraMedia(cameraId, {
          edgeStatus: ['ready', 'waking'].includes(String(result.edge_status || '').toLowerCase()) ? 'WAKING' : 'WAITING',
          isUploading: false,
          uploadError: null,
        });
        window.dispatchEvent(new CustomEvent('netraksh:edge-wake', { detail: { cameraId, status: 'WAKING' } }));
        clearTimeout(wakeTimeoutsRef.current[cameraId]);
        wakeTimeoutsRef.current[cameraId] = setTimeout(() => {
          updateCameraMedia(cameraId, { edgeStatus: 'TIMEOUT', uploadError: 'AI WORKER COLD START TIMED OUT — RETRY ANALYSIS' });
        }, 305_000);
      }
      return { ok: true, status: response.status, result };
    } catch (error) {
      const status = Number.isFinite(error?.status) ? error.status : null;
      onPhase(status ? `CONTROL FAILED HTTP ${status}` : 'CONTROL NETWORK FAILED');
      if (cameraId) {
        // Failed controls are fully transactional: restore the exact prior
        // lifecycle and media state instead of leaving a fake WAKING card.
        setSlotSources((current) => ({ ...current, [cameraId]: previousSourceState }));
        updateCameraMedia(cameraId, {
          ...(previousMediaState || {}),
          uploadError: error?.message || 'START FAILED — CONTROL REQUEST DID NOT COMPLETE',
        });
      }
      return { ok: false, status, error: error?.message || 'START FAILED — CONTROL REQUEST DID NOT COMPLETE' };
    }
  };

  const handleStartAnalysis = async (cameraId, sourceState) => {
    if (!cameraId || !sourceState) {
      if (cameraId) updateCameraMedia(cameraId, { uploadError: 'CONTROL SOURCE SESSION MISSING — REFRESH SOURCE STATE', controlStatus: 'CONTROL PAYLOAD FAILED' });
      return;
    }
    const payload = scenarioAction(cameraId, sourceState, 'normal', true);
    if (!payload) {
      updateCameraMedia(cameraId, { uploadError: 'CONTROL SOURCE SESSION MISSING — REFRESH SOURCE STATE', controlStatus: 'CONTROL PAYLOAD FAILED' });
      return;
    }
    setControlRequests((current) => ({ ...current, [cameraId]: true }));
    const safeDetails = {
      camera_id: cameraId,
      source_mode: payload.source_mode,
      session_prefix: payload.video_session_id ? String(payload.video_session_id).slice(0, 8) : null,
      scenario: payload.scenario,
      wake_edge: payload.wake_edge === true,
    };
    console.info('[Dashboard] START CLICKED', safeDetails);
    updateCameraMedia(cameraId, { uploadError: null, controlStatus: 'CONTROL PAYLOAD READY' });
    const outcome = await requestScenario(cameraId, payload, (phase) => {
      console.info('[Dashboard] start control', { ...safeDetails, phase });
      updateCameraMedia(cameraId, { controlStatus: phase });
    });
    if (!outcome.ok) {
      updateCameraMedia(cameraId, { uploadError: outcome.error, controlStatus: outcome.status ? `CONTROL FAILED HTTP ${outcome.status}` : 'CONTROL NETWORK FAILED' });
    }
    setControlRequests((current) => ({ ...current, [cameraId]: false }));
  };

  useEffect(() => {
    cameraMediaRef.current = cameraMedia;
  }, [cameraMedia]);

  useEffect(() => () => {
    Object.values(cameraMediaRef.current).forEach((state) => {
      if (state?.mediaUrl?.startsWith('blob:')) URL.revokeObjectURL(state.mediaUrl);
    });
  }, []);

  // One authenticated, backend-ready dashboard mount may request a bounded
  // authoritative prewarm. Direct startup wakes happen before this, but only
  // this authenticated API exposes readiness truth and bounded retries.
  useEffect(() => {
    if (!canUpload || backendStatus !== 'HEALTHY' || prewarmRequestStateRef.current === 'ACCEPTED') return undefined;
    if (prewarmRequestStateRef.current === 'IN_FLIGHT') return undefined;
    prewarmRequestStateRef.current = 'IN_FLIGHT';
    let cancelled = false;
    let pollTimer = null;
    let retryTimer = null;
    let attempts = 0;
    const deadline = Date.now() + 305_000;
    const publish = (payload) => {
      if (!cancelled && payload) window.dispatchEvent(new CustomEvent('netraksh:edge-prewarm', { detail: payload }));
    };
    const fetchStatus = async () => {
      try {
        const response = await authFetch('/api/dashboard/edge/prewarm/status');
        if (!response.ok || cancelled) return null;
        const payload = await response.json();
        publish(payload);
        return payload;
      } catch (_) { return null; }
    };
    const shouldPoll = (payload) => {
      const eligible = Number(payload?.eligible || 0);
      const ready = Number(payload?.ready || 0);
      const terminal = Number(payload?.terminal || 0);
      return eligible > 0 && ready < eligible && ready + terminal < eligible;
    };
    const pollWhilePending = async () => {
      const payload = await fetchStatus();
      if (!payload || cancelled) return;
      if (shouldPoll(payload) && Date.now() < deadline) {
        pollTimer = window.setTimeout(pollWhilePending, 2_000);
      }
    };
    const requestPrewarm = async () => {
      attempts += 1;
      try {
        const response = await authFetch('/api/dashboard/edge/prewarm', { method: 'POST' });
        if (!response.ok || cancelled) {
          if (response.status !== 401 && response.status !== 403 && attempts < 3) {
            retryTimer = window.setTimeout(requestPrewarm, attempts * 750);
          } else if (!cancelled) prewarmRequestStateRef.current = 'IDLE';
          return;
        }
        const payload = await response.json();
        prewarmRequestStateRef.current = 'ACCEPTED';
        publish(payload);
        // An accepted request must always obtain at least one cache-only
        // status read when any eligible worker is not ready yet.
        if (shouldPoll(payload)) pollTimer = window.setTimeout(pollWhilePending, 2_000);
      } catch (_) {
        if (!cancelled && attempts < 3) retryTimer = window.setTimeout(requestPrewarm, attempts * 750);
        else if (!cancelled) prewarmRequestStateRef.current = 'IDLE';
      }
    };
    requestPrewarm();
    return () => {
      cancelled = true;
      if (pollTimer) window.clearTimeout(pollTimer);
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [canUpload, backendStatus]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/ready`);
        if (mounted) setBackendStatus(response.ok ? 'HEALTHY' : 'UNAVAILABLE');
      } catch (_) {
        if (mounted) setBackendStatus('UNAVAILABLE');
      }
    };
    check();
    const id = setInterval(check, 10000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  const cameraIds = Array.from(new Set([
    // Saved slots are layout only.  Including them while a cold backend is
    // restoring lets the card say RESTORING rather than falsely "not
    // configured"; GET /video/current remains the source authority.
    ...cameraSlots,
    ...cameras.map(camera => camera.camera_id),
    ...Object.keys(liveTracks),
    ...Object.keys(metrics),
    ...events.map(event => event.camera_id).filter(Boolean),
  ]));
  const scopedLiveTracks = useMemo(() => Object.fromEntries(
    Object.entries(liveTracks).map(([cameraId, telemetry]) => [
      cameraId,
      telemetryForSource(telemetry, slotSources[cameraId], cameraId),
    ]),
  ), [liveTracks, slotSources]);
  const cameraModels = useMemo(() => cameraIds.map(cameraId => {
    const camera = cameras.find(item => item.camera_id === cameraId) || {};
    const rawName = String(camera.name || '').trim();
    const normalizedId = String(cameraId || '').replace(/[_-]+/g, ' ').trim();
    const parts = normalizedId.split(/\s+/).filter(Boolean);
    const formattedParts = parts.map((part) => {
      if (/^cam$/i.test(part)) return 'Camera';
      if (/^border$/i.test(part)) return 'Border';
      if (/^checkpoint$/i.test(part)) return 'Checkpoint';
      if (/^\d+$/.test(part)) return part.padStart(2, '0');
      return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
    });
    const friendlyFromId = formattedParts.includes('Camera')
      ? formattedParts.join(' ')
      : ['Camera', ...formattedParts].join(' ');
    const friendlyName = rawName && !/^unknown[-_]/i.test(rawName)
      ? rawName
      : friendlyFromId || 'Camera';
    const receivedAt = scopedLiveTracks[cameraId]?.timestamp;
    const status = lifecycleStatus(slotSources[cameraId], scopedLiveTracks[cameraId], now);
    return {
      cameraId,
      friendlyName,
      location: camera.location || 'Location not registered',
      displayId: cameraId.toUpperCase(),
      streamId: scopedLiveTracks[cameraId]?.stream_id || null,
      sourceType: 'EDGE CAMERA',
      status,
      lastSeen: receivedAt || null,
    };
  }), [cameraIds, cameras, scopedLiveTracks, slotSources, now]);
  const visibleCameraIds = useMemo(
    () => selectCameraSlots(cameraIds, cameraSlots),
    [cameraIds.join('|'), cameraSlots.join('|')],
  );
  const activeCameraIds = useMemo(() => visibleCameraIds.filter((id) => {
    return isActiveTelemetry(scopedLiveTracks[id], now);
  }), [visibleCameraIds.join('|'), scopedLiveTracks, now]);
  const configuredCameraIds = useMemo(() => visibleCameraIds.filter((id) => Boolean(slotSources[id]?.sourceMode)), [visibleCameraIds.join('|'), slotSources]);
  const cameraInventoryRestoring = backendStatus !== 'HEALTHY'
    || visibleCameraIds.filter(Boolean).some((cameraId) => slotSources[cameraId]?.restoring);
  useEffect(() => {
    const cameraStates = visibleCameraIds.filter(Boolean).map((cameraId) => {
      const telemetry = scopedLiveTracks[cameraId];
      const status = telemetryStatusAt(telemetry, now);
      const source = slotSources[cameraId];
      const ageMs = telemetry?.timestamp ? Math.max(0, now - telemetry.timestamp) : Infinity;
      const intent = status === 'COMPLETED'
        ? 'IDLE'
        : source?.runState === 'WAKING'
          ? 'WAKING'
          : status === 'LIVE' || status === 'STALE'
          ? 'ACTIVE'
          : 'IDLE';
      const sameSource = source?.sourceMode !== 'durable' || telemetry?.stream_id === source?.sourceId;
      const sameGeneration = source?.analysisGeneration == null
        || Number(telemetry?.analysis_generation) === Number(source.analysisGeneration);
      return { cameraId, intent, ageMs, hasFreshCurrentTelemetry: status === 'LIVE' && sameSource && sameGeneration };
    });
    window.dispatchEvent(new CustomEvent('netraksh:analysis-state', { detail: { cameraStates } }));
  }, [visibleCameraIds.join('|'), slotSources, scopedLiveTracks, now]);
  useEffect(() => {
    activeCameraIds.forEach((cameraId) => {
      window.dispatchEvent(new CustomEvent('netraksh:edge-wake', { detail: { cameraId, status: 'LIVE' } }));
      clearTimeout(wakeTimeoutsRef.current[cameraId]);
      delete wakeTimeoutsRef.current[cameraId];
    });
  }, [activeCameraIds.join('|')]);
  useEffect(() => {
    // A fresh packet from the current source/generation is authoritative over
    // an older browser control diagnostic.  Clear only diagnostics that this
    // successful lifecycle actually supersedes; a newly occurring error is
    // still rendered by requestScenario.
    visibleCameraIds.filter(Boolean).forEach((cameraId) => {
      const telemetry = scopedLiveTracks[cameraId];
      const source = slotSources[cameraId];
      if (!telemetry || !source) return;
      const sameSource = source.sourceMode !== 'durable' || telemetry.stream_id === source.sourceId;
      const sameGeneration = source.analysisGeneration == null
        || Number(telemetry.analysis_generation) === Number(source.analysisGeneration);
      if (!sameSource || !sameGeneration) return;
      const status = telemetryStatusAt(telemetry, now);
      if (!['LIVE', 'COMPLETED'].includes(status)) return;
      const media = cameraMediaRef.current[cameraId] || {};
      const staleDiagnostic = /CONTROL (PAYLOAD|NETWORK) FAILED|START FAILED|COLD START TIMED OUT/.test(
        `${media.controlStatus || ''} ${media.uploadError || ''}`,
      );
      if (staleDiagnostic) updateCameraMedia(cameraId, { controlStatus: null, uploadError: null });
    });
  }, [visibleCameraIds.join('|'), slotSources, scopedLiveTracks, now]);
  useEffect(() => {
    if (!activeCameraIds.length) return;
    setSlotSources((current) => {
      let changed = false;
      const next = { ...current };
      activeCameraIds.forEach((cameraId) => {
        const lifecycle = String(next[cameraId]?.analysisState || next[cameraId]?.runState || '').toUpperCase();
        // Historical packets are not a lifecycle command.  In particular,
        // they must never turn a COMPLETED source into STOP/LIVE.
        if (next[cameraId] && ['WAKING', 'ACTIVE', 'LIVE'].includes(lifecycle) && next[cameraId].runState !== 'LIVE') {
          next[cameraId] = { ...next[cameraId], runState: 'LIVE', analysisState: 'LIVE' };
          changed = true;
        }
      });
      return changed ? next : current;
    });
  }, [activeCameraIds.join('|')]);
  const dashboardMode = deriveDashboardMode(activeCameraIds);
  const reliabilityScopeCameraId = reliabilityCameraId && configuredCameraIds.includes(reliabilityCameraId)
    ? reliabilityCameraId : configuredCameraIds[0] || null;
  useEffect(() => {
    if (!cameraIds.length) return;
    setCameraSlots((current) => {
      // Keep persisted assignments while the inventory is arriving in
      // separate websocket batches. Reconcile defaults only when no slots
      // have been chosen yet; otherwise a one-camera first batch can replace
      // slot 1 with an empty value and lose the operator's assignment.
      if (current.length) return current;
      const next = selectCameraSlots(cameraIds, current);
      return JSON.stringify(current) === JSON.stringify(next) ? current : next;
    });
  }, [cameraIds.join('|')]);
  useEffect(() => {
    // Do not erase persisted demo slot assignments during the initial render
    // while the websocket camera inventory is still empty. Route changes
    // remount Dashboard, and writing [] here used to clear both configured
    // slots before the inventory could restore them.
    if (!cameraSlots.length) return;
    // Persist the operator's assignments, not only the cameras that have
    // arrived in this websocket batch. A route remount can briefly receive
    // one worker before the other; saving the filtered visible list there
    // silently dropped the missing slot.
    localStorage.setItem('netraksh.cameraSlots', JSON.stringify(cameraSlots));
    localStorage.removeItem('netraksh.demoCameraSlots');
    if (visibleCameraIds[0] && !visibleCameraIds.includes(selectedCameraId)) setSelectedCameraId(visibleCameraIds[0]);
  }, [cameraSlots.join('|'), visibleCameraIds.join('|')]);
  useEffect(() => {
    let mounted = true;
    setSlotSources((current) => {
      const next = { ...current };
      visibleCameraIds.filter(Boolean).forEach((cameraId) => { next[cameraId] = restoringSourceState(); });
      return next;
    });
    const restoreScopedSources = async () => {
      if (backendStatus !== 'HEALTHY') return;
      await Promise.all(visibleCameraIds.filter(Boolean).map(async (cameraId) => {
        let authoritativeResponse = false;
        try {
          const response = await authFetch(`/api/dashboard/video/current?camera_id=${encodeURIComponent(cameraId)}`);
          if (!response.ok || !mounted) return;
          authoritativeResponse = true;
          const state = await response.json();
          const restoredSource = sourceStateFromCurrentVideo(state);
          if (restoredSource) {
            // Commit backend authority before making the control available.
            setSlotSources((current) => ({ ...current, [cameraId]: restoredSource }));
            setCameraMedia((current) => {
              const previous = current[cameraId]?.mediaUrl;
              if (previous?.startsWith('blob:')) URL.revokeObjectURL(previous);
              return {
                ...current,
                [cameraId]: {
                  ...current[cameraId],
                  mediaUrl: null,
                  sessionId: restoredSource.sourceMode === 'durable' ? state.session_id : null,
                  playbackEnded: false,
                  uploadError: null,
                  isUploading: false,
                },
              };
            });
            if (state.preview_url) {
              const mediaResponse = await authFetch(state.preview_url);
              if (mediaResponse.ok) {
                const blobUrl = URL.createObjectURL(await mediaResponse.blob());
                setCameraMedia((current) => {
                  const previous = current[cameraId]?.mediaUrl;
                  if (previous?.startsWith('blob:')) URL.revokeObjectURL(previous);
                  return {
                    ...current,
                    [cameraId]: {
                      ...current[cameraId],
                      mediaUrl: blobUrl,
                      mediaType: 'video',
                      sessionId: state.session_id,
                      sessionStartTime: Date.now(),
                      playbackEnded: false,
                      uploadError: null,
                      isUploading: false,
                    },
                  };
                });
              } else if (restoredSource.sourceMode === 'durable') {
                // Preview transport is independent of durable activation. Do
                // not replace a valid cloud session with the bundled demo just
                // because a redirect/blob fetch was temporarily unavailable.
                setCameraMedia((current) => ({
                  ...current,
                  [cameraId]: {
                    ...current[cameraId],
                    mediaUrl: null,
                    sessionId: state.session_id,
                    uploadError: 'PREVIEW LOAD FAILED — VIDEO IS STILL STORED',
                    isUploading: false,
                  },
                }));
              }
            }
          } else {
            setSlotSources((current) => ({ ...current, [cameraId]: { restoring: false, runState: 'UNAVAILABLE' } }));
          }
        } catch (_) { return; /* transport failure remains RESTORING */ }
        if (!mounted || !authoritativeResponse) return;
      }));
    };
    restoreScopedSources();
    return () => { mounted = false; };
  }, [visibleCameraIds.join('|'), backendStatus]);
  useEffect(() => {
    if (dashboardMode !== 'DUAL') setEventCameraFilter('ALL');
    if (!configuredCameraIds.includes(reliabilityCameraId)) setReliabilityCameraId(configuredCameraIds[0] || null);
  }, [dashboardMode, configuredCameraIds.join('|')]);
  const selectedSessionId = selectedCameraId ? cameraMedia[selectedCameraId]?.sessionId : null;
  const reportingCameraId = selectedSessionId
    ? Object.entries(scopedLiveTracks).find(([, telemetry]) => telemetry?.stream_id === selectedSessionId)?.[0]
    : null;
  const selectedCameraHasActiveStream = selectedCameraId
    && (!selectedSessionId || scopedLiveTracks[selectedCameraId]?.stream_id === selectedSessionId);
  const activeCameraId = (selectedCameraHasActiveStream ? selectedCameraId : reportingCameraId)
    || selectedCameraId
    || Object.keys(scopedLiveTracks).find((cameraId) => scopedLiveTracks[cameraId])
    || cameras.find(camera => camera.health_state)?.camera_id
    || cameraIds[0]
    || null;
  const activeCamera = cameraModels.find(camera => camera.cameraId === activeCameraId) || null;
  const activeMediaState = activeCameraId ? (cameraMedia[activeCameraId] || {}) : {};
  const mediaUrl = activeMediaState.mediaUrl || null;
  const mediaType = activeMediaState.mediaType || 'video';
  const isUploading = Boolean(activeMediaState.isUploading);
  const sessionStartTime = activeMediaState.sessionStartTime || 0;
  const videoSessionId = activeMediaState.sessionId || null;
  const uploadError = activeMediaState.uploadError || null;
  const playbackEnded = Boolean(activeMediaState.playbackEnded);
  const activeTelemetryReceivedAt = activeCameraId ? scopedLiveTracks[activeCameraId]?.timestamp : null;
  const telemetryAgeMs = activeTelemetryReceivedAt == null ? null : now - activeTelemetryReceivedAt;
  const analysisState = activeCameraId ? scopedLiveTracks[activeCameraId]?.analysis_state : null;
  const activeSourceState = activeCameraId ? slotSources[activeCameraId] : null;
  const telemetryStatus = !isConnected ? 'DISCONNECTED'
    : telemetryAgeMs == null ? lifecycleStatus(activeSourceState, null, now)
    : telemetryStatusAt(scopedLiveTracks[activeCameraId], now);
  const activeProcessingFps = processingFpsForTelemetry(scopedLiveTracks[activeCameraId], now);
  const activeCameraHealth = cameraHealthPresentation(health[activeCameraId], now);
  const activeCameraHealthLabel = ['PAUSED', 'WAKING'].includes(telemetryStatus) || (!health[activeCameraId] && activeSourceState?.sourceMode)
    ? (telemetryStatus === 'WAKING' ? 'AWAITING CURRENT-RUN HEALTH SAMPLE' : `N/A · ANALYSIS ${telemetryStatus}`)
    : `${activeCameraHealth.health}${activeCameraHealth.health !== 'OK' && activeCameraHealth.reason !== 'N/A' ? ` · ${String(activeCameraHealth.reason).replace(/_/g, ' ')}` : ''}`;

  const eventTimestampMs = (value) => {
    if (!value) return NaN;
    const date = parseUtc(value);
    return date ? date.getTime() : NaN;
  };

  const visibleContextKey = visibleCameraIds
    .filter(Boolean)
    .map((cameraId) => `${cameraId}:${cameraMedia[cameraId]?.sessionId || slotSources[cameraId]?.sourceId || ''}:${analysisSessionIdForSource(scopedLiveTracks[cameraId], slotSources[cameraId]) || ''}:${slotSources[cameraId]?.analysisGeneration ?? ''}`)
    .join('|');
  const completedSummaryContextKey = `${visibleContextKey}|${visibleCameraIds
    .filter(Boolean)
    .map((cameraId) => scopedLiveTracks[cameraId]?.analysis_state || slotSources[cameraId]?.analysisState || '')
    .join('|')}`;
  useEffect(() => {
    visibleCameraIds.filter(Boolean).forEach((cameraId) => {
      const streamId = cameraMedia[cameraId]?.sessionId || slotSources[cameraId]?.sourceId || null;
      const analysisSessionId = analysisSessionIdForSource(scopedLiveTracks[cameraId], slotSources[cameraId]);
      refreshEventsForContext(cameraId, streamId, analysisSessionId);
      refreshTelemetryForContext(
        cameraId,
        streamId,
        analysisSessionId,
        slotSources[cameraId]?.analysisGeneration,
      );
    });
  }, [visibleContextKey, refreshEventsForContext, refreshTelemetryForContext, scopedLiveTracks]);

  useEffect(() => {
    let mounted = true;
    visibleCameraIds.filter(Boolean).forEach(async (cameraId) => {
      const source = slotSources[cameraId];
      const sessionId = analysisSessionIdForSource(scopedLiveTracks[cameraId], source);
      if (!sessionId || !source?.sourceId || lifecycleStatus(source, scopedLiveTracks[cameraId], Date.now()) !== 'COMPLETED') return;
      setRunSummaryLoading(current => ({ ...current, [cameraId]: true }));
      const params = new URLSearchParams({ camera_id: cameraId, stream_id: source.sourceId });
      if (source.analysisGeneration != null) params.set('analysis_generation', String(source.analysisGeneration));
      try {
        const response = await authFetch(`/system/analysis-runs/${encodeURIComponent(sessionId)}?${params.toString()}`);
        const summary = response.ok ? await response.json() : null;
        if (mounted) setRunSummaries(current => ({ ...current, [cameraId]: summary }));
      } catch (_) {
        if (mounted) setRunSummaries(current => ({ ...current, [cameraId]: null }));
      } finally {
        if (mounted) setRunSummaryLoading(current => ({ ...current, [cameraId]: false }));
      }
    });
    return () => { mounted = false; };
  }, [completedSummaryContextKey]);

  useEffect(() => {
    if (activeCameraIds.length < 2) {
      setCorrelationState(null);
      return undefined;
    }
    let mounted = true;
    const refreshCorrelation = async () => {
      try {
        const params = new URLSearchParams({ active_camera_ids: activeCameraIds.join(',') });
        const streams = activeCameraIds.map((id) => scopedLiveTracks[id]?.stream_id);
        const sessions = activeCameraIds.map((id) => scopedLiveTracks[id]?.analysis_session_id);
        if (streams.every(Boolean) && sessions.every(Boolean)) {
          params.set('stream_ids', streams.join(','));
          params.set('analysis_session_ids', sessions.join(','));
        }
        const response = await authFetch(`/events/correlation/current?${params.toString()}`);
        if (mounted && response.ok) setCorrelationState(await response.json());
      } catch (_) { /* websocket remains the fast path */ }
    };
    refreshCorrelation();
    const id = setInterval(refreshCorrelation, 5000);
    return () => { mounted = false; clearInterval(id); };
  }, [activeCameraIds.join('|'), scopedLiveTracks]);


  const handleFileUpload = async (cameraId, e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    // Windows/browser file pickers can provide an empty or generic MIME for
    // AVI and other valid camera containers. Keep extension validation
    // conservative, then let the authenticated backend perform content and
    // size validation; do not reject a valid source solely on MIME metadata.
    const extension = String(file.name || '').toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] || '';
    const supportedExtensions = new Set(['avi', 'mp4', 'mov', 'mkv', 'webm', 'm4v']);
    const mimeLooksVideo = String(file.type || '').toLowerCase().startsWith('video/');
    if (!mimeLooksVideo && !supportedExtensions.has(extension)) {
      updateCameraMedia(cameraId, { uploadError: 'Please select a supported video file.' });
      return;
    }
    updateCameraMedia(cameraId, { uploadError: null });

    setLatestEvent(null);
    resetCameraContext(cameraId);
    setRunSummaries(current => ({ ...current, [cameraId]: null }));
    setRunSummaryLoading(current => ({ ...current, [cameraId]: false }));
    const previousSource = slotSources[cameraId];
    const pausePayload = scenarioAction(cameraId, previousSource, 'paused');
    if (pausePayload) {
      authFetch('/api/dashboard/video/scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pausePayload),
      }).catch(() => {});
    }
    const previousUrl = cameraMediaRef.current[cameraId]?.mediaUrl;
    if (previousUrl?.startsWith('blob:')) URL.revokeObjectURL(previousUrl);
    setSlotSources((current) => ({
      ...current,
      [cameraId]: {
        sourceMode: 'durable',
        sourceId: null,
        sourceName: file.name,
        runState: 'UPLOADING',
      },
    }));
    // Never preview the raw local blob. The first playable URL is the exact
    // normalized MP4 that the cloud worker will analyze.
    updateCameraMedia(cameraId, {
      mediaUrl: null,
      mediaType: 'video',
      isUploading: true,
      sessionId: null,
      sessionStartTime: Date.now(),
      playbackEnded: false,
      uploadError: null,
    });

    const formData = new FormData();
    formData.append('file', file);
    formData.append('camera_id', cameraId);
    let uploaded;
    try {
      const res = await authFetch('/api/dashboard/video/upload', { method: 'POST', body: formData });
      if (!res.ok) {
        let detail = 'VIDEO UPLOAD FAILED';
        try { detail = (await res.json()).detail || detail; } catch (_) { /* keep concise fallback */ }
        throw new Error(detail);
      }
      uploaded = await res.json();
    } catch (error) {
      // The server may have accepted a request even when the browser loses the
      // response. Keep the replacement context visible instead of resurrecting
      // the old bundled source; the operator can retry after checking current
      // sessions rather than silently creating a second upload.
      console.error('Upload error:', error);
      setSlotSources((current) => ({
        ...current,
        [cameraId]: { ...current[cameraId], sourceMode: 'durable', runState: 'ERROR' },
      }));
      updateCameraMedia(cameraId, {
        mediaUrl: null,
        isUploading: false,
        uploadError: error instanceof TypeError && error.message === 'Failed to fetch'
          ? 'UPLOAD CONNECTION INTERRUPTED'
          : (error.message || 'VIDEO UPLOAD FAILED'),
      });
      return;
    }

    // Phase 1 is durable as soon as upload returns 200. Persist this session
    // before activation/preview so a later failure can never roll it back.
    const sessionId = uploaded.session_id || null;
    const sourceName = uploaded.source_name || file.name;
    setSlotSources((current) => ({
      ...current,
      [cameraId]: {
        sourceMode: 'durable',
        sourceId: sessionId,
        sourceName,
        runState: sessionId ? 'ACTIVATING' : 'ERROR',
      },
    }));
    updateCameraMedia(cameraId, {
      mediaUrl: null,
      sessionId,
      isUploading: false,
      uploadError: sessionId ? null : 'VIDEO STORED BUT NO SESSION ID WAS RETURNED',
    });
    if (!sessionId) return;

    // Phase 2 — activate the exact uploaded session. Activation failure keeps
    // the durable source selected and is independently retryable.
    try {
      const analyzeRes = await authFetch('/api/dashboard/video/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, source_name: sourceName, preview_name: null, camera_id: cameraId }),
      });
      if (!analyzeRes.ok) {
        let detail = 'ANALYSIS ACTIVATION FAILED — RETRY';
        try { detail = (await analyzeRes.json()).detail || detail; } catch (_) { /* concise fallback */ }
        throw new Error(detail);
      }
      const activatedSource = {
        sourceMode: 'durable',
        sourceId: sessionId,
        sourceName,
        runState: 'WAKING',
      };
      setSlotSources((current) => ({ ...current, [cameraId]: activatedSource }));
      // A successful upload should flow directly into cloud analysis. This
      // avoids leaving the old demo worker active while the UI waits for a
      // second manual click and makes the public-link workflow deterministic.
      requestScenario(
        cameraId,
        scenarioAction(cameraId, activatedSource, 'normal', true),
      );
    } catch (error) {
      console.error('Analysis activation error:', error);
      setSlotSources((current) => ({ ...current, [cameraId]: { ...current[cameraId], runState: 'ERROR' } }));
      updateCameraMedia(cameraId, { uploadError: error instanceof TypeError && error.message === 'Failed to fetch' ? 'ANALYSIS ACTIVATION FAILED — RETRY' : (error.message || 'ANALYSIS ACTIVATION FAILED — RETRY') });
    }

    // Phase 3 — preview is useful but never authoritative. A redirect/blob
    // failure must not clear the stored session or its source identity.
    if (uploaded.preview_url) {
      try {
        const mediaRes = await authFetch(uploaded.preview_url);
        if (!mediaRes.ok) throw new Error('PREVIEW LOAD FAILED — VIDEO IS STILL STORED');
        const blobUrl = URL.createObjectURL(await mediaRes.blob());
        updateCameraMedia(cameraId, { mediaUrl: blobUrl, uploadError: null });
      } catch (error) {
        console.error('Preview load error:', error);
        updateCameraMedia(cameraId, { mediaUrl: null, uploadError: 'PREVIEW LOAD FAILED — VIDEO IS STILL STORED' });
      }
    }
  };

  const [fleetHealth, setFleetHealth] = useState([]);
  
  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const response = await authFetch('/api/nodes/health');
        if (response.ok) setFleetHealth(await response.json());
      } catch (e) {
        console.error("Failed to fetch fleet health", e);
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const triggerUpload = (cameraId) => {
    if (!cameraId) return;
    fileInputRefs.current[cameraId]?.click();
  };

  // Events for the selected camera and active uploaded-video context.
  const contextualEvents = [];
  const _seenIds = new Set();
  const visibleCameraSet = new Set(configuredCameraIds);
  events.forEach(e => {
    if (visibleCameraSet.size && !visibleCameraSet.has(e.camera_id)) return;
    if (!visibleCameraSet.size) return;
    if (eventCameraFilter !== 'ALL' && e.camera_id !== eventCameraFilter) return;
    // Every camera is scoped to its own current analysis session. This keeps
    // prior demo/history events out even when both fixed SIH camera IDs are in
    // view at the same time.
    const sourceTelemetry = scopedLiveTracks[e.camera_id];
    const contextStreamId = sourceTelemetry?.stream_id
      || slotSources[e.camera_id]?.sourceId
      || null;
    const contextAnalysisSessionId = analysisSessionIdForSource(sourceTelemetry, slotSources[e.camera_id]);
    const contextStartTime = cameraMedia[e.camera_id]?.sessionStartTime || null;
    if (contextStreamId && e.stream_id && e.stream_id !== contextStreamId) return;
    if (contextAnalysisSessionId && e.analysis_session_id !== contextAnalysisSessionId) return;
    if (contextStreamId && !e.stream_id) {
      const timestamp = eventTimestampMs(e.timestamp);
      if (!contextStartTime || !Number.isFinite(timestamp) || timestamp < contextStartTime) return;
    }
    
    // Deduplication
    const id = e.event_id || e.id;
    if (id) {
      if (_seenIds.has(id)) return;
      _seenIds.add(id);
    }
    
    // Legacy fallback applies only when no session contract is available.
    if (!contextStreamId && !contextAnalysisSessionId) {
      const timestamp = eventTimestampMs(e.timestamp);
      if (!contextStartTime || !Number.isFinite(timestamp) || timestamp < contextStartTime) return;
    }
    contextualEvents.push(e);
  });

  const currentSessionEvents = contextualEvents.filter((event) => {
    const telemetry = scopedLiveTracks[event.camera_id];
    const sessionId = analysisSessionIdForSource(telemetry, slotSources[event.camera_id]);
    return Boolean(sessionId && event.analysis_session_id === sessionId);
  });
  const runContexts = Object.fromEntries(configuredCameraIds.map((cameraId) => [cameraId, {
    streamId: slotSources[cameraId]?.sourceId || null,
    analysisSessionId: analysisSessionIdForSource(scopedLiveTracks[cameraId], slotSources[cameraId]),
  }]));
  const scopedRunEvents = filterLiveEvents(currentSessionEvents, runContexts, eventCameraFilter);
  const displayEvents = scopedRunEvents.filter(ev =>
    (ev.event_type && String(ev.event_type).toLowerCase() !== 'unknown') ||
    ev.decision_state === 'ABSTAIN' || ev.decision === 'ABSTAIN'
  ).slice(0, 10);
  const recentPlateReads = scopedRunEvents
    .filter((ev) => ev.normalized_plate_text || ev.plate_text)
    .sort((a, b) => eventTimestampMs(b.timestamp) - eventTimestampMs(a.timestamp))
    .slice(0, 8);

  useEffect(() => {
    setLatestEvent(displayEvents[0] || null);
  }, [displayEvents.length, displayEvents[0]?.event_id, displayEvents[0]?.id]);

  // Reliability factors and Gate 1 must describe the same event snapshot.
  // Live camera health is only a fallback when no event health was recorded.
  const scopedLatestEvent = selectReliabilityEvent(
    scopedRunEvents,
    reliabilityScopeCameraId,
    configuredCameraIds,
    analysisSessionIdForSource(scopedLiveTracks[reliabilityScopeCameraId], slotSources[reliabilityScopeCameraId]),
    slotSources[reliabilityScopeCameraId]?.sourceId || null,
  );
  const reliabilityEvent = scopedLatestEvent;
  const parsed = reliabilityEvent ? parseDecisionReason(reliabilityEvent) : null;
  // Only the REST result is scoped to the currently live cameras and their
  // current streams.  A websocket correlation message can legitimately
  // describe an earlier session, so it must not override this scoped view.
  const effectiveCorrelation = dashboardMode === 'DUAL' ? correlationState : null;
  const healthState = reliabilityEvent?.camera_health_state
    || (reliabilityEvent && health[reliabilityEvent.camera_id]?.health_state); // 'OK' | 'DEGRADED' | 'FAILED'
  const sceneCondition = reliabilityEvent?.scene_condition;
  const decisionMeta = DECISION_META[reliabilityEvent?.decision_state] || null;
  const whyExplanation = explainDecision(reliabilityEvent ? parseDecisionReason(reliabilityEvent) : null);
  let liveTelemetry = !activeCameraId ? null : scopedLiveTracks[activeCameraId];
  if (liveTelemetry && videoSessionId && liveTelemetry.stream_id && liveTelemetry.stream_id !== videoSessionId) {
    liveTelemetry = null;
  }

  const StatusPill = ({ title, desc, type, active }) => {
    let colors = '';
    let icon = null;
    
    if (type === 'detected') {
      colors = active ? 'bg-ok text-black' : 'badge-outline';
      icon = <CheckCircle size={16} />;
    } else if (type === 'uncertain') {
      colors = active ? 'bg-warning text-black' : 'badge-outline';
      icon = <HelpCircle size={16} />;
    } else {
      colors = active ? 'bg-danger text-white' : 'badge-outline';
      icon = <ShieldAlert size={16} />;
    }

    return (
      <div className={`dashboard-status-pill card ${colors} transition-all ${active ? 'shadow-lg scale-105' : 'opacity-60'}`} style={{ padding: '0.625rem', height: '100%', borderColor: active ? 'transparent' : 'var(--border-color)', borderRadius: 'var(--radius-md)' }}>
        <div className="flex items-center" style={{ gap: '0.375rem', marginBottom: '0.2rem' }}>
          {icon}
          <span className="font-display font-bold" style={{ fontSize: '0.7rem', letterSpacing: '0.05em' }}>{title}</span>
        </div>
        <span className="font-body" style={{ fontSize: '0.55rem', opacity: 0.8, lineHeight: 1.2 }}>{desc}</span>
      </div>
    );
  };

  const LogicGate = ({ num, title, stats, active }) => (
    <div className={`dashboard-logic-gate flex rounded border ${active ? 'border-ok bg-[rgba(34,211,164,0.05)]' : 'border-color opacity-50'} relative`} style={{ padding: '0.5rem', gap: '0.75rem', borderRadius: 'var(--radius-md)' }}>
      <div className="flex-shrink-0 mt-1">
        <div className={`w-3 h-3 rounded-full border-2 flex items-center justify-center ${active ? 'border-ok text-ok bg-[rgba(34,211,164,0.2)]' : 'border-color text-muted'}`}>
        </div>
      </div>
      <div className="flex flex-col w-full">
        <span className="dashboard-gate-title font-display text-muted uppercase tracking-wider" style={{ fontSize: '0.55rem', letterSpacing: '0.1em', marginBottom: '0.25rem' }}>Gate {num} — {title}</span>
        <div className="flex justify-between items-center rounded border border-color" style={{ padding: '0.35rem', background: 'var(--bg-base)' }}>
          {stats}
        </div>
      </div>
      
      {num < 3 && <div className="absolute left-6 top-8 h-12 bg-border-color -z-10" style={{ width: '1px' }}></div>}
    </div>
  );

  return (
    <div className="dashboard-page h-full flex flex-col" style={{ gap: '1rem' }}>
      <div className="section-header">
        <div>
          <div className="section-title">Border Intelligence Center</div>
          <div className="section-sub">Real-time camera, edge and reliability monitoring</div>
        </div>
        <div className="dashboard-command-status">
          <label className="dashboard-camera-select">
            <span>ACTIVE CAMERA</span>
            <select
              value={activeCameraId || ''}
              onChange={(event) => {
                setSelectedCameraId(event.target.value);
                setLatestEvent(null);
                updateCameraMedia(event.target.value, { playbackEnded: false });
              }}
              disabled={cameraIds.length === 0}
            >
              {cameraIds.length === 0 && <option value="">No camera configured</option>}
              {cameraModels.map(camera => {
                return <option key={camera.cameraId} value={camera.cameraId}>{camera.friendlyName} · {camera.displayId} · {camera.status}</option>;
              })}
            </select>
          </label>
          <div className={`dashboard-status-chip status-${backendStatus.toLowerCase()}`}>
            <span>BACKEND</span><strong>{backendStatus}</strong>
          </div>
          <div className={`dashboard-status-chip status-${connectionStatus.toLowerCase()}`}>
            <span>SOCKET</span><strong>{connectionStatus}</strong>
          </div>
          <div className={`dashboard-status-chip status-${telemetryStatus.toLowerCase()}`}>
            <span>TELEMETRY</span><strong>{telemetryStatus}</strong>
          </div>
        </div>
      </div>

      <div className="dashboard-live-strip">
        <div><span>CAMERA</span><strong title={activeCamera?.displayId}>{activeCamera?.friendlyName || 'Not configured'}</strong></div>
        <div><span>CAMERA HEALTH</span><strong>{activeCameraHealthLabel}</strong></div>
        <div><span>AI FPS</span><strong>{activeProcessingFps == null ? 'N/A' : activeProcessingFps.toFixed(2)}</strong></div>
        <div><span>LIVE TRACKS</span><strong>{telemetryStatus === 'LIVE' ? (scopedLiveTracks[activeCameraId]?.track_count ?? 'NOT REPORTED') : 'N/A'}</strong></div>
        <div><span>FRAME</span><strong>{telemetryStatus === 'LIVE' && scopedLiveTracks[activeCameraId]?.frame_width != null && scopedLiveTracks[activeCameraId]?.frame_height != null ? `${scopedLiveTracks[activeCameraId].frame_width}×${scopedLiveTracks[activeCameraId].frame_height}` : 'N/A'}</strong></div>
        <div><span>LAST TELEMETRY</span><strong>{activeSourceState?.restoring || runSummaryLoading[activeCameraId] ? 'LOADING RUN HISTORY...' : telemetryAgeMs == null ? (telemetryStatus === 'PAUSED' ? 'N/A · PAUSED' : telemetryStatus === 'WAKING' ? 'WAITING FOR FIRST CURRENT-RUN TELEMETRY' : 'Never') : formatTelemetryAge(telemetryAgeMs)}</strong></div>
      </div>

      <section className={`dashboard-camera-grid camera-mode-${dashboardMode.toLowerCase()}`} aria-label="Camera source slots">
        {Array.from({ length: MAX_VISIBLE_CAMERAS }, (_, slotIndex) => {
          const cameraId = visibleCameraIds[slotIndex];
          const camera = cameraModels.find(item => item.cameraId === cameraId) || null;
          const telemetry = cameraId ? scopedLiveTracks[cameraId] : null;
          const sourceState = cameraId ? slotSources[cameraId] : null;
          const sessionId = analysisSessionIdForSource(telemetry, sourceState);
          const cameraEvents = displayEvents.filter(event => event.camera_id === cameraId);
          const latestCameraEvent = latestEventForSession(cameraEvents, cameraId, sessionId);
          const latestFaceEvent = cameraEvents.find(event => String(event.event_type || '').toUpperCase() === 'FACE_DETECTED' || event.face_match_status || event.recognition_state) || null;
          const faceStatus = latestFaceEvent?.face_match_status || (latestFaceEvent?.face_match_person_id ? 'KNOWN' : latestFaceEvent ? 'UNKNOWN' : null);
          const faceLabel = latestFaceEvent?.watchlist_label || latestFaceEvent?.face_match_person_name || null;
          const completedSummary = runSummaries[cameraId] || null;
          const lightingState = latestCameraEvent?.lighting_state || telemetry?.lighting_state || completedSummary?.lighting_state || 'AWAITING CURRENT-RUN SAMPLE';
          const sceneState = latestCameraEvent?.scene_condition || telemetry?.scene_condition || completedSummary?.scene_condition || 'AWAITING CURRENT-RUN SAMPLE';
          const analyticsMethod = latestCameraEvent?.detection_method || telemetry?.detection_method || completedSummary?.detection_method || 'AWAITING CURRENT-RUN SAMPLE';
          const metadata = cameraDisplayMetadata(camera, slotIndex);
          const locationLabel = metadata.location;
          const title = metadata.name;
          const startupKey = cameraId === 'cam-border-01' ? 'camBorder01' : cameraId === 'cam-checkpoint-01' ? 'camCheckpoint01' : null;
          const edgeRuntime = startupKey ? startupReadiness[startupKey] : null;
          const operational = deriveCameraOperationalState({ nodeStatus: edgeRuntime?.status, sourceState, telemetry, now });
          const capabilities = edgeRuntime?.payload?.capabilities || null;
          const status = lifecycleStatus(sourceState, telemetry, now);
          const liveStatus = telemetryStatusAt(telemetry, now);
          const telemetryAvailable = Boolean(telemetry && liveStatus === 'LIVE');
          const completedRun = status === 'COMPLETED';
          const lifecycle = String(sourceState?.analysisState || sourceState?.runState || '').toUpperCase();
          const displayRunState = sourceState?.restoring
            ? 'RESTORING'
            : lifecycle || (telemetryAvailable ? 'LIVE' : 'LOADED');
          const mediaState = cameraId ? (cameraMedia[cameraId] || {}) : {};
          const isDemoReplay = Boolean(telemetry?.demo_replay || sourceState?.sourceMode === 'bundled');
          const statusLabel = status;
          const cardFps = processingFpsForTelemetry(telemetry, now);
          const sourceFps = sourceFpsForTelemetry(telemetry);
          // Process-local telemetry is not a durable completed-run record.
          // Only display it after EOF when it belongs to the exact restored
          // analysis session; otherwise name the absence instead of implying
          // that an old global/latest value is current evidence.
          const completedTelemetry = completedRun ? completedSummary : null;
          const updateTimestamp = completedRun ? completedSummary?.completed_at || completedSummary?.last_telemetry_at : telemetry?.timestamp;
          const normalizedUpdateTimestamp = updateTimestamp == null ? null : Number(updateTimestamp) > 1e12 ? Number(updateTimestamp) : Number(updateTimestamp) * 1000;
          const updateAge = normalizedUpdateTimestamp == null ? null : Math.max(0, now - normalizedUpdateTimestamp);
          return (
            <article className="dashboard-camera-card card" key={`camera-slot-${slotIndex}`}>
              {cameraId && <input
                type="file"
                accept=".mp4,.avi,.mov,.mkv,.webm,.m4v,video/*"
                onChange={(event) => handleFileUpload(cameraId, event)}
                ref={(element) => { fileInputRefs.current[cameraId] = element; }}
                style={{ display: 'none' }}
                data-camera-id={cameraId}
              />}
              <div className="dashboard-camera-card-header">
                <div>
                  <div className="dashboard-camera-kicker">CAMERA {String(slotIndex + 1).padStart(2, '0')}</div>
                  <h2>{title}</h2>
                  <p>{cameraId ? `${cameraId.toUpperCase()} · ${locationLabel}` : 'No source selected'}</p>
                  {sourceState?.restoring && <p className="dashboard-source-name">RESTORING CLOUD SOURCE...</p>}
                  {!sourceState?.restoring && sourceState?.sourceName && <p className="dashboard-source-name">SOURCE: {sourceState.sourceName}</p>}
                  {!sourceState?.restoring && sourceState?.sourceMode && <p className="dashboard-source-name">MODE: {sourceState.sourceMode === 'durable' ? 'USER UPLOAD' : 'BUNDLED DEMO'} · ANALYSIS: {displayRunState}</p>}
                  {mediaState.controlStatus && <p className="dashboard-source-name" role="status">{mediaState.controlStatus}</p>}
                  <p className="dashboard-source-name">SUPPORTED: MP4 · AVI · MOV · MKV · WEBM · M4V</p>
                  {mediaState.edgeStatus === 'WAKING' && !telemetryAvailable && <p className="dashboard-source-name">WAKING AI WORKER...</p>}
                </div>
                <div className="dashboard-camera-card-controls">
                  <span className={`dashboard-camera-status status-${status.toLowerCase().replace(/\s+/g, '-')}`}>{statusLabel}</span>
                  {cameraId && canUpload && !sourceState?.restoring && <div className="dashboard-slot-actions">
                    <button type="button" className="btn btn-sm btn-outline" onClick={() => triggerUpload(cameraId)}>{sourceState?.sourceName ? 'REPLACE VIDEO' : 'ADD VIDEO'}</button>
                    {sourceState?.sourceMode && lifecycleAction(sourceState) === 'START' && <button type="button" className="btn btn-sm btn-outline" data-action="start-analysis" data-camera-id={cameraId} disabled={Boolean(controlRequests[cameraId])} onClick={() => handleStartAnalysis(cameraId, sourceState)}>{controlRequests[cameraId] ? 'STARTING...' : 'START / ANALYZE'}</button>}
                    {sourceState?.sourceMode && lifecycleAction(sourceState) === 'STOP' && <button className="btn btn-sm btn-outline" onClick={async () => {
                      const payload = scenarioAction(cameraId, sourceState, 'paused');
                      if (payload) {
                        try {
                          const response = await authFetch('/api/dashboard/video/scenario', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                          const result = await response.json().catch(() => ({}));
                          if (!response.ok) throw new Error(`STOP FAILED — HTTP ${response.status}`);
                          setSlotSources((current) => ({
                            ...current,
                            [cameraId]: current[cameraId] ? {
                              ...current[cameraId],
                              runState: String(result.analysis_state || 'PAUSED').toUpperCase(),
                              analysisState: String(result.analysis_state || 'PAUSED').toUpperCase(),
                              ...(result.analysis_generation != null ? { analysisGeneration: result.analysis_generation } : {}),
                            } : current[cameraId],
                          }));
                          updateCameraMedia(cameraId, { edgeStatus: 'WAITING', uploadError: null });
                        } catch (error) {
                          updateCameraMedia(cameraId, { uploadError: error.message || 'STOP FAILED' });
                        }
                      }
                      // Keep the selected source bound to this slot while it is
                      // paused so the operator can START / ANALYZE the same
                      // uploaded file again. Clearing the slot and deleting
                      // its source metadata made local uploads impossible to
                      // restart after STOP.
                      setLatestEvent(null);
                    }} type="button" data-action="stop-analysis" data-camera-id={cameraId}>STOP ANALYSIS</button>}
                  </div>}
                  <select
                    aria-label={`Select camera slot ${slotIndex + 1}`}
                    value={cameraId || ''}
                    onChange={(event) => {
                      const next = [...visibleCameraIds];
                      next[slotIndex] = event.target.value || null;
                      setCameraSlots(next);
                      if (event.target.value) setSelectedCameraId(event.target.value);
                    }}
                  >
                    <option value="">Not connected</option>
                    {cameraModels.map(item => <option key={item.cameraId} value={item.cameraId}>{item.friendlyName} · {item.displayId}</option>)}
                  </select>
                </div>
              </div>
              <div className="dashboard-camera-media">
                {cameraId ? (
                  <VideoFeed
                    eventData={latestCameraEvent}
                    liveTracksData={telemetry}
                    telemetryStatus={camera?.status || 'WAITING'}
                    cameraId={cameraId}
                    playbackEnded={Boolean(mediaState.playbackEnded)}
                    demoScenario={demoScenario}
                    mediaUrl={mediaState.mediaUrl || null}
                    mediaType={mediaState.mediaType || 'video'}
                    currentFps={cardFps}
                    onUpload={() => triggerUpload(cameraId)}
                    isUploading={Boolean(mediaState.isUploading)}
                    canUpload={canUpload}
                    uploadError={mediaState.uploadError || null}
                    sourceMode={sourceState?.sourceMode || null}
                    expectedSessionId={sourceState?.sourceId || null}
                    sourceRunState={displayRunState}
                    sourceRestoring={Boolean(sourceState?.restoring)}
                    onVideoEnded={() => updateCameraMedia(cameraId, { playbackEnded: true })}
                  />
                ) : (
                  <div className="dashboard-camera-empty"><ShieldAlert size={22} /><strong>CAMERA SLOT {slotIndex + 1} · NOT CONFIGURED</strong><span>No video source selected.</span></div>
                )}
              </div>
              <div className="dashboard-camera-ai-row" aria-label="AI capability status">
                {isDemoReplay && <span className="ai-demo">DEMO REPLAY</span>}
                <span className={telemetryAvailable ? 'ai-active' : 'ai-context'}>DETECTION {telemetryAvailable ? 'LIVE' : status === 'STALE' ? 'STALE · LAST KNOWN' : status}</span>
                <span className={telemetryAvailable ? 'ai-active' : 'ai-context'}>TRACKING {telemetryAvailable ? 'LIVE' : status === 'STALE' ? 'STALE · LAST KNOWN' : status}</span>
                <span className="ai-context">SCENE {sceneState.replace(/_/g, ' ')} · LIGHTING {lightingState.replace(/_/g, ' ')}</span>
                <span className="ai-context">ANALYTICS {analyticsMethod.replace(/_/g, ' ')}</span>
                <span className="ai-context">LINE / FENCE EVENT {cameraId ? 'BACKEND' : 'WAITING'}</span>
                <span className="ai-context">NODE {operational.node}</span>
                <span className="ai-context">SOURCE {operational.source}</span>
                <span className="ai-context">ANALYSIS {operational.analysis}</span>
                <span className="ai-context">TELEMETRY {operational.telemetry}</span>
                <span className="ai-context">ANPR {capabilityLabel(capabilities?.anpr_localization, 'LOCALIZATION AVAILABLE')}</span>
                <span className="ai-context">OCR {capabilityLabel(capabilities?.anpr_ocr, 'AVAILABLE', 'UNAVAILABLE')}</span>
              </div>
              <div className="dashboard-camera-telemetry" aria-label={`ANPR result for ${cameraId || 'empty slot'}`}>
                <span><b>ANPR OCR</b>{latestCameraEvent?.normalized_plate_text || latestCameraEvent?.plate_text || (capabilities?.anpr_ocr === false ? 'OCR UNAVAILABLE' : 'NO PLATE READ FOR THIS RUN')}</span>
                <span><b>CONFIDENCE</b>{latestCameraEvent?.plate_confidence == null ? 'N/A' : `${Math.round(Number(latestCameraEvent.plate_confidence) * 100)}%`}</span>
              </div>
              <div className="dashboard-camera-telemetry" aria-label={`Face watchlist result for ${cameraId || 'empty slot'}`}>
                <span><b>FACE WATCHLIST</b>{faceStatus === 'KNOWN' ? `MATCH · ${faceLabel || 'SUBJECT LABEL NOT REPORTED'}` : faceStatus === 'INSUFFICIENT_QUALITY' ? 'INSUFFICIENT QUALITY' : faceStatus === 'UNKNOWN' ? 'NO WATCHLIST MATCH' : 'NO FACE RESULT FOR THIS RUN'}</span>
                <span><b>SCORE</b>{latestFaceEvent?.recognition_score == null ? 'N/A' : Number(latestFaceEvent.recognition_score).toFixed(1)}</span>
              </div>
              <div className="dashboard-camera-telemetry">
                <span><b>{completedRun ? 'FINAL AI FPS' : 'AI FPS'}</b>{completedRun
                  ? (Number.isFinite(completedTelemetry?.processing_fps) ? Number(completedTelemetry.processing_fps).toFixed(2) : 'NOT RECORDED FOR THIS COMPLETED RUN')
                  : (cardFps == null ? 'N/A' : cardFps.toFixed(2))}</span>
                <span><b>SOURCE FPS</b>{completedRun ? (sourceFpsForTelemetry(completedTelemetry) == null ? 'NOT RECORDED FOR THIS COMPLETED RUN' : sourceFpsForTelemetry(completedTelemetry).toFixed(2)) : (sourceFps == null ? 'N/A' : sourceFps.toFixed(2))}</span>
                <span><b>PERSONS</b>{completedRun ? (completedTelemetry?.person_count ?? 'NOT RECORDED FOR THIS COMPLETED RUN') : (telemetryAvailable ? (telemetry.person_count ?? 'NOT REPORTED FOR THIS RUN') : 'N/A')}</span>
                <span><b>VEHICLES</b>{completedRun ? (completedTelemetry?.vehicle_count ?? 'NOT RECORDED FOR THIS COMPLETED RUN') : (telemetryAvailable ? (telemetry.vehicle_count ?? 'NOT REPORTED FOR THIS RUN') : 'N/A')}</span>
                <span><b>TRACKS</b>{completedRun ? (completedTelemetry?.track_count ?? 'NOT RECORDED FOR THIS COMPLETED RUN') : (telemetryAvailable ? (telemetry.track_count ?? 'NOT REPORTED FOR THIS RUN') : 'N/A')}</span>
                <span><b>LAST UPDATE</b>{runSummaryLoading[cameraId] ? 'LOADING RUN HISTORY...' : updateAge == null ? (completedRun ? 'NOT RECORDED FOR THIS HISTORICAL RUN' : 'Never') : liveStatus === 'COMPLETED' ? `COMPLETED ${formatTelemetryAge(updateAge)}` : liveStatus === 'OFFLINE' ? 'OFFLINE' : liveStatus === 'STALE' ? `STALE · ${formatTelemetryAge(updateAge)}` : formatTelemetryAge(updateAge)}</span>
                <span><b>LATEST EVENT</b>{formatLatestEvent(latestCameraEvent, now)}</span>
              </div>
            </article>
          );
        })}
      </section>

      <section className="dashboard-events-card card" aria-label="Latest unified security events">
        <div className="card-header">
          <div><span className="card-title">Current Run Events</span><span className="dashboard-events-subtitle">{configuredCameraIds.length === 0 ? 'WAITING FOR SOURCE' : configuredCameraIds.length === 1 ? `Showing current-run events for ${cameraModels.find((camera) => camera.cameraId === configuredCameraIds[0])?.friendlyName || configuredCameraIds[0]}` : 'Unified feed · exact current source/run sessions'} · latest {Math.min(displayEvents.length, 10)}</span></div>
          {configuredCameraIds.length > 1 && <div className="dashboard-event-filters" role="group" aria-label="Event camera filter">
            <button className={`btn btn-sm ${eventCameraFilter === 'ALL' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setEventCameraFilter('ALL')}>ALL</button>
            {configuredCameraIds.map((cameraId) => <button key={cameraId} className={`btn btn-sm ${eventCameraFilter === cameraId ? 'btn-primary' : 'btn-outline'}`} onClick={() => setEventCameraFilter(cameraId)}>{cameraId === 'cam-border-01' ? 'CAM 1' : 'CAM 2'}</button>)}
          </div>}
          <button onClick={() => setShowWhy((value) => !value)} className="btn btn-sm btn-outline">WHY THIS ALERT?</button>
        </div>
        {showWhy && <div className="dashboard-events-explanation">{whyExplanation || 'No verified event is available yet. This explanation will use the backend decision factors when an event arrives.'}</div>}
        <div className="dashboard-events-table-wrap">
          {cameraInventoryRestoring ? <div className="state-empty" style={{ padding: '1rem' }}><div className="state-empty-sub">RESTORING CAMERA CONFIGURATION</div></div> : configuredCameraIds.length === 0 ? <div className="state-empty" style={{ padding: '1rem' }}><div className="state-empty-sub">WAITING FOR SOURCE — ADD A VIDEO TO BEGIN ANALYSIS.</div></div> : displayEvents.length === 0 ? <div className="state-empty" style={{ padding: '1rem' }}><div className="state-empty-sub">{configuredCameraIds.every((id) => lifecycleStatus(slotSources[id], scopedLiveTracks[id], now) === 'COMPLETED') ? 'ANALYSIS COMPLETED — NO VERIFIED SECURITY EVENT WAS GENERATED FOR THIS RUN.' : configuredCameraIds.some((id) => ['PAUSED', 'READY'].includes(String(slotSources[id]?.runState || slotSources[id]?.analysisState).toUpperCase())) ? 'SOURCE LOADED — ANALYSIS PAUSED. No current-run security event yet.' : 'PROCESSING — NO VERIFIED SECURITY EVENT YET.'}</div></div> : (
            <table className="dashboard-events-table">
              <thead><tr>{['TIME', 'EVENT ID', 'CAMERA', 'EVENT', 'DECISION', 'SEVERITY', 'EVIDENCE'].map(label => <th key={label}>{label}</th>)}</tr></thead>
              <tbody>{displayEvents.map((event, index) => {
                const time = parseUtc(event.timestamp);
                const camera = cameraModels.find(item => item.cameraId === event.camera_id);
                return <tr key={event.event_id || event.id || `${event.timestamp}-${index}`}>
                  <td>{time && !Number.isNaN(time.getTime()) ? time.toISOString().substring(11, 19) : 'N/A'}</td>
                  <td title={event.event_id || event.id || ''}>{String(event.event_id || event.id || 'N/A').slice(0, 8)}</td>
                  <td>{camera?.friendlyName || event.camera_id || 'Unknown camera'}</td>
                  <td>{String(event.event_type || event.detection_class || 'Security event').replace(/_/g, ' ').replace(/MOVEMENT UNCLASSIFIED/g, 'LOW LIGHT MOVEMENT')}{event.detection_method === 'MOTION_FALLBACK' ? ' · MOTION FALLBACK' : ''}</td>
                  <td className={`decision-${String(event.decision_state || event.decision || 'UNKNOWN').toLowerCase()}`}>{event.decision_state || event.decision || 'UNKNOWN'}</td>
                  <td>{event.severity || event.threat_level || 'N/A'}</td>
                  <td><a className="btn btn-sm btn-outline" href="/evidence">Open evidence</a></td>
                </tr>;
              })}</tbody>
            </table>
          )}
        </div>
      </section>

      <section className="dashboard-events-card card" aria-label="Recent number plate reads">
        <div className="card-header">
          <div><span className="card-title">Recent Number Plate Reads</span><span className="dashboard-events-subtitle">Current camera/session scope · {recentPlateReads.length} read{recentPlateReads.length === 1 ? '' : 's'}</span></div>
          {dashboardMode === 'DUAL' && <div className="dashboard-event-filters" role="group" aria-label="ANPR camera filter">
            <button className={`btn btn-sm ${eventCameraFilter === 'ALL' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setEventCameraFilter('ALL')}>ALL</button>
            {activeCameraIds.map((cameraId) => <button key={`anpr-${cameraId}`} className={`btn btn-sm ${eventCameraFilter === cameraId ? 'btn-primary' : 'btn-outline'}`} onClick={() => setEventCameraFilter(cameraId)}>{cameraModels.find((camera) => camera.cameraId === cameraId)?.friendlyName || cameraId}</button>)}
          </div>}
        </div>
        {recentPlateReads.length === 0 ? <div className="state-empty" style={{ padding: '1rem' }}><div className="state-empty-sub">NO PLATE READ — accepted OCR results will appear here.</div></div> : (
          <div className="dashboard-events-table-wrap"><table className="dashboard-events-table"><thead><tr>{['TIME', 'CAMERA', 'PLATE', 'CONFIDENCE', 'VEHICLE', 'EVIDENCE'].map(label => <th key={`anpr-head-${label}`}>{label}</th>)}</tr></thead><tbody>{recentPlateReads.map((event, index) => {
            const time = parseUtc(event.timestamp);
            const camera = cameraModels.find(item => item.cameraId === event.camera_id);
            return <tr key={`plate-${event.event_id || index}`}><td>{time && !Number.isNaN(time.getTime()) ? time.toISOString().substring(11, 19) : 'N/A'}</td><td>{camera?.friendlyName || event.camera_id}</td><td className="font-display">{event.normalized_plate_text || event.plate_text}</td><td>{event.plate_confidence == null ? 'N/A' : `${Math.round(Number(event.plate_confidence) * 100)}%`}</td><td>{event.vehicle_subtype || event.detection_class || 'vehicle'}</td><td><a className="btn btn-sm btn-outline" href="/evidence">Open evidence</a></td></tr>;
          })}</tbody></table></div>
        )}
      </section>

      {/* h-[calc(100%-80px)], flex-[3]/flex-[2] (below), and min-h-[400px]
          (below) were all bracket-notation classes that never applied any
          real CSS — the video feed column in particular used to collapse
          to ~2px tall as a result (confirmed via getComputedStyle, not
          guessed) since nothing was left to give it real height once
          .absolute/.relative were fixed and stopped accidentally
          contributing document-flow height. Converted to real inline
          styles. */}
      <div className="dashboard-main-grid flex" style={{ flex: 1, minHeight: 0, gap: '1rem' }}>

        {/* Left Column */}
        <div className="dashboard-left-column flex-col h-full" style={{ flex: 3, display: 'flex', gap: '0.75rem' }}>
          <div className="dashboard-video-slot" style={{ minHeight: '300px' }}>
            <VideoFeed
              eventData={latestEvent}
              liveTracksData={liveTelemetry}
              telemetryStatus={telemetryStatus}
              cameraId={activeCameraId}
              playbackEnded={playbackEnded}
              demoScenario={demoScenario}
              mediaUrl={mediaUrl}
              mediaType={mediaType}
              currentFps={activeProcessingFps}
              onUpload={() => triggerUpload(activeCameraId)}
              isUploading={isUploading}
              canUpload={canUpload}
              uploadError={uploadError}
              sourceMode={slotSources[activeCameraId]?.sourceMode || null}
              expectedSessionId={slotSources[activeCameraId]?.sourceId || null}
              sourceRunState={slotSources[activeCameraId]?.runState || null}
              onVideoEnded={() => updateCameraMedia(activeCameraId, { playbackEnded: true })}
            />
          </div>

          <div className="dashboard-timeline-card card" style={{ minHeight: '21rem' }}>
            <div className="card-header">
              <span className="card-title">Event Timeline</span>
              <button
                onClick={() => setShowWhy((v) => !v)}
                className="btn btn-sm btn-outline"
                style={{ fontSize: '0.5rem', letterSpacing: '0.05em' }}
              >
                WHY THIS ALERT?
              </button>
            </div>
            
            <div className="flex flex-col" style={{ padding: '0.75rem', gap: '0.5rem', overflowY: 'auto' }}>
              {showWhy && (
                <div className="text-xs font-body text-main border border-color rounded mb-2" style={{ padding: '0.5rem', background: 'var(--bg-base)' }}>
                  {whyExplanation || 'No real event yet to explain — this fills in from the same decision_reason data the Reliability Decision panel shows, once one arrives.'}
                </div>
              )}
              <div className="flex flex-col gap-2 flex-grow pr-2">
                {!mediaUrl && displayEvents.length === 0 ? (
                  <div className="state-empty" style={{ padding: '1rem' }}>
                    <div className="state-empty-sub">No verified security events recorded for this camera yet</div>
                  </div>
                ) : analysisState === 'COMPLETED' && displayEvents.length === 0 ? (
                  <div className="state-empty" style={{ padding: '1rem' }}>
                    <div className="state-empty-sub">VIDEO COMPLETE — NO SECURITY EVENTS DETECTED FOR THIS STREAM</div>
                  </div>
                ) : displayEvents.length === 0 ? (
                  <div className="state-loading" style={{ padding: '1rem' }}>
                    <span>PROCESSING — NO VERIFIED SECURITY EVENT YET</span>
                  </div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                        {['TIME','TRACK','TYPE','DECISION','SEVERITY','CONF','VERIFIED'].map(h => (
                          <th key={h} style={{
                            fontFamily: 'var(--font-display)', fontSize: '0.75rem',
                            fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
                            color: 'var(--text-muted)', padding: '0.25rem 0.5rem',
                            textAlign: 'left', whiteSpace: 'nowrap',
                          }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {/* Real events from processed video */}
                      {displayEvents.map((ev, i) => {
                        const parsedEv = parseDecisionReason(ev);
                        const conf = parsedEv?.kind === 'scored'
                          ? `${Math.round(parsedEv.d * 100)}%`
                          : 'N/A';
                        const tsDate = parseUtc(ev.timestamp);
                        const tsStr = tsDate && !isNaN(tsDate)
                          ? tsDate.toISOString().substring(11, 19)
                          : 'N/A';
                        const decColor =
                          ev.decision_state === 'DETECTED'  ? 'var(--color-ok)'      :
                          ev.decision_state === 'UNCERTAIN' ? 'var(--color-warning)'  :
                          ev.decision_state === 'ABSTAIN'   ? 'var(--color-danger)'   :
                                                              'var(--text-muted)';
                        let typeLabel = ev.event_type
                          ? ev.event_type.replace(/_/g, ' ')
                          : (ev.detection_class || 'N/A');
                        if (ev.decision_state === 'ABSTAIN' && (!ev.event_type || String(ev.event_type).toLowerCase() === 'unknown')) {
                          typeLabel = ev.decision_reason ? `SYSTEM ABSTAIN: ${ev.decision_reason}` : 'SYSTEM ABSTAIN';
                        }
                        return (
                          <tr key={ev.event_id || ev.id || `${ev.timestamp}-${ev.track_id||''}-${i}`}
                              style={{ borderBottom: '1px solid rgba(30,48,80,0.4)' }}>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.875rem', color: 'var(--accent)', padding: '0.3rem 0.5rem', whiteSpace: 'nowrap' }}>{tsStr}</td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.875rem', color: 'var(--text-main)', padding: '0.3rem 0.5rem' }}>#{ev.track_id ?? 'N/A'}</td>
                            <td style={{ fontSize: '0.875rem', color: 'var(--text-main)', padding: '0.3rem 0.5rem', maxWidth: '8rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={typeLabel}>{typeLabel}</td>
                            <td style={{ fontFamily: 'var(--font-display)', fontSize: '0.8rem', fontWeight: 700, color: decColor, padding: '0.3rem 0.5rem', whiteSpace: 'nowrap' }}>{ev.decision_state || 'N/A'}</td>
                            <td style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', color: ev.severity === 'HIGH' || ev.severity === 'CRITICAL' ? 'var(--color-danger)' : 'var(--text-muted)', padding: '0.3rem 0.5rem', whiteSpace: 'nowrap' }}>{ev.severity || 'N/A'}</td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.875rem', color: 'var(--text-muted)', padding: '0.3rem 0.5rem' }}>{conf}</td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: ev.verified_ok === true ? 'var(--color-ok)' : 'var(--text-muted)', padding: '0.3rem 0.5rem', whiteSpace: 'nowrap' }}>{ev.verified_ok == null ? 'N/A' : ev.verified_ok ? 'YES' : 'NO'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          {/* Cross-Camera Corroboration Panel
              Shows temporal/spatial plausibility score (Tc) when a second
              camera has observed the same detection class within the expected
              travel-time window.  This is NOT identity re-identification —
              see backend/services/cross_camera.py for honest scope. */}
          <div className="dashboard-cross-camera-card card mt-2">
            <div className="card-header">
              <div className="flex items-center gap-2">
                <GitMerge size={12} className="text-muted" />
                <span className="card-title">Cross-Camera Corroboration</span>
              </div>
              <span className="badge badge-neutral" style={{ fontSize: '0.45rem' }}>temporal/spatial only</span>
            </div>
            <div className="flex flex-col" style={{ padding: '0.75rem' }}>
              {configuredCameraIds.length < 2 ? (
                <div className="flex flex-col gap-1">
                  <span className="text-warning text-sm font-display">{configuredCameraIds.length === 1 ? 'SECOND SOURCE REQUIRED' : 'ADD CAMERA SOURCES'}</span>
                  <span className="text-xs text-muted">{configuredCameraIds.length === 1 ? 'Load a second source to enable cross-camera event correlation.' : 'Load camera sources to enable cross-camera event correlation.'}</span>
                </div>
              ) : activeCameraIds.length < 2 ? (
                <div className="flex flex-col gap-1"><span className="text-warning text-sm font-display">TWO SOURCES LOADED — BOTH ANALYSES MUST BE LIVE</span><span className="text-xs text-muted">Start both analyses to enable temporal/spatial correlation.</span></div>
              ) : effectiveCorrelation?.status === 'CORROBORATED' ? (
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className="text-ok text-lg">&#10003;</span>
                    <span className="text-sm font-display text-ok">
                      Corroborated by{' '}
                      <span className="font-bold">{effectiveCorrelation.secondary_camera_id || 'second camera'}</span>
                    </span>
                  </div>
                  <div className="flex gap-4 text-xs font-body text-muted">
                    <span>RULE MATCH</span>
                    {effectiveCorrelation.time_delta_seconds != null && (
                      <span>Δt = <span className="text-main">{Number(effectiveCorrelation.time_delta_seconds).toFixed(1)}s</span> apart</span>
                    )}
                    {effectiveCorrelation.distance_m != null && (
                      <span><span className="text-main">{Number(effectiveCorrelation.distance_m).toFixed(0)}m</span> separation</span>
                    )}
                    {effectiveCorrelation.expected_time_seconds != null && <span>expected <span className="text-main">{Number(effectiveCorrelation.expected_time_seconds).toFixed(1)}s</span></span>}
                    {effectiveCorrelation.corroboration_score != null && <span>score <span className="text-main">{Number(effectiveCorrelation.corroboration_score).toFixed(3)}</span></span>}
                    {effectiveCorrelation.appearance_similarity != null && <span>appearance <span className="text-main">{Number(effectiveCorrelation.appearance_similarity).toFixed(3)}</span></span>}
                  </div>
                  <span className="text-[10px] text-muted italic mt-1">Same detection class appeared at a spatially-plausible camera within expected travel time. No identity re-id claimed.</span>
                </div>
              ) : effectiveCorrelation && ['OUTSIDE_TIME_WINDOW', 'INCOMPATIBLE_EVENT_TYPES', 'STALE_SESSION', 'CAMERAS_NOT_RELATED', 'NO_MATCH', 'INSUFFICIENT_EVIDENCE'].includes(effectiveCorrelation.status) ? (
                <div className="flex items-start gap-2">
                  <span className="text-warning text-base">&#9888;</span>
                  <div className="flex flex-col">
                    <span className="text-sm font-display text-warning">NOT CORROBORATED · {effectiveCorrelation.status.replace(/_/g, ' ')}</span>
                    <span className="text-xs text-muted">Latest persisted candidate was evaluated against the configured camera relationship and temporal window.</span>
                  </div>
                </div>
              ) : effectiveCorrelation?.status === 'WAITING_FOR_SECOND_CAMERA' || effectiveCorrelation?.status === 'WAITING' ? (
                <div className="flex flex-col gap-2">
                  <span className="text-sm font-display text-warning">● MONITORING TWO CAMERAS</span>
                  <span className="text-xs text-muted">NO CURRENT-RUN CORROBORATED PAIR YET · correlation window: {effectiveCorrelation?.correlation_window_seconds == null ? 'NOT REPORTED' : `${effectiveCorrelation.correlation_window_seconds}s`}.</span>
                </div>
              ) : latestEvent ? (
                <div className="flex items-start gap-2"><span className="text-warning text-base">&#9888;</span><span className="text-xs text-muted">NO CORROBORATION / INSUFFICIENT EVIDENCE — no qualifying second-camera event is available.</span></div>
              ) : (
                <span className="text-xs text-muted">NO CURRENT-RUN CORROBORATED PAIR YET</span>
              )}
            </div>
          </div>

          <div className="dashboard-fleet-card dashboard-fleet-card-left card">
            <div className="card-header">
              <span className="card-title">System Fleet Health</span>
              <span className="badge badge-neutral" style={{ fontSize: '0.45rem' }}>{activeCameraIds.length} Active / {fleetHealth.length} Registered</span>
            </div>
            <div className="overflow-y-auto custom-scrollbar flex flex-col gap-2" style={{ padding: '0.75rem' }}>
              {cameraInventoryRestoring ? <div className="state-empty-sub">RESTORING CAMERA INVENTORY</div> : configuredCameraIds.length === 0 && <div className="state-empty-sub">WAITING FOR SOURCE</div>}
              {fleetHealth.map((node) => {
                const cameraSource = slotSources[node.camera_id];
                const startupKey = node.camera_id === 'cam-border-01' ? 'camBorder01' : node.camera_id === 'cam-checkpoint-01' ? 'camCheckpoint01' : null;
                const operational = deriveCameraOperationalState({ nodeStatus: startupKey ? startupReadiness[startupKey]?.status : null, sourceState: cameraSource, telemetry: scopedLiveTracks[node.camera_id], now });
                return <div key={node.camera_id} className="flex justify-between items-center border rounded p-2" style={{ borderColor: 'var(--border-color)' }}><span className="font-display text-main" style={{ fontSize: '.7rem' }}>{node.name || node.camera_id}</span><span className="text-muted" style={{ fontSize: '.6rem' }}>NODE {operational.node} · ANALYSIS {operational.analysis}</span></div>;
              })}
            </div>
          </div>

        </div>

        {/* Right Column */}
        <div className="dashboard-right-column flex-col h-full" style={{ flex: 2, display: 'flex', gap: '0.75rem' }}>
          <div className="dashboard-reliability-card card">
            <div className="card-header">
              <div><span className="card-title">Reliability Decision Pipeline</span><span className="dashboard-events-subtitle">{reliabilityScopeCameraId ? `Camera: ${cameraModels.find((camera) => camera.cameraId === reliabilityScopeCameraId)?.friendlyName || reliabilityScopeCameraId}${!activeCameraIds.includes(reliabilityScopeCameraId) ? ` · SOURCE LOADED · ANALYSIS ${lifecycleStatus(slotSources[reliabilityScopeCameraId], scopedLiveTracks[reliabilityScopeCameraId], now) === 'COMPLETED' ? 'COMPLETED' : 'PAUSED'}` : ''}` : cameraInventoryRestoring ? 'RESTORING CAMERA CONFIGURATION' : 'WAITING FOR SOURCE'}</span></div>
              {configuredCameraIds.length > 1 && <select aria-label="Reliability camera" value={reliabilityScopeCameraId || ''} onChange={(event) => setReliabilityCameraId(event.target.value)}>{configuredCameraIds.map((cameraId) => <option key={cameraId} value={cameraId}>{cameraModels.find((camera) => camera.cameraId === cameraId)?.friendlyName || cameraId}</option>)}</select>}
              <ShieldCheck size={14} className="text-muted" />
            </div>

            <div className="flex flex-col relative" style={{ gap: '0.5rem', padding: '0.75rem' }}>
              <LogicGate
                num={1} title="Camera Health (hard override)"
                active={!!reliabilityEvent}
                stats={
                  healthState ? (
                    <>
                      <div className="flex-col"><span className="text-xs text-muted">STATE</span>
                        <span className={`text-sm ${healthState === 'OK' ? 'text-ok' : healthState === 'DEGRADED' ? 'text-warning' : 'text-danger'}`}>
                          {healthState}
                        </span>
                      </div>
                      {healthState === 'FAILED' && parsed?.kind === 'abstain' && (
                        <div className="flex-col"><span className="text-xs text-muted">REASON</span><span className="text-sm text-danger">{parsed.healthReason}</span></div>
                      )}
                    </>
                  ) : (
                    <span className="text-xs text-muted">{!reliabilityScopeCameraId ? 'Waiting for a real event…' : !activeCameraIds.includes(reliabilityScopeCameraId) ? lifecycleStatus(slotSources[reliabilityScopeCameraId], scopedLiveTracks[reliabilityScopeCameraId], now) === 'COMPLETED' ? 'No reliability decision was generated for the completed current run.' : 'No current-run reliability decision — analysis paused.' : liveTelemetry ? 'N/A — no reliability event for current telemetry' : 'Waiting for a real event…'}</span>
                  )
                }
              />
              <LogicGate
                num={2} title="Scene Condition"
                active={!!reliabilityEvent}
                stats={
                  sceneCondition ? (
                    <>
                      <span className="text-xs text-muted">Illumination Profile</span>
                      <span className="text-xs border px-1 rounded bg-elevated">{SCENE_CONDITION_LABELS[sceneCondition] || sceneCondition}</span>
                    </>
                  ) : (
                    <span className="text-xs text-muted">{!reliabilityScopeCameraId ? 'Waiting for a real event…' : !activeCameraIds.includes(reliabilityScopeCameraId) ? lifecycleStatus(slotSources[reliabilityScopeCameraId], scopedLiveTracks[reliabilityScopeCameraId], now) === 'COMPLETED' ? 'No scene decision was generated for the completed current run.' : 'No current-run scene decision — analysis paused.' : liveTelemetry ? 'N/A — no scene decision for current telemetry' : 'Waiting for a real event…'}</span>
                  )
                }
              />
              <LogicGate
                num={3} title="Reliability Factors"
                active={!!reliabilityEvent}
                stats={
                  parsed?.kind === 'scored' ? (
                    <div className="flex-col w-full">
                      {/* Not `grid grid-cols-4` — inert class, see docs/LIMITATIONS.md */}
                      <div className="w-full mb-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem' }}>
                        {[
                          ['D', parsed.d], ['T', parsed.t], ['S', parsed.s], ['H', parsed.h],
                        ].map(([label, value]) => (
                          <div key={label} className="flex-col items-center text-center">
                            <span className="text-xs text-muted block">{label}</span>
                            <span className="text-sm block">{value == null ? 'NOT REPORTED' : value.toFixed(2)}</span>
                          </div>
                        ))}
                      </div>
                      <div className="flex justify-between w-full mb-1">
                        <span className="text-xs text-muted">R SCORE</span>
                        <span className="text-xs text-muted">THRESHOLD</span>
                      </div>
                      <div className="flex justify-between w-full">
                        <span className={`text-sm font-bold ${parsed.aboveThreshold ? 'text-ok' : 'text-warning'}`}>{parsed.r == null ? 'NOT REPORTED' : parsed.r.toFixed(3)}</span>
                        <span className="text-sm">{parsed.threshold == null ? 'THRESHOLD NOT REPORTED' : parsed.threshold.toFixed(3)}</span>
                      </div>
                      <div className="w-full h-1 bg-dark mt-2 rounded overflow-hidden">
                        <div className={`h-full ${parsed.aboveThreshold ? 'bg-ok' : 'bg-warning'}`} style={{ width: `${parsed.r == null ? 0 : Math.min(parsed.r * 100, 100)}%` }}></div>
                      </div>
                      {parsed.degraded && <span className="text-xs text-warning mt-1">Flagged: DEGRADED camera context</span>}
                    </div>
                  ) : parsed?.kind === 'abstain' ? (
                    <span className="text-xs text-muted">Gate 1 override — R was never computed for this event</span>
                  ) : (
                    <span className="text-xs text-muted">{!reliabilityScopeCameraId ? 'Waiting for a real event…' : !activeCameraIds.includes(reliabilityScopeCameraId) ? lifecycleStatus(slotSources[reliabilityScopeCameraId], scopedLiveTracks[reliabilityScopeCameraId], now) === 'COMPLETED' ? 'No reliability decision was generated for the completed current run.' : 'No current-run reliability decision — analysis paused.' : liveTelemetry ? 'N/A — reliability is emitted only with a processed event' : 'Waiting for a real event…'}</span>
                  )
                }
              />
            </div>

            {/* This is a live status readout, not an action — it was
                markup as a <button> with no onClick and no disabled
                attribute, so it rendered with a pointer cursor and hover
                states implying it did something on click when it never
                did. Changed to a <div role="status"> — same visual
                treatment, honestly non-interactive. */}
            <div className="mt-auto" style={{ marginTop: 'auto', padding: '0 0.75rem 0.75rem' }}>
              {decisionMeta ? (
                <div role="status" className={`w-full border rounded font-display tracking-widest flex items-center justify-center ${decisionMeta.colorClass}`} style={{ padding: '0.5rem 0', gap: '0.5rem', fontSize: '0.75rem' }}>
                  <decisionMeta.icon size={14} /> [{decisionMeta.label}] · {lifecycleStatus(slotSources[reliabilityScopeCameraId], scopedLiveTracks[reliabilityScopeCameraId], now) === 'COMPLETED' ? `LAST RECORDED DECISION FOR THIS RUN · ${String(reliabilityEvent?.event_id || reliabilityEvent?.id || '').slice(0, 8)}` : 'CURRENT-RUN DECISION'}
                </div>
              ) : (
                <div role="status" className="w-full border border-color text-muted rounded font-display tracking-widest flex items-center justify-center opacity-60" style={{ padding: '0.5rem 0', gap: '0.5rem', fontSize: '0.75rem' }}>
                  <HelpCircle size={14} /> [AWAITING CURRENT-RUN DECISION]
                </div>
              )}
            </div>
          </div>

          {/* Not `grid grid-cols-3` — inert class, see docs/LIMITATIONS.md */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
            <StatusPill 
              title="DETECTED" desc="Reliable detection confirmed" 
              type="detected" active={reliabilityEvent?.decision_state === 'DETECTED'} />
            <StatusPill 
              title="UNCERTAIN" desc="Confidence < Threshold" 
              type="uncertain" active={reliabilityEvent?.decision_state === 'UNCERTAIN'} />
            <StatusPill 
              title="ABSTAIN" desc="System Unreliable" 
              type="abstain" active={reliabilityEvent?.decision_state === 'ABSTAIN'} />
          </div>
          
          {/* System Fleet Health Widget */}
          <div className="dashboard-fleet-card card flex-grow">
             <div className="card-header">
                <span className="card-title">System Fleet Health</span>
                <span className="badge badge-neutral" style={{ fontSize: '0.45rem' }}>{fleetHealth.length} Nodes</span>
             </div>
             <div className="overflow-y-auto custom-scrollbar flex flex-col gap-2 flex-grow" style={{ padding: '0.75rem' }}>
               {fleetHealth.length === 0 && <div className="state-empty-sub">Health data unavailable</div>}
               {fleetHealth.map(node => {
                 const lastPingMs = node.last_ping ? Date.parse(node.last_ping) : NaN;
                 const nodeFresh = Number.isFinite(lastPingMs) && now - lastPingMs < 30000;
                 const nodeState = nodeFresh ? node.health_state : (node.last_ping ? 'OFFLINE' : 'UNKNOWN');
                 let color = 'text-warning';
                 let bgColor = 'bg-[rgba(245,158,11,0.05)]';
                 if (nodeState === 'FAILED' || nodeState === 'OFFLINE') {
                   color = 'text-danger';
                   bgColor = 'bg-[rgba(239,68,68,0.05)]';
                 } else if (nodeFresh && node.health_state === 'OK') {
                   color = 'text-ok';
                   bgColor = 'bg-[rgba(34,211,164,0.05)]';
                 }

                 return (
                   <div key={node.camera_id} className={`flex flex-col border rounded p-2 ${bgColor}`} style={{ borderColor: `var(--color-${color.replace('text-','')})` }}>
                     <div className="flex justify-between items-center mb-1">
                       <span className={`font-display ${color}`} style={{ fontSize: '0.65rem' }}>{node.name}</span>
                       <span className={`font-display ${color}`} style={{ fontSize: '0.5rem' }}>{nodeState}</span>
                     </div>
                     <div className="flex justify-between text-muted" style={{ fontSize: '0.55rem', fontFamily: 'var(--font-mono)' }}>
                       <span>FPS: {nodeFresh && Number.isFinite(node.fps) ? node.fps.toFixed(1) : 'N/A'}</span>
                       <span>CPU: {nodeFresh && Number.isFinite(node.cpu_percent) ? `${node.cpu_percent.toFixed(1)}%` : 'N/A'}</span>
                       <span>Uptime: {nodeFresh && Number.isFinite(node.uptime_seconds) ? `${Math.floor(node.uptime_seconds / 3600)}h` : 'N/A'}</span>
                     </div>
                   </div>
                 );
               })}
             </div>
          </div>
        </div>

      </div>
    </div>
  );
}
