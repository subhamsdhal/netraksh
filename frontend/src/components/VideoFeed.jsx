/**
 * NETRAKSH — LiveVideoFeed Component
 *
 * Renders a video element with:
 *   - Accurate letterbox-aware coordinate mapping for bounding boxes
 *   - An SVG overlay that draws tactical track boxes at pixel-perfect positions
 *   - A compact analyzed/source-preview mode control
 *   - Graceful fallback states for sensor failure / fog / offline scenarios
 *
 * SECURITY: This component receives pre-validated track data from the backend
 * WebSocket; it never executes dynamic content from track payloads.
 *
 * COORDINATE SYSTEM:
 *   Bounding box values (bbox_x, bbox_y, bbox_w, bbox_h) are normalised
 *   fractions [0..1] relative to the original camera frame resolution.
 *   The video element uses object-fit:contain, which letterboxes/pillarboxes
 *   the frame inside the container. This component measures the actual rendered
 *   video rect (not the container rect) via a ResizeObserver + intrinsic
 *   dimensions so SVG paths map 1-to-1 with the on-screen pixels of the frame.
 */
import { useMemo, useState, useEffect, useRef, useCallback } from 'react';
import { CameraOff, CloudFog, AlertTriangle, Upload, Activity } from 'lucide-react';
import { authFetch } from '../services/auth';
import { frameResponseMatchesTelemetry } from '../utils/dashboardScope';
import {
  acceptedAnalyzedTimeline,
  analyzedSampleAcceptance,
  analyzedSampleIsNewer,
  analyzedSampleMatchesScope,
  containedMediaRect,
} from '../utils/analyzedPlayback';
import {
  replayTimelineAssessment,
} from '../utils/trackingTimeline';

// ─── Threat-aware colour palette ────────────────────────────────────────────
//
// Colour meaning (matches NETRAKSH threat doctrine):
//   CRITICAL / SEVERE  → Crimson red, thick stroke, pulsing label (WL match)
//   FRIENDLY / CLEARED → Cyan  (explicit friendly tag from operator)
//   ELEVATED           → Amber (watchlist but not highest threat)
//   DEFAULT / UNKNOWN  → Neon green (no identity match)
//
// The track payload may carry:
//   track.threat_level   — 'CRITICAL' | 'SEVERE' | 'ELEVATED' | null
//   track.identity_match — true/false (set when backend WL match fires)
//   track.is_friendly    — true/false (operator-cleared)

const THREAT_PALETTE = {
  // Watchlist confirmed hit — red, thick, pulsing
  CRITICAL: {
    stroke: '#ef4444',
    strokeWidth: 2.5,
    fill: 'rgba(239,68,68,0.12)',
    labelFill: '#ef4444',
    labelText: '#fff',
    pulse: true,
    glowColor: 'rgba(239,68,68,0.6)',
  },
  SEVERE: {
    stroke: '#f97316',
    strokeWidth: 2.5,
    fill: 'rgba(249,115,22,0.10)',
    labelFill: '#f97316',
    labelText: '#fff',
    pulse: true,
    glowColor: 'rgba(249,115,22,0.55)',
  },
  // Watchlist match but lower threat tier
  ELEVATED: {
    stroke: '#fbbf24',
    strokeWidth: 1.5,
    fill: 'rgba(251,191,36,0.08)',
    labelFill: '#fbbf24',
    labelText: '#000',
    pulse: false,
    glowColor: 'rgba(251,191,36,0.45)',
  },
  // Operator-cleared friendly
  FRIENDLY: {
    stroke: '#22d3ee',
    strokeWidth: 1.5,
    fill: 'rgba(34,211,238,0.07)',
    labelFill: '#22d3ee',
    labelText: '#000',
    pulse: false,
    glowColor: 'rgba(34,211,238,0.4)',
  },
  // Default — no identity information
  UNKNOWN: {
    stroke: '#4ade80',
    strokeWidth: 1.5,
    fill: 'rgba(74,222,128,0.08)',
    labelFill: '#4ade80',
    labelText: '#000',
    pulse: false,
    glowColor: 'rgba(74,222,128,0.5)',
  },
};

/**
 * Returns the correct colour config for a track based on threat level and
 * identity match flags embedded in the telemetry payload.
 *
 * @param {object} track - Track object from live_telemetry payload.
 * @param {number}  trackId - Numeric track ID (used for fallback palette rotation).
 */
function getThreatPalette(track, trackId) {
  if (track?.is_friendly) return THREAT_PALETTE.FRIENDLY;
  if (track?.identity_match || track?.threat_level) {
    const level = (track.threat_level || '').toUpperCase();
    if (level === 'CRITICAL') return THREAT_PALETTE.CRITICAL;
    if (level === 'SEVERE') return THREAT_PALETTE.SEVERE;
    if (level === 'ELEVATED') return THREAT_PALETTE.ELEVATED;
    // identity_match=true but no explicit level → treat as ELEVATED
    if (track.identity_match) return THREAT_PALETTE.ELEVATED;
  }
  // Fallback for unidentified tracks: cycle through green shades by track ID
  // so multiple simultaneous unknown tracks are visually distinguishable.
  const FALLBACK_GREENS = [
    THREAT_PALETTE.UNKNOWN,
    { ...THREAT_PALETTE.UNKNOWN, stroke: '#34d399', labelFill: '#34d399', glowColor: 'rgba(52,211,153,0.45)' },
    { ...THREAT_PALETTE.UNKNOWN, stroke: '#6ee7b7', labelFill: '#6ee7b7', glowColor: 'rgba(110,231,183,0.4)' },
  ];
  return FALLBACK_GREENS[Math.abs(trackId ?? 0) % FALLBACK_GREENS.length];
}


