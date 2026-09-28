/**
 * NETRAKSH — LiveVideoFeed Component
 *
 * Renders a video element with:
 *   - Accurate letterbox-aware coordinate mapping for bounding boxes
 *   - An SVG overlay that draws tactical track boxes at pixel-perfect positions
 *   - A toggleable corner HUD (replaces the removed [SUPER DEBUG OVERLAY])
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
import { CameraOff, CloudFog, AlertTriangle, Upload, Play, Activity } from 'lucide-react';
import { authFetch } from '../services/auth';
import { frameResponseMatchesTelemetry } from '../utils/dashboardScope';

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

// ─── Corner debug HUD (replaces [SUPER DEBUG OVERLAY]) ───────────────────────
// Hidden by default — operator clicks the tiny [HUD] toggle to reveal it.
// Low opacity, monospace, bottom-right corner — never blocks the video content.
function DebugHud({ visible, videoRect, liveTracksData, videoRef, analyzedFrame }) {
  if (!visible) return null;
  const vt = videoRef.current;
  return (
    <div
      style={{
        position: 'absolute', bottom: '0.5rem', right: '0.5rem',
        background: 'rgba(0,0,0,0.65)', border: '1px solid rgba(74,222,128,0.3)',
        borderRadius: '0.2rem', padding: '0.35rem 0.5rem',
        fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
        fontSize: '0.5rem', lineHeight: '1.5', color: 'rgba(74,222,128,0.7)',
        opacity: 0.85, zIndex: 30, pointerEvents: 'none', whiteSpace: 'pre',
        minWidth: '160px',
      }}
    >
      {`CONTAINER  ${videoRect.cw?.toFixed(0)}×${videoRect.ch?.toFixed(0)}\n`}
      {`FRAME SRC  ${videoRect.vw}×${videoRect.vh}\n`}
      {`RENDERED   ${videoRect.width?.toFixed(0)}×${videoRect.height?.toFixed(0)}\n`}
      {`OFFSET     L:${videoRect.left?.toFixed(0)} T:${videoRect.top?.toFixed(0)}\n`}
      {liveTracksData
        ? `SEQ ${liveTracksData.sequence ?? '—'}  FRAME ${liveTracksData.frame_index ?? '—'}  SESSION ${(liveTracksData.analysis_session_id || liveTracksData.stream_id || '—').slice(0, 8)}\nSRC t=${liveTracksData.video_time?.toFixed(2) ?? '—'}s\n`
        : `NO LIVE DATA\n`}
      {analyzedFrame
        ? `ANALYZED FRAME · SAME SAMPLE\n`
        : vt
        ? `VID  t=${vt.currentTime?.toFixed(2)}s  RS:${vt.readyState}\n`
        : `VIDEO NOT READY\n`}
      {`PERSONS ${liveTracksData?.person_count ?? 0}  VEHICLES ${liveTracksData?.vehicle_count ?? 0}  TRACKS ${liveTracksData?.track_count ?? 0}`}
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────
export default function VideoFeed({
  eventData,
  liveTracksData,
  activeEvents = [],
  telemetryStatus = 'WAITING',
  cameraId,
  playbackEnded = false,
  demoScenario = 'normal',
  mediaUrl,
  mediaType,
  currentFps,
  onUpload,
  isUploading,
  canUpload,
  uploadError,
  onVideoEnded,
  onStartAnalysis,
  onPauseAnalysis,
  sourceMode,
  expectedSessionId,
  sourceRunState,
  sourceRestoring = false,
}) {
  const containerRef = useRef(null);
  const videoRef = useRef(null);
  const previewRef = useRef(null);
  const svgRef = useRef(null);

  // Measured geometry of the letterboxed video frame within its container.
  const [videoRect, setVideoRect] = useState({
    left: 0, top: 0, width: 0, height: 0, cw: 0, ch: 0, vw: 0, vh: 0,
  });

  // Durable uploads default to the authoritative analyzed view once telemetry
  // exists; the toggle switches back to the independently playing source.
  const [hudVisible, setHudVisible] = useState(sourceMode === 'durable');
  const [videoError, setVideoError] = useState(false);
  const [analyzedFrameUrl, setAnalyzedFrameUrl] = useState(null);
  const [analyzedFrameStatus, setAnalyzedFrameStatus] = useState('WAITING FOR NEXT ANALYZED FRAME');
  const isDurableSource = sourceMode === 'durable';
  const showAnalyzedFrame = Boolean(
    analyzedFrameUrl
    && hudVisible
    && ['LIVE', 'STALE'].includes(telemetryStatus)
  );

  useEffect(() => {
    setHudVisible(sourceMode === 'durable');
  }, [sourceMode]);

  // Lightweight render-tick to re-evaluate live tracks freshness
  const [tick, setTick] = useState(0);

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
    const sourceSessionId = liveTracksData?.stream_id || null;
    const analysisSessionId = liveTracksData?.analysis_session_id || null;
    const frameIndex = liveTracksData?.frame_index;
    if (!isDurableSource && !hudVisible) return undefined;
    if (expectedSessionId && sourceSessionId && sourceSessionId !== expectedSessionId) return undefined;
    if (!cameraId || !analysisSessionId || !Number.isFinite(frameIndex) || !liveTracksData?.preview_available) return undefined;
    let cancelled = false;
    let nextUrl = null;
    const params = new URLSearchParams({
      analysis_session_id: analysisSessionId,
      frame_index: String(frameIndex),
      hud: isDurableSource || hudVisible ? 'true' : 'false',
      cache_bust: `${analysisSessionId}:${frameIndex}:${isDurableSource || hudVisible ? 1 : 0}`,
    });
    authFetch(`/system/telemetry/frame/${encodeURIComponent(cameraId)}?${params.toString()}`)
      .then((response) => response.ok && frameResponseMatchesTelemetry(liveTracksData, response.headers) ? response.blob() : null)
      .then((blob) => {
        if (!blob || cancelled) return;
        nextUrl = URL.createObjectURL(blob);
        // Do not replace a valid FrameSnapshot until this exact response is
        // decodable. A failed candidate keeps the prior image and its baked
        // boxes/counts together instead of rendering a broken image.
        const candidate = new Image();
        candidate.onload = () => {
          if (cancelled) return;
          setAnalyzedFrameUrl((previous) => {
            if (previous) URL.revokeObjectURL(previous);
            return nextUrl;
          });
          setAnalyzedFrameStatus('LATEST ANALYZED FRAME');
        };
        candidate.onerror = () => {
          URL.revokeObjectURL(nextUrl);
          nextUrl = null;
          if (!cancelled) setAnalyzedFrameStatus('WAITING FOR NEXT ANALYZED FRAME');
        };
        candidate.src = nextUrl;
      })
      .catch(() => { if (!cancelled) setAnalyzedFrameStatus('WAITING FOR NEXT ANALYZED FRAME'); });
    return () => { cancelled = true; if (nextUrl) URL.revokeObjectURL(nextUrl); };
  }, [cameraId, liveTracksData, hudVisible, isDurableSource, expectedSessionId]);

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
  const rVFC_ref = useRef(null);
  
  useEffect(() => {
    if (demoCache && videoRef.current && 'requestVideoFrameCallback' in videoRef.current) {
      let rVFC = null;
      const callback = (now, metadata) => {
        // metadata.mediaTime is the exact presentation timestamp of the currently painted frame
        rVFC_ref.current = metadata.mediaTime;
        setTick((v) => v + 1);
        rVFC = videoRef.current.requestVideoFrameCallback(callback);
      };
      rVFC = videoRef.current.requestVideoFrameCallback(callback);
      return () => {
        if (rVFC && videoRef.current) videoRef.current.cancelVideoFrameCallback(rVFC);
      };
    } else if (demoCache) {
      let rafId;
      const loop = () => {
        setTick((v) => v + 1);
        rafId = requestAnimationFrame(loop);
      };
      rafId = requestAnimationFrame(loop);
      return () => cancelAnimationFrame(rafId);
    } else {
      const id = setInterval(() => setTick((v) => v + 1), 250);
      return () => clearInterval(id);
    }
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
    const vw = media.naturalWidth || media.videoWidth || liveTracksData?.frame_width || 1280;
    const vh = media.naturalHeight || media.videoHeight || liveTracksData?.frame_height || 720;

    if (vw === 0 || vh === 0) return;

    const containerRatio = cw / ch;
    const videoRatio = vw / vh;

    let renderedW, renderedH, left, top;

    if (containerRatio > videoRatio) {
      // Container wider than frame → pillarbox
      renderedH = ch;
      renderedW = ch * videoRatio;
      left = (cw - renderedW) / 2;
      top = 0;
    } else {
      // Container taller than frame → letterbox
      renderedW = cw;
      renderedH = cw / videoRatio;
      left = 0;
      top = (ch - renderedH) / 2;
    }

    setVideoRect({ left, top, width: renderedW, height: renderedH, cw, ch, vw, vh });
  }, [liveTracksData?.frame_width, liveTracksData?.frame_height, showAnalyzedFrame]);

  useEffect(() => {
    setVideoError(false);
    updateRect();
    const ro = new ResizeObserver(updateRect);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [updateRect, mediaUrl]);

  const activeTracks = useMemo(() => {
    if (showAnalyzedFrame && liveTracksData?.tracks) return liveTracksData.tracks;
    // For demo cache, prioritize rVFC exact mediaTime over the generic video.currentTime.
    // ADD +1 FRAME (1.0 / 30.0) LOOKAHEAD to compensate for the 1-frame DOM repaint delay, 
    // ensuring the SVG paints on screen exactly in sync with the video frame.
    const videoTime = (demoCache && rVFC_ref.current !== null) 
      ? rVFC_ref.current + (1.0 / 30.0)
      : (videoRef.current ? videoRef.current.currentTime : 0);

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
    // browser clock. Production boxes are burned into the exact analyzed JPEG.
    return [];
  }, [liveTracksData, demoCache, tick, mediaUrl, showAnalyzedFrame]);

  /**
   * FIX A: Continuous Browser Playback-Time Sync
   * Synchronize the backend with the current browser time every 2 seconds
   * so Edge doesn't fall behind.
   */
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

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
  }, [onStartAnalysis, playbackEnded, demoScenario]);

  // ── Empty state — no media loaded ──────────────────────────────────────────
  if (!mediaUrl && !analyzedFrameUrl) {
    return (
      <div
        className="dashboard-video-feed w-full h-full flex flex-col items-center justify-center border rounded relative overflow-hidden"
        style={{ background: 'radial-gradient(circle at 50% 50%, #0c1a13 0%, #020617 100%)', cursor: canUpload ? 'pointer' : 'default' }}
        onClick={canUpload ? onUpload : undefined}
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
              ? 'UPLOADING · VALIDATING · NORMALIZING VIDEO'
              : ['ACTIVATING', 'WAKING'].includes(sourceRunState)
                ? 'PREPARING CLOUD ANALYSIS'
                : sourceRunState === 'READY_TO_START'
                  ? 'VIDEO READY · STARTING AI WORKER'
                  : (sourceMode === 'durable' && expectedSessionId && !liveTracksData)
                    ? sourceRunState === 'COMPLETED'
                      ? 'SOURCE STORED · ANALYSIS COMPLETED'
                      : 'WAITING FOR FIRST ANALYZED FRAME'
                    : liveTracksData
                      ? 'TELEMETRY ACTIVE · LOCAL PLAYBACK OPTIONAL'
                      : 'NO VIDEO SOURCE'}
          </span>
          {canUpload && !sourceRestoring && !isUploading && !(sourceMode === 'durable' && expectedSessionId) ? <div className="dashboard-video-upload" style={{
            background: 'var(--color-ok)', color: '#000',
            fontFamily: 'var(--font-display)', fontWeight: 700,
            fontSize: '0.75rem', letterSpacing: '0.1em',
            padding: '0.6rem 1.5rem', borderRadius: '0.25rem',
            display: 'flex', alignItems: 'center', gap: '0.5rem',
          }}>
            <Play size={14} /> ADD VIDEO SOURCE
          </div> : sourceRestoring ? <span className="text-muted text-xs">VERIFYING DURABLE SOURCE AUTHORITY</span> : !isUploading && sourceMode === 'durable' && expectedSessionId ? <span className="text-muted text-xs">PREVIEW UNAVAILABLE FOR THIS RESTORED SESSION</span> : <span className="text-muted text-xs">Upload requires ADMIN or OPERATOR access</span>}
          <span className="text-muted text-xs">SUPPORTED: MP4 · AVI · MOV · MKV · WEBM · M4V</span>
          {uploadError && <span className="text-danger text-xs text-center" role="alert">{uploadError}</span>}
        </div>
      </div>
    );
  }

  const processedAtRaw = Number(liveTracksData?.processed_timestamp);
  const processedAtMs = Number.isFinite(processedAtRaw)
    ? (processedAtRaw > 1e12 ? processedAtRaw : processedAtRaw * 1000)
    : null;
  const processedAgeSeconds = processedAtMs == null
    ? null
    : Math.max(0, (Date.now() - processedAtMs) / 1000);

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
      {/* Durable cloud sources always show the annotated JPEG paired with the
          current telemetry sample. The video element is explicitly a source
          preview while the worker is waking or no analyzed frame exists. */}
      {showAnalyzedFrame ? <img
        ref={previewRef}
        src={analyzedFrameUrl}
        alt={`Annotated analyzed frame for ${cameraId}`}
        onLoad={updateRect}
        style={{
          position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', zIndex: 0,
          filter: telemetryStatus === 'LIVE' ? 'none' : 'grayscale(0.7) brightness(0.55)',
        }}
      /> : mediaUrl ? <video
        ref={videoRef}
        src={mediaUrl}
        muted
        controls
        playsInline
        preload="metadata"
        onLoadedMetadata={(e) => {
          updateRect();
          if (e.target.paused && !e.target.ended) onPauseAnalysis?.(e.target.currentTime);
        }}
        onPlay={(e) => {
          setIsVideoPlaying(true);
          onStartAnalysis?.(e.target.currentTime);
        }}
        onPause={(e) => {
          setIsVideoPlaying(false);
          if (!e.target.ended && !playbackEnded) {
            onPauseAnalysis?.(e.target.currentTime);
          }
        }}
        onSeeked={(e) => onStartAnalysis?.(e.target.currentTime)}
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
        style={{
          display: showAnalyzedFrame ? 'block' : 'none',
          position: 'absolute', inset: 0,
          width: '100%', height: '100%',
          zIndex: 10, pointerEvents: 'none',
          overflow: 'visible',
        }}
      >
        {activeTracks.map((ev) => {
          const normalizeTrackBBox = (track) => {
            if (track.bbox_x != null && track.bbox_y != null && track.bbox_w != null && track.bbox_h != null) {
              return { x: track.bbox_x, y: track.bbox_y, w: track.bbox_w, h: track.bbox_h };
            }
            if (track.bbox && track.bbox.x1 != null && track.bbox.y1 != null && track.bbox.x2 != null && track.bbox.y2 != null) {
              const fw = liveTracksData?.frame_width || 960;
              const fh = liveTracksData?.frame_height || 720;
              return {
                x: track.bbox.x1 / fw,
                y: track.bbox.y1 / fh,
                w: (track.bbox.x2 - track.bbox.x1) / fw,
                h: (track.bbox.y2 - track.bbox.y1) / fh
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
          const trackLabel = ev.identity_match && ev.subject_name
            ? `${ev.subject_name} [WL]`
            : `TRACK #${ev.track_id ?? '?'}`;

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
            <g key={ev.track_id}>
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

      {showAnalyzedFrame && (
        <div style={{
          position: 'absolute', left: '0.45rem', bottom: '0.45rem', zIndex: 20,
          padding: '0.25rem 0.45rem', border: '1px solid rgba(74,222,128,0.55)',
          background: 'rgba(2,6,23,0.86)', color: '#4ade80', borderRadius: '0.2rem',
          fontFamily: 'ui-monospace, monospace', fontSize: '0.55rem', letterSpacing: '0.07em',
          pointerEvents: 'none',
        }}>
          {analyzedFrameStatus} · FRAME {liveTracksData?.frame_index ?? '—'} · PROCESSED {processedAgeSeconds == null ? 'RECENTLY' : `${processedAgeSeconds.toFixed(1)}s AGO`} · EXACT TELEMETRY SAMPLE
        </div>
      )}
      {!showAnalyzedFrame && mediaUrl && isDurableSource && (
        <div style={{
          position: 'absolute', left: '0.45rem', bottom: '0.45rem', zIndex: 20,
          padding: '0.25rem 0.45rem', border: '1px solid rgba(56,189,248,0.55)',
          background: 'rgba(2,6,23,0.86)', color: '#38bdf8', borderRadius: '0.2rem',
          fontFamily: 'ui-monospace, monospace', fontSize: '0.55rem', letterSpacing: '0.07em',
          pointerEvents: 'none',
        }}>
          {analyzedFrameUrl
            ? `SOURCE PREVIEW · AI SAMPLE AVAILABLE · FRAME ${liveTracksData?.frame_index ?? '—'} · SOURCE TIME ${Number.isFinite(liveTracksData?.video_time) ? `${liveTracksData.video_time.toFixed(2)}s` : '—'} · PROCESSED ${processedAgeSeconds == null ? 'RECENTLY' : `${processedAgeSeconds.toFixed(1)}s AGO`}`
            : 'SOURCE PREVIEW · WAITING FOR FIRST ANALYZED FRAME'}
        </div>
      )}

      {/* ── Corner HUD toggle button ── */}
      <button
        onClick={() => setHudVisible((v) => !v)}
        title="Toggle debug HUD"
        aria-pressed={hudVisible}
        style={{
          position: 'absolute', top: '0.4rem', right: '0.4rem',
          zIndex: 20,
          background: hudVisible ? 'rgba(74,222,128,0.2)' : 'rgba(0,0,0,0.5)',
          border: `1px solid ${hudVisible ? 'rgba(74,222,128,0.6)' : 'rgba(255,255,255,0.15)'}`,
          borderRadius: '0.2rem',
          padding: '0.15rem 0.4rem',
          fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
          fontSize: '0.5rem', letterSpacing: '0.08em',
          color: hudVisible ? '#4ade80' : 'rgba(255,255,255,0.4)',
          cursor: 'pointer',
          lineHeight: '1.4',
          display: 'flex', alignItems: 'center', gap: '0.25rem',
        }}
      >
        <Activity size={8} /> {hudVisible ? 'ANALYZED' : 'SOURCE'}
      </button>

      {/* ── Toggleable debug HUD (replaces removed [SUPER DEBUG OVERLAY]) ── */}
      <DebugHud
        visible={hudVisible}
        videoRect={videoRect}
        liveTracksData={liveTracksData}
        videoRef={videoRef}
        analyzedFrame={showAnalyzedFrame}
      />

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
            TELEMETRY {telemetryStatus} · {cameraId || 'UNKNOWN CAMERA'}
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
            TRANSMITTING TO EDGE NODE…
          </span>
        </div>
      )}

      {/* ── Add Video Button (Bottom Right) ── */}
      {canUpload && (
        <button
          onClick={onUpload}
          disabled={isUploading}
          className="flex items-center gap-2 border border-ok text-ok px-3 py-1.5 rounded hover:bg-[rgba(74,222,128,0.1)] transition-colors text-sm font-display tracking-widest disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            position: 'absolute', bottom: '0.5rem', right: '0.5rem',
            zIndex: 20,
            background: 'rgba(0,0,0,0.65)',
          }}
        >
          {isUploading ? 'UPLOADING...' : 'ADD VIDEO'}
        </button>
      )}
    </div>
  );
}