// ─── Scenario fallback overlays ───────────────────────────────────────────────
function ScenarioOverlay({ scenario }) {
  if (scenario === 'normal') return null;

  const configs = {
    fog: {
      icon: CloudFog,
      label: 'DENSE FOG CONDITION',
      sub: 'Scene Classifier: FOG_RAIN | IR fallback active',
      color: '#94a3b8',
      bg: 'rgba(148,163,184,0.12)',
      border: 'rgba(148,163,184,0.3)',
    },
    sensor_failure: {
      icon: CameraOff,
      label: 'SENSOR FAILURE',
      sub: 'Gate 1 hard-override → ABSTAIN | Camera health: FAILED',
      color: '#ef4444',
      bg: 'rgba(239,68,68,0.1)',
      border: 'rgba(239,68,68,0.4)',
    },
    offline: {
      icon: AlertTriangle,
      label: 'SYSTEM OFFLINE',
      sub: 'SyncClient paused | Events queuing locally',
      color: '#fbbf24',
      bg: 'rgba(251,191,36,0.1)',
      border: 'rgba(251,191,36,0.35)',
    },
  };

  const cfg = configs[scenario];
  if (!cfg) return null;
  const Icon = cfg.icon;

  return (
    <div
      style={{
        position: 'absolute', inset: 0, zIndex: 15,
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        gap: '0.5rem', pointerEvents: 'none',
      }}
    >
      <Icon size={32} style={{ color: cfg.color }} />
      <span style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', letterSpacing: '0.1em', color: cfg.color, fontWeight: 700 }}>
        {cfg.label}
      </span>
      <span style={{ fontFamily: 'var(--font-body)', fontSize: '0.6rem', color: cfg.color, opacity: 0.75, textAlign: 'center', padding: '0 1rem' }}>
        {cfg.sub}
      </span>
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────
export default function VideoFeed({
  liveTracksData,
  telemetryStatus = 'WAITING',
  cameraId,
  playbackEnded = false,
  demoScenario = 'normal',
  mediaUrl,
  isUploading,
  uploadStage = null,
  uploadProgress = null,
  uploadError,
  onVideoEnded,
  onStartAnalysis,
  onPauseAnalysis,
  sourceMode,
  expectedSessionId,
  expectedGeneration = null,
  expectedSourceGeneration = null,
  completedTimeline = [],
  completedSummary = null,
  completedSummaryLoading = false,
  sourceRunState,
  sourceRestoring = false,
  onAnalyzedSample,
}) {
  const containerRef = useRef(null);
  const videoRef = useRef(null);
  const previewRef = useRef(null);
  const svgRef = useRef(null);
  const trackingTimelineRef = useRef([]);
  const trackingRunRef = useRef(null);
  const playbackCursorRef = useRef(0);

  // Measured geometry of the letterboxed video frame within its container.
  const [videoRect, setVideoRect] = useState({
    left: 0, top: 0, width: 0, height: 0, cw: 0, ch: 0, vw: 0, vh: 0,
  });

  // Source preview remains truthful while a run is starting. The first exact,
  // decodable frame for each new run promotes the view to analyzed/HUD once.
  const [hudVisible, setHudVisible] = useState(true);
  const [trackingModeActive, setTrackingModeActive] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const [analyzedFrameUrl, setAnalyzedFrameUrl] = useState(null);
  const [, setAnalyzedFrameStatus] = useState('WAITING FOR FIRST ANALYZED FRAME');
  const [displayedSample, setDisplayedSample] = useState(null);
  const displayedSampleRef = useRef(null);
  const onAnalyzedSampleRef = useRef(onAnalyzedSample);
  const promotedRunRef = useRef(null);
  const manualSourceRunRef = useRef(null);
  const sourcePreviewSelectedRef = useRef(false);
  const currentRunRef = useRef(null);
  const isDurableSource = sourceMode === 'durable';
  const trackingCapable = isDurableSource && Boolean(mediaUrl);
  const completedRun = String(sourceRunState || '').toUpperCase() === 'COMPLETED';
  const replayAssessment = useMemo(
    () => replayTimelineAssessment(completedTimeline, completedSummary || {}),
    [completedTimeline, completedSummary],
  );
  const useTrackingTimeline = trackingCapable && trackingModeActive;
  const analyzedViewAvailable = Boolean(mediaUrl || analyzedFrameUrl || trackingModeActive);
  const requestHudFrame = !trackingCapable && !useTrackingTimeline && (isDurableSource || hudVisible);
  const hasStoredDurableSource = isDurableSource && Boolean(expectedSessionId);
  const uploadLabel = uploadStage === 'UPLOADING'
    ? `UPLOADING${Number.isFinite(uploadProgress) ? ` ${uploadProgress}%` : ''}`
    : uploadStage === 'PREPARING'
      ? 'VALIDATING & STORING VIDEO'
      : 'PREPARING VIDEO';
  const showAnalyzedFrame = Boolean(
    analyzedFrameUrl
    && hudVisible
    && !useTrackingTimeline
    && ['LIVE', 'STALE', 'COMPLETED'].includes(telemetryStatus)
  );

  const viewState = !mediaUrl && !analyzedFrameUrl
    ? 'NO_SOURCE'
    : isUploading
      ? 'UPLOADING'
      : completedRun
        ? completedSummaryLoading
          ? 'COMPLETED_REPLAY_LOADING'
          : replayAssessment.ready && trackingModeActive
            ? 'COMPLETED_REPLAY_READY'
            : 'COMPLETED_REPLAY_UNAVAILABLE'
    : useTrackingTimeline && hudVisible
          ? 'ANALYZED_SYNC'
          : telemetryStatus === 'LIVE' || ['ACTIVE', 'LIVE', 'RUNNING', 'WAKING', 'STARTING'].includes(String(sourceRunState || '').toUpperCase())
            ? 'WAITING_FOR_FIRST_HUD_SAMPLE'
            : 'SOURCE_PREVIEW';
  const viewBadge = {
    COMPLETED_REPLAY_LOADING: 'LOADING HUD',
    COMPLETED_REPLAY_READY: 'ANALYZED REPLAY',
    COMPLETED_REPLAY_UNAVAILABLE: 'HUD UNAVAILABLE',
    ANALYZED_SYNC: 'ANALYZED SYNC',
    WAITING_FOR_FIRST_HUD_SAMPLE: 'WAITING FOR HUD',
    SOURCE_PREVIEW: 'SOURCE PREVIEW',
  }[viewState] || null;

  useEffect(() => { onAnalyzedSampleRef.current = onAnalyzedSample; }, [onAnalyzedSample]);

  const sourceSessionId = liveTracksData?.stream_id || null;
  const analysisSessionId = liveTracksData?.analysis_session_id || null;
  const telemetryGeneration = liveTracksData?.analysis_generation;
  const scopeMatches = analyzedSampleMatchesScope(liveTracksData, {
    cameraId,
    streamId: expectedSessionId || sourceSessionId,
    analysisGeneration: expectedGeneration,
    sourceGeneration: expectedSourceGeneration,
  });
  const runIdentity = scopeMatches && cameraId && analysisSessionId && Number.isFinite(liveTracksData?.frame_index)
    ? `${cameraId}:${sourceSessionId || expectedSessionId || 'source'}:${analysisSessionId}:${telemetryGeneration ?? expectedGeneration ?? 'generation'}`
    : null;

  useEffect(() => {
    promotedRunRef.current = null;
    manualSourceRunRef.current = null;
    sourcePreviewSelectedRef.current = false;
    currentRunRef.current = null;
    trackingRunRef.current = null;
    playbackCursorRef.current = 0;
    trackingTimelineRef.current = [];
    setHudVisible(true);
    setTrackingModeActive(false);
    displayedSampleRef.current = null;
    setDisplayedSample(null);
    onAnalyzedSampleRef.current?.(null);
  }, [cameraId, sourceMode, expectedSessionId, expectedGeneration, expectedSourceGeneration]);

  useEffect(() => {
    if (!completedRun || !replayAssessment.ready) {
      if (completedRun && !completedSummaryLoading) {
        trackingRunRef.current = null;
        trackingTimelineRef.current = [];
        setTrackingModeActive(false);
        setHudVisible(false);
      }
      return;
    }
    const first = completedTimeline[0];
    const scope = {
      cameraId,
      streamId: expectedSessionId,
      analysisSessionId: first.analysis_session_id,
      analysisGeneration: expectedGeneration,
      sourceGeneration: expectedSourceGeneration,
    };
    const restored = acceptedAnalyzedTimeline(completedTimeline, scope);
    if (!restored.length) {
      trackingRunRef.current = null;
      trackingTimelineRef.current = [];
      setTrackingModeActive(false);
      setHudVisible(false);
      return;
    }
    trackingRunRef.current = restored[0].analysis_session_id;
    trackingTimelineRef.current = restored;
    playbackCursorRef.current = 0;
    setTrackingModeActive(true);
    setHudVisible(true);
  }, [cameraId, completedRun, completedSummaryLoading, completedTimeline, expectedGeneration, expectedSessionId, expectedSourceGeneration, replayAssessment.ready]);

  useEffect(() => {
    if (!runIdentity || currentRunRef.current === runIdentity) return;
    currentRunRef.current = runIdentity;
    setHudVisible(true);
    displayedSampleRef.current = null;
    setDisplayedSample(null);
    onAnalyzedSampleRef.current?.(null);
  }, [runIdentity]);

  useEffect(() => {
    if (!trackingCapable) return undefined;
    const receive = (event) => {
      const sample = event.detail;
      if (!sample || sample.camera_id !== cameraId) return;
      if (expectedSessionId && sample.stream_id !== expectedSessionId) return;
      if (expectedGeneration != null
        && Number(sample.analysis_generation) !== Number(expectedGeneration)) return;
      if (expectedSourceGeneration != null
        && Number(sample.source_generation) !== Number(expectedSourceGeneration)) return;
      const incomingRun = sample.analysis_session_id || null;
      if (!incomingRun) return;
      const incomingRunIdentity = `${cameraId}:${sample.stream_id}:${incomingRun}:${sample.analysis_generation ?? 'generation'}`;
      if (trackingRunRef.current && trackingRunRef.current !== incomingRun) return;
      const scope = {
        cameraId,
        streamId: expectedSessionId || sample.stream_id,
        analysisSessionId: incomingRun,
        analysisGeneration: expectedGeneration,
        sourceGeneration: expectedSourceGeneration,
      };
      const accepted = analyzedSampleAcceptance(sample, scope);
      if (!accepted.accepted) return;
      currentRunRef.current = incomingRunIdentity;
      if (!trackingRunRef.current) {
        trackingRunRef.current = incomingRun;
        playbackCursorRef.current = 0;
        trackingTimelineRef.current = [];
        setHudVisible(true);
        setTrackingModeActive(true);
      }
      const receivedSample = { ...accepted.sample, browser_received_timestamp: Date.now() / 1000 };
      const nextTimeline = acceptedAnalyzedTimeline(
        [...trackingTimelineRef.current, receivedSample],
        { ...scope, analysisSessionId: trackingRunRef.current },
      );
      trackingTimelineRef.current = nextTimeline;
      if (!sourcePreviewSelectedRef.current && manualSourceRunRef.current !== incomingRunIdentity) setHudVisible(true);
      setTrackingModeActive(true);
    };
    window.addEventListener('netraksh-tracking-frame', receive);
    return () => window.removeEventListener('netraksh-tracking-frame', receive);
  }, [cameraId, completedRun, expectedSessionId, expectedGeneration, expectedSourceGeneration, trackingCapable]);

  // Explicit React playback state for scanner and UI
  const [isVideoPlaying, setIsVideoPlaying] = useState(false);

  // Fetch the exact bounded JPEG that produced this telemetry sample. The
  // backend requires the same session + frame index, so an independent video
  // clock can never masquerade as the analyzed frame.
  useEffect(() => {
    // stream_id binds telemetry to the selected durable upload. The frame
    // endpoint, however, is keyed by analysis_session_id + frame_index.
    // Keeping those identities separate prevents an old demo frame from
    // being displayed for a newly selected upload.
    const frameIndex = liveTracksData?.frame_index;
    if (!requestHudFrame) return undefined;
    if (!scopeMatches) return undefined;
    if (!cameraId || !analysisSessionId || !Number.isFinite(frameIndex) || !liveTracksData?.preview_available) return undefined;
    let cancelled = false;
    let nextUrl = null;
    let committed = false;
    const params = new URLSearchParams({
      analysis_session_id: analysisSessionId,
      frame_index: String(frameIndex),
      // The browser draws the HUD from the exact committed telemetry object.
      // Request the clean paired frame so boxes are never drawn twice.
      hud: 'false',
      cache_bust: `${analysisSessionId}:${frameIndex}:clean`,
    });
    authFetch(`/system/telemetry/frame/${encodeURIComponent(cameraId)}?${params.toString()}`)
      .then((response) => response.ok && frameResponseMatchesTelemetry(liveTracksData, response.headers) ? response.blob() : null)
      .then((blob) => {
        if (!blob || cancelled) return;
        nextUrl = URL.createObjectURL(blob);
        // Do not replace a valid FrameSnapshot until this exact response is
        // decodable. A failed candidate keeps the prior image and its paired
        // telemetry together instead of rendering a broken image.
        const candidate = new Image();
        candidate.onload = () => {
          if (cancelled) return;
          if (!analyzedSampleIsNewer(displayedSampleRef.current, liveTracksData)) {
            URL.revokeObjectURL(nextUrl);
            nextUrl = null;
            return;
          }
          setAnalyzedFrameUrl((previous) => {
            if (previous) URL.revokeObjectURL(previous);
            return nextUrl;
          });
          displayedSampleRef.current = liveTracksData;
          setDisplayedSample(liveTracksData);
          const shouldPresentHud = runIdentity && manualSourceRunRef.current !== runIdentity;
          onAnalyzedSampleRef.current?.(shouldPresentHud ? liveTracksData : null);
          console.info('[VideoFeed] ANALYZED SAMPLE DISPLAYED', {
            camera_id: liveTracksData.camera_id,
            stream_prefix: String(liveTracksData.stream_id || '').slice(0, 8),
            run_prefix: String(liveTracksData.analysis_session_id || '').slice(0, 8),
            analysis_generation: liveTracksData.analysis_generation ?? null,
            sequence: liveTracksData.sequence ?? null,
            frame_index: liveTracksData.frame_index,
            video_time: liveTracksData.video_time ?? null,
            processing_fps: liveTracksData.processing_fps ?? null,
            source_fps: liveTracksData.source_fps ?? liveTracksData.fps_declared ?? null,
            track_count: liveTracksData.track_count ?? null,
          });
          committed = true;
          setAnalyzedFrameStatus('ANALYZED LIVE STREAM');
          if (
            runIdentity
            && promotedRunRef.current !== runIdentity
            && manualSourceRunRef.current !== runIdentity
          ) {
            promotedRunRef.current = runIdentity;
            setHudVisible(true);
          }
        };
        candidate.onerror = () => {
          URL.revokeObjectURL(nextUrl);
          nextUrl = null;
          if (!cancelled) setAnalyzedFrameStatus('WAITING FOR NEXT ANALYZED FRAME');
        };
        candidate.src = nextUrl;
      })
      .catch(() => { if (!cancelled) setAnalyzedFrameStatus('WAITING FOR NEXT ANALYZED FRAME'); });
    return () => { cancelled = true; if (nextUrl && !committed) URL.revokeObjectURL(nextUrl); };
  }, [cameraId, liveTracksData, requestHudFrame, expectedSessionId, expectedGeneration, scopeMatches, runIdentity, analysisSessionId]);

  useEffect(() => {
    if (!['OFFLINE', 'DISCONNECTED'].includes(telemetryStatus)) return;
    setAnalyzedFrameUrl((previous) => {
      if (previous) URL.revokeObjectURL(previous);
      return null;
    });
  }, [telemetryStatus]);

  useEffect(() => {
    setAnalyzedFrameUrl((previous) => {
      if (previous) URL.revokeObjectURL(previous);
      return null;
    });
  }, [cameraId, sourceMode, expectedSessionId]);

  // ─── LOCAL DETERMINISTIC DEMO CACHE LOGIC ────────────────────────────────────
  const [demoCache, setDemoCache] = useState(null);
  const [demoMediaTime, setDemoMediaTime] = useState(null);

  useEffect(() => {
    if (sourceMode === 'legacy-demo' && mediaUrl && mediaUrl.includes('vtest.mp4')) {
      authFetch('/api/dashboard/video/demo-telemetry')
        .then(res => res.json())
        .then(data => {
          setDemoCache(data);
          console.log('[DemoCache] Loaded deterministic demo cache', data.length, 'frames');
        })
        .catch(err => console.error('[DemoCache] Failed to load telemetry cache:', err));
    } else {
      setDemoCache(null);
    }
  }, [mediaUrl, sourceMode]);

  // Refresh freshness state four times per second for RTSP.
  // For local demo cache, we must render at frame rate to ensure perfect zero-latency visual sync.
  // We use requestVideoFrameCallback if available for frame-perfect timestamps, fallback to requestAnimationFrame.
  useEffect(() => {
    const video = videoRef.current;
    if (demoCache && video && 'requestVideoFrameCallback' in video) {
      let rVFC = null;
      const callback = (_now, metadata) => {
        // metadata.mediaTime is the exact presentation timestamp of the currently painted frame
        setDemoMediaTime(metadata.mediaTime);
        rVFC = video.requestVideoFrameCallback(callback);
      };
      rVFC = video.requestVideoFrameCallback(callback);
      return () => {
        if (rVFC) video.cancelVideoFrameCallback(rVFC);
      };
    }
    if (demoCache && video) {
      let rafId;
      const loop = () => {
        setDemoMediaTime(video.currentTime);
        rafId = requestAnimationFrame(loop);
      };
      rafId = requestAnimationFrame(loop);
      return () => cancelAnimationFrame(rafId);
    }
    return undefined;
  }, [demoCache, mediaUrl]);

  /**
   * Compute the letterbox offsets.
   *
   * The video element fills its parent 100%×100% with object-fit:contain.
   * To find where the actual frame pixels sit we compare the container
   * aspect ratio with the intrinsic video aspect ratio:
   *   - If container is wider than the frame → pillarbox (black bars on sides)
   *   - If container is taller than the frame → letterbox (bars top/bottom)
   *
   * We also fall back gracefully when metadata hasn't loaded yet.
   */
  const updateRect = useCallback(() => {
    const container = containerRef.current;
    const media = showAnalyzedFrame ? previewRef.current : videoRef.current;
    if (!container || !media) return;

    const cr = container.getBoundingClientRect();
    const cw = cr.width;
    const ch = cr.height;
    // Prefer the authoritative browser media dimensions (what object-fit uses).
    // Fallback to telemetry dimensions only before the first frame loads.
    const vw = media.naturalWidth || media.videoWidth || displayedSample?.frame_width || liveTracksData?.frame_width || 1280;
    const vh = media.naturalHeight || media.videoHeight || displayedSample?.frame_height || liveTracksData?.frame_height || 720;

    if (vw === 0 || vh === 0) return;

    const rect = containedMediaRect(cw, ch, vw, vh);
    setVideoRect({ ...rect, cw, ch, vw, vh });
  }, [displayedSample?.frame_width, displayedSample?.frame_height, liveTracksData?.frame_width, liveTracksData?.frame_height, showAnalyzedFrame]);

  // Default analyzed playback is frame-locked. The browser video is paused,
  // sought to the accepted detector sample's source time, painted, and only
  // then are the sample, boxes and card metrics committed together.
  useEffect(() => {
    if (!useTrackingTimeline || !hudVisible) return undefined;
    const video = videoRef.current;
    if (!video) return undefined;
    let cancelled = false;
    let timer = null;
    let frameCallback = null;
    let pendingSeekListener = null;

    const commit = (sample) => {
      if (cancelled) return;
      const visibleSample = { ...sample, visible_timestamp: Date.now() / 1000 };
      displayedSampleRef.current = visibleSample;
      setDisplayedSample(visibleSample);
      setAnalyzedFrameStatus(completedRun ? 'ANALYZED REPLAY' : 'ANALYZED LIVE STREAM');
      onAnalyzedSampleRef.current?.(visibleSample);
      updateRect();
    };

    const painted = (sample, done) => {
      const finish = () => {
        commit(sample);
        done();
      };
      if ('requestVideoFrameCallback' in video) {
        frameCallback = video.requestVideoFrameCallback(finish);
      } else {
        requestAnimationFrame(finish);
      }
    };

    const pump = () => {
      if (cancelled) return;
      const timeline = trackingTimelineRef.current;
      const sample = timeline[playbackCursorRef.current];
      if (!sample) {
        if (completedRun) return;
        timer = setTimeout(pump, 40);
        return;
      }
      video.pause();
      const target = Math.max(0, Number(sample.video_time));
      const continueAfterPaint = () => {
        playbackCursorRef.current += 1;
        const next = trackingTimelineRef.current[playbackCursorRef.current];
        const sourceGap = next ? Math.max(0, Number(next.video_time) - target) : 0;
        const delay = completedRun ? Math.min(750, Math.max(80, sourceGap * 1000)) : 0;
        timer = setTimeout(pump, delay);
      };
      const onSeeked = () => {
        pendingSeekListener = null;
        painted(sample, continueAfterPaint);
      };
      if (Math.abs(Number(video.currentTime) - target) <= 0.002 && video.readyState >= 2) {
        painted(sample, continueAfterPaint);
      } else {
        pendingSeekListener = onSeeked;
        video.addEventListener('seeked', onSeeked, { once: true });
        video.currentTime = target;
      }
    };

    pump();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (pendingSeekListener) video.removeEventListener('seeked', pendingSeekListener);
      if (frameCallback != null && 'cancelVideoFrameCallback' in video) {
        video.cancelVideoFrameCallback(frameCallback);
      }
    };
  }, [completedRun, hudVisible, updateRect, useTrackingTimeline]);

  useEffect(() => {
    setVideoError(false);
    updateRect();
    const ro = new ResizeObserver(updateRect);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [updateRect, mediaUrl]);

  const activeTracks = useMemo(() => {
    if ((showAnalyzedFrame || useTrackingTimeline) && displayedSample?.tracks) return displayedSample.tracks;
    // For demo cache, prioritize rVFC exact mediaTime over the generic video.currentTime.
    // ADD +1 FRAME (1.0 / 30.0) LOOKAHEAD to compensate for the 1-frame DOM repaint delay, 
    // ensuring the SVG paints on screen exactly in sync with the video frame.
    const videoTime = demoMediaTime == null ? 0 : demoMediaTime + (1.0 / 30.0);

    // DEMO CACHE OVERRIDE (Explicit playback-time-driven for ZERO latency)
    if (demoCache && demoCache.length > 0) {
      // Fast linear search (cache is sorted monotonically)
      let closest = demoCache[0];
      let minDiff = Math.abs(closest.video_time - videoTime);
      for (let i = 1; i < demoCache.length; i++) {
        const diff = Math.abs(demoCache[i].video_time - videoTime);
        if (diff < minDiff) {
          minDiff = diff;
          closest = demoCache[i];
        } else if (diff > minDiff) {
          break; // Passed the closest point
        }
      }
      // Demo tolerance is tight because it is perfectly synced
      if (minDiff <= 0.1) return closest.tracks;
      return [];
    }

    // Never project asynchronous telemetry over an independently advancing
    // browser clock. Production boxes are paired with one exact analyzed JPEG.
    return [];
  }, [displayedSample, demoCache, demoMediaTime, showAnalyzedFrame, useTrackingTimeline]);

  /**
   * FIX A: Continuous Browser Playback-Time Sync
   * Synchronize the backend with the current browser time every 2 seconds
   * so Edge doesn't fall behind.
   */
  useEffect(() => {
    if (isDurableSource) return undefined;
    const video = videoRef.current;
    if (!video) return undefined;

    let intervalId = null;

    const syncTime = () => {
      // Continuously synchronize the exact video state to the backend
      if (video.ended || playbackEnded) {
        return; // Natural end: do not send pause heartbeat
      }
      if (!video.paused && demoScenario !== 'paused') {
        onStartAnalysis?.(video.currentTime);
      } else {
        onPauseAnalysis?.(video.currentTime);
      }
    };

    intervalId = setInterval(syncTime, 2000);

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [onStartAnalysis, onPauseAnalysis, playbackEnded, demoScenario, isDurableSource]);

  // ── Empty state — no media loaded ──────────────────────────────────────────
  if (!mediaUrl && !analyzedFrameUrl) {
    return (
      <div
        className="dashboard-video-feed w-full h-full flex flex-col items-center justify-center border rounded relative overflow-hidden"
        style={{ background: 'radial-gradient(circle at 50% 50%, #0c1a13 0%, #020617 100%)' }}
      >
        <div className="flex flex-col items-center z-10" style={{ gap: '1rem' }}>
          <div style={{
            width: '64px', height: '64px', borderRadius: '50%',
            background: 'rgba(74,222,128,0.15)',
            border: '2px solid rgba(74,222,128,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Upload size={28} style={{ color: 'var(--color-ok)' }} />
          </div>
          <span
            className="dashboard-video-title font-display font-bold text-main"
            style={{ fontSize: '1rem', letterSpacing: '0.1em' }}
          >
            {sourceRestoring
              ? 'RESTORING STORED SOURCE...'
              : isUploading
              ? uploadLabel
              : ['ACTIVATING', 'WAKING'].includes(sourceRunState)
                ? 'PREPARING CLOUD ANALYSIS'
                : sourceRunState === 'READY_TO_START'
                  ? 'VIDEO READY · STARTING AI WORKER'
                  : sourceRunState === 'COMPLETED' || telemetryStatus === 'COMPLETED'
                    ? 'SOURCE STORED · ANALYSIS COMPLETED'
                    : hasStoredDurableSource
                      ? telemetryStatus === 'LIVE' || ['STARTING', 'ACTIVE', 'LIVE', 'RUNNING'].includes(String(sourceRunState || '').toUpperCase())
                        ? 'SOURCE STORED · AWAITING CURRENT-RUN ANALYZED FRAME'
                        : 'SOURCE STORED · PREVIEW UNAVAILABLE FOR RESTORED SESSION'
                    : telemetryStatus === 'STALE' && liveTracksData
                      ? 'LAST TELEMETRY AVAILABLE · NOT LIVE'
                      : (sourceMode === 'durable' && expectedSessionId && !liveTracksData)
                        ? 'WAITING FOR FIRST ANALYZED FRAME'
                        : telemetryStatus === 'LIVE' && liveTracksData
                          ? 'TELEMETRY ACTIVE · LOCAL PLAYBACK OPTIONAL'
                          : 'NO VIDEO SOURCE'}
          </span>
          {sourceRestoring ? <span className="text-muted text-xs">VERIFYING DURABLE SOURCE AUTHORITY</span> : !isUploading && sourceMode === 'durable' && expectedSessionId ? <span className="text-muted text-xs">PREVIEW UNAVAILABLE FOR THIS RESTORED SESSION</span> : <span className="text-muted text-xs">Use ADD VIDEO in the camera header</span>}
          <span className="text-muted text-xs">SUPPORTED: MP4 · AVI · MOV · MKV · WEBM · M4V</span>
          {uploadError && <span className="text-danger text-xs text-center" role="alert">{uploadError}</span>}
        </div>
      </div>
    );
  }

  // ── Video player + SVG overlay ──────────────────────────────────────────────
  return (
    <div
      ref={containerRef}
      className="dashboard-video-feed w-full h-full relative border rounded overflow-hidden"
      style={{
        background: 'radial-gradient(circle at 50% 50%, #064e3b 0%, #020617 100%)',
        boxShadow: 'inset 0 0 50px rgba(0,0,0,0.8)',
      }}
    >
      {/* Durable cloud analysis is an ordered stream of exact clean frames.
          SVG boxes and card metrics use only the telemetry object committed
          with the currently decoded frame. */}
      {showAnalyzedFrame ? <img
        ref={previewRef}
        src={analyzedFrameUrl}
        alt={`Synchronized analyzed video frame for ${cameraId}`}
        onLoad={updateRect}
        style={{
          position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', zIndex: 0,
          filter: telemetryStatus === 'LIVE' ? 'none' : 'grayscale(0.7) brightness(0.55)',
        }}
      /> : mediaUrl ? <video
        ref={videoRef}
        src={mediaUrl}
        muted
        controls={!hudVisible}
        playsInline
        preload="metadata"
        onLoadedMetadata={(e) => {
          e.target.playbackRate = 1.0;
          if (isDurableSource && hudVisible) e.target.pause();
          updateRect();
          if (!isDurableSource && e.target.paused && !e.target.ended) onPauseAnalysis?.(e.target.currentTime);
        }}
        onPlay={(e) => {
          setIsVideoPlaying(true);
          if (!isDurableSource) onStartAnalysis?.(e.target.currentTime);
        }}
        onPause={(e) => {
          setIsVideoPlaying(false);
          if (!isDurableSource && !e.target.ended && !playbackEnded) {
            onPauseAnalysis?.(e.target.currentTime);
          }
        }}
        onSeeked={(e) => { if (!isDurableSource) onStartAnalysis?.(e.target.currentTime); }}
        onRateChange={(e) => {
          if (e.target.playbackRate !== 1.0) e.target.playbackRate = 1.0;
        }}
        onEnded={(e) => {
          setIsVideoPlaying(false);
          onVideoEnded?.(e);
        }}
        onError={() => {
          setVideoError(true);
          console.error('Unable to load the selected video');
        }}
        style={{
          position: 'absolute', inset: 0,
          width: '100%', height: '100%',
          /* object-fit:contain ensures no stretching; letterbox bars are black */
          objectFit: 'contain',
          zIndex: 0,
        }}
      /> : analyzedFrameUrl ? <img
        ref={previewRef}
        src={analyzedFrameUrl}
        alt={`Latest analyzed frame for ${cameraId}`}
        onLoad={updateRect}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', zIndex: 0 }}
      /> : null}
      {videoError && mediaUrl && !showAnalyzedFrame && (
        <div className="absolute inset-0 z-25 flex items-center justify-center bg-black/80 text-danger text-sm text-center px-4" role="alert">
          Unable to play this video in the browser.
        </div>
      )}



      {/* ── Scanline aesthetic effect ── */}
      <div className="scanline" style={{ zIndex: 5, pointerEvents: 'none', animationPlayState: isVideoPlaying ? 'running' : 'paused' }} />

      {/* ── SVG bounding-box overlay ──────────────────────────────────────────
          The SVG is sized to the full container (100%×100%) but all drawing
          coordinates are translated by the letterbox offsets so track boxes
          land precisely on the frame pixels — not on the black bars.
          Using SVG (vs absolutely-positioned divs) eliminates the sub-pixel
          clipping and z-index stacking issues that caused the previous
          "TRACK #16 clipping" bug.
      ─────────────────────────────────────────────────────────────────────── */}
      <svg
        ref={svgRef}
        aria-label="Detection-synchronized tracking overlay"
        data-frame-index={displayedSample?.frame_index ?? ''}
        data-source-time={Number.isFinite(displayedSample?.video_time) ? displayedSample.video_time : ''}
        style={{
          display: (showAnalyzedFrame || (useTrackingTimeline && hudVisible)) ? 'block' : 'none',
          position: 'absolute', inset: 0,
          width: '100%', height: '100%',
          zIndex: 10, pointerEvents: 'none',
          overflow: 'visible',
        }}
      >
        {activeTracks.map((ev) => {
          const normalizeTrackBBox = (track) => {
            if (track.bbox_x != null && track.bbox_y != null && track.bbox_w != null && track.bbox_h != null) {
              return {
                x: Math.max(0, Number(track.bbox_x)),
                y: Math.max(0, Number(track.bbox_y)),
                w: Math.min(1, Number(track.bbox_x) + Number(track.bbox_w)) - Math.max(0, Number(track.bbox_x)),
                h: Math.min(1, Number(track.bbox_y) + Number(track.bbox_h)) - Math.max(0, Number(track.bbox_y)),
              };
            }
            return null;
          };

          const norm = normalizeTrackBBox(ev);
          if (!norm) return null;

          // ── Threat-aware colour ──────────────────────────────────────
          const color = getThreatPalette(ev, ev.track_id);

          const isWatchlistHit = ev.identity_match || !!ev.threat_level;
          const isCritical = ['CRITICAL', 'SEVERE'].includes(
            (ev.threat_level || '').toUpperCase()
          );

          // Build the label: show subject name if a WL match is known
          const objectLabel = String(ev.object_class || ev.class_name || ev.detection_class || 'object').toUpperCase();
          const trackLabel = ev.identity_match && ev.subject_name
            ? `${ev.subject_name} [WL]`
            : `${objectLabel} · TRACK #${ev.track_id ?? '?'}`;

          // Map normalised [0..1] coords → container pixel coords
          const x = videoRect.left + norm.x * videoRect.width;
          const y = videoRect.top + norm.y * videoRect.height;
          const w = norm.w * videoRect.width;
          const h = norm.h * videoRect.height;

          // Label background metrics
          const labelFontSize = 9;
          const labelPadH = 5;
          const labelPadV = 2;
          const labelW = trackLabel.length * (labelFontSize * 0.62) + labelPadH * 2;
          const labelH = labelFontSize + labelPadV * 2;

          return (
            <g
              key={ev.track_id}
              data-track-id={ev.track_id ?? 'unknown'}
              data-track-class={ev.object_class || ev.class_name || ev.class || 'unknown'}
              data-bbox-x={norm.x}
              data-bbox-y={norm.y}
              data-bbox-w={norm.w}
              data-bbox-h={norm.h}
            >
              {/* Main bounding rectangle */}
              <rect
                x={x} y={y} width={w} height={h}
                fill={color.fill}
                stroke={color.stroke}
                strokeWidth={color.strokeWidth ?? 1.5}
                style={{
                  filter: `drop-shadow(0 0 ${isCritical ? '7' : '4'}px ${color.glowColor})`,
                  // Pulsing glow for critical WL hits via CSS animation on SVG element
                  animation: color.pulse ? 'wl-pulse 1.2s ease-in-out infinite' : 'none',
                }}
              />

              {/* Corner accent marks */}
              {[
                [x, y, 8, 0, 0, 8],
                [x + w, y, -8, 0, 0, 8],
                [x, y + h, 8, 0, 0, -8],
                [x + w, y + h, -8, 0, 0, -8],
              ].map(([cx, cy, dx1, dy1, dx2, dy2], i) => (
                <g key={i}>
                  <line x1={cx} y1={cy} x2={cx + dx1} y2={cy + dy1} stroke={color.stroke} strokeWidth={color.strokeWidth ?? 2} />
                  <line x1={cx} y1={cy} x2={cx + dx2} y2={cy + dy2} stroke={color.stroke} strokeWidth={color.strokeWidth ?? 2} />
                </g>
              ))}

              {/* Label pill */}
              <rect
                x={x} y={y - labelH}
                width={labelW} height={labelH}
                fill={color.labelFill}
                rx={2}
                style={{
                  animation: color.pulse ? 'wl-pulse-label 1.2s ease-in-out infinite' : 'none',
                }}
              />
              <text
                x={x + labelPadH}
                y={y - labelPadV - 1}
                fill={color.labelText}
                fontSize={labelFontSize}
                fontFamily="'Space Grotesk', ui-monospace, monospace"
                fontWeight={700}
                letterSpacing="0.06em"
                dominantBaseline="auto"
              >
                {trackLabel}
              </text>

              {/* WL badge icon (⚠) for watchlist hits */}
              {isWatchlistHit && (
                <text
                  x={x + w - 12}
                  y={y + 14}
                  fill={color.stroke}
                  fontSize={12}
                  fontFamily="system-ui"
                  style={{ filter: `drop-shadow(0 0 3px ${color.stroke})` }}
                >
                  ⚠
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* ── Scenario fallback overlay (fog / sensor failure / offline) ── */}
      <ScenarioOverlay scenario={demoScenario} />

      {['STALE', 'OFFLINE'].includes(telemetryStatus) && analyzedFrameUrl && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 18, pointerEvents: 'none',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(2,6,23,0.18)',
        }}>
          <span style={{
            padding: '0.45rem 0.75rem', border: '1px solid rgba(251,191,36,0.75)',
            background: 'rgba(2,6,23,0.88)', color: '#fbbf24', borderRadius: '0.25rem',
            fontFamily: 'var(--font-display)', fontSize: '0.7rem', letterSpacing: '0.09em',
          }}>
            LAST KNOWN FRAME · {telemetryStatus} TELEMETRY
          </span>
        </div>
      )}

      {hudVisible && displayedSample && (
        <div style={{
          position: 'absolute', left: '0.45rem', bottom: '0.45rem', zIndex: 20,
          padding: '0.25rem 0.45rem', border: '1px solid rgba(74,222,128,0.55)',
          background: 'rgba(2,6,23,0.86)', color: '#4ade80', borderRadius: '0.2rem',
          fontFamily: 'ui-monospace, monospace', fontSize: '0.55rem', letterSpacing: '0.07em',
          pointerEvents: 'none',
        }}>
          FRAME {displayedSample.frame_index} · {displayedSample.video_time.toFixed(2)}s
        </div>
      )}
      {!showAnalyzedFrame && !useTrackingTimeline && mediaUrl && isDurableSource && (
        <div style={{
          position: 'absolute', left: '0.45rem', bottom: '0.45rem', zIndex: 20,
          padding: '0.25rem 0.45rem', border: '1px solid rgba(56,189,248,0.55)',
          background: 'rgba(2,6,23,0.86)', color: '#38bdf8', borderRadius: '0.2rem',
          fontFamily: 'ui-monospace, monospace', fontSize: '0.55rem', letterSpacing: '0.07em',
          pointerEvents: 'none',
        }}>
          {analyzedFrameUrl
            ? 'SOURCE PREVIEW · ANALYZED SYNC AVAILABLE'
            : completedRun
              ? (completedSummaryLoading
                ? 'SOURCE REPLAY · LOADING ANALYZED HUD'
                : replayAssessment.ready
                  ? 'SOURCE PREVIEW · COMPLETED RUN · ANALYZED REPLAY AVAILABLE'
                  : 'SOURCE REPLAY · HUD NOT AVAILABLE FOR THIS HISTORICAL RUN')
              : 'SOURCE PREVIEW · WAITING FOR FIRST ANALYZED FRAME'}
        </div>
      )}

      {/* ── Corner HUD toggle button ── */}
      <button
        onClick={() => {
          if (!analyzedViewAvailable) return;
          setHudVisible((visible) => {
            const nextVisible = !visible;
            const activeRunIdentity = currentRunRef.current || runIdentity;
            if (!nextVisible && activeRunIdentity) manualSourceRunRef.current = activeRunIdentity;
            if (nextVisible) manualSourceRunRef.current = null;
            sourcePreviewSelectedRef.current = !nextVisible;
            if (nextVisible) playbackCursorRef.current = Math.max(0, trackingTimelineRef.current.length - 1);
            const video = videoRef.current;
            if (video) {
              if (nextVisible) video.pause();
              else video.play().catch(() => {});
            }
            onAnalyzedSampleRef.current?.(nextVisible ? displayedSampleRef.current : null);
            return nextVisible;
          });
        }}
        disabled={!analyzedViewAvailable}
        title={analyzedViewAvailable ? (hudVisible ? 'View source preview' : 'View analyzed frames') : viewBadge || 'Analyzed view unavailable'}
        data-playback-mode={hudVisible ? 'analyzed-sync' : 'source-preview'}
        data-view-state={viewState}
        aria-pressed={hudVisible}
        style={{
          position: 'absolute', top: '0.4rem', right: '0.4rem',
          zIndex: 20,
          background: viewState === 'COMPLETED_REPLAY_UNAVAILABLE' ? 'rgba(69,26,3,0.96)' : hudVisible ? 'rgba(6,78,59,0.96)' : 'rgba(2,6,23,0.96)',
          border: `1px solid ${viewState === 'COMPLETED_REPLAY_UNAVAILABLE' ? '#f59e0b' : hudVisible ? '#4ade80' : '#64748b'}`,
          borderRadius: '0.2rem',
          padding: '0.22rem 0.45rem',
          fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
          fontSize: '0.5rem', letterSpacing: '0.08em',
          color: viewState === 'COMPLETED_REPLAY_UNAVAILABLE' ? '#fbbf24' : hudVisible ? '#4ade80' : '#e2e8f0',
          cursor: 'pointer',
          lineHeight: '1.4',
          display: 'flex', alignItems: 'center', gap: '0.25rem',
        }}
      >
        <Activity size={8} /> {hudVisible ? 'VIEW SOURCE' : 'VIEW ANALYZED'}
      </button>

      {/* ── Telemetry Status Indicator ── */}
      {telemetryStatus !== undefined && (
        <div style={{
          position: 'absolute', top: '0.4rem', left: '0.4rem',
          zIndex: 20, display: 'flex', alignItems: 'center', gap: '0.3rem',
          background: 'rgba(0,0,0,0.55)',
          border: `1px solid ${
            telemetryStatus === 'LIVE' ? 'rgba(74,222,128,0.35)' :
            telemetryStatus === 'WAITING' ? 'rgba(251,191,36,0.35)' :
            telemetryStatus === 'COMPLETED' ? 'rgba(56,189,248,0.35)' :
            'rgba(239,68,68,0.35)'
          }`,
          borderRadius: '0.2rem', padding: '0.15rem 0.45rem',
          pointerEvents: 'none',
        }}>
          <span style={{
            width: '5px', height: '5px', borderRadius: '50%',
            background: 
              telemetryStatus === 'LIVE' ? '#4ade80' :
              telemetryStatus === 'WAITING' ? '#fbbf24' :
              telemetryStatus === 'COMPLETED' ? '#38bdf8' :
              '#ef4444',
            boxShadow: `0 0 5px ${
              telemetryStatus === 'LIVE' ? '#4ade80' :
              telemetryStatus === 'WAITING' ? '#fbbf24' :
              telemetryStatus === 'COMPLETED' ? '#38bdf8' :
              '#ef4444'
            }`,
            animation: telemetryStatus === 'LIVE' ? 'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite' : 'none',
            display: 'inline-block',
          }} />
          <span style={{
            fontFamily: 'ui-monospace, monospace',
            fontSize: '0.5rem', letterSpacing: '0.1em',
            color: 
              telemetryStatus === 'LIVE' ? 'rgba(74,222,128,0.85)' :
              telemetryStatus === 'WAITING' ? 'rgba(251,191,36,0.85)' :
              telemetryStatus === 'COMPLETED' ? 'rgba(56,189,248,0.85)' :
              'rgba(239,68,68,0.85)',
          }}>
            {hudVisible
              ? (completedRun ? 'CURRENT VIEW: ANALYZED REPLAY' : displayedSample ? 'CURRENT VIEW: ANALYZED SYNC' : 'CURRENT VIEW: AWAITING ANALYZED SAMPLE')
              : 'CURRENT VIEW: SOURCE PREVIEW'}
          </span>
        </div>
      )}

      {/* ── Uploading spinner ── */}
      {isUploading && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 25,
          background: 'rgba(0,0,0,0.7)',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          gap: '0.75rem',
        }}>
          <span className="animate-pulse" style={{
            fontFamily: 'var(--font-display)', fontSize: '0.8rem',
            letterSpacing: '0.1em', color: 'var(--color-ok)',
          }}>
            {uploadLabel}
          </span>
        </div>
      )}

    </div>
  );
}
