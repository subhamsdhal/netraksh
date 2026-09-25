import { useState, useEffect, useCallback, useMemo } from 'react';
import { CameraOff, AlertTriangle, ShieldCheck, Activity } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import { WS_URL, authFetch } from '../services/auth';

// This entire page used to be 3 hardcoded mock cameras (CAM-07/12/04) with
// a "82%" / "36 OK / 5 DEGRADED / 3 FAILED" summary that didn't even
// arithmetically match the 3 cameras rendered below it — and a WebSocket
// merge that could never actually fire, since nothing in the backend ever
// broadcast a `camera_health` message. Both gaps are now closed:
//   - GET /cameras (backend/api/cameras.py) is now actually called here.
//   - POST /cameras/{id}/health (added alongside this change) is what the
//     edge pipeline now calls periodically (edge/main.py's new
//     _report_camera_health), and its handler broadcasts camera_health
//     over the WebSocket — so the merge below can genuinely fire now.
// See docs/ARCHITECTURE.md for the full account.
export default function Health() {
  const { health } = useWebSocket(WS_URL);
  const [cameras, setCameras] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | auth-required | error
  const [filter, setFilter] = useState('all'); // all | attention

  const loadCameras = useCallback(async () => {
    setStatus('loading');
    try {
      const res = await authFetch('/cameras');
      if (res.status === 403) {
        setStatus('access-denied');
        return;
      }
      if (!res.ok) {
        setStatus('error');
        return;
      }
      setCameras(await res.json());
      setStatus('ready');
    } catch (_e) {
      setStatus('error');
    }
  }, []);

  useEffect(() => { loadCameras(); }, [loadCameras]);

  // Merge live WS camera_health pushes (now real — see module comment
  // above) into the list fetched from GET /cameras, keyed by camera_id.
  const mergedCameras = useMemo(() => cameras.map((cam) => {
    const h = health[cam.camera_id];
    if (!h) return cam;
    return {
      ...cam,
      health_state: h.health_state ?? cam.health_state,
      health_reason: h.health_reason ?? cam.health_reason,
      fps_actual: h.fps_actual ?? cam.fps_actual,
      blur_score: h.blur_score ?? cam.blur_score,
      exposure_clip_fraction: h.exposure_clip_fraction ?? cam.exposure_clip_fraction,
      drift_seconds: h.drift_seconds ?? cam.drift_seconds,
    };
  }), [cameras, health]);

  const okCount = mergedCameras.filter((c) => c.health_state === 'OK').length;
  const degradedCount = mergedCameras.filter((c) => c.health_state === 'DEGRADED').length;
  const failedCount = mergedCameras.filter((c) => c.health_state === 'FAILED').length;
  const unknownCount = mergedCameras.length - okCount - degradedCount - failedCount;
  const sightPct = mergedCameras.length > 0 ? Math.round((okCount / mergedCameras.length) * 100) : null;
  const needsAttentionCount = degradedCount + failedCount + unknownCount;

  const visibleCameras = filter === 'attention'
    ? mergedCameras.filter((c) => c.health_state !== 'OK')
    : mergedCameras;

  const CameraCard = ({ cam }) => {
    let borderColor = 'border-color';
    if (cam.health_state === 'OK') borderColor = 'border-ok';
    else if (cam.health_state === 'DEGRADED') borderColor = 'border-warning';
    else if (cam.health_state === 'FAILED') borderColor = 'border-danger';

    return (
      <div className={`bg-panel border rounded flex flex-col overflow-hidden ${borderColor}`}>
        <div className="h-32 w-full relative bg-black flex items-center justify-center">
          {cam.health_state === 'FAILED' ? (
            <div className="flex flex-col items-center gap-2 text-danger">
              <CameraOff size={32} />
              <span className="text-xs font-display tracking-widest">NO SIGNAL</span>
            </div>
          ) : (
            <div className="w-full h-full relative" style={{ background: 'radial-gradient(circle at 50% 50%, rgba(34,197,94,0.13), rgba(2,6,23,0.96))', filter: cam.health_state === 'DEGRADED' ? 'blur(2px) brightness(0.65)' : 'none' }}>
              <div className="absolute top-2 left-2 text-[10px] font-display bg-white text-black px-1 rounded">{cam.health_state === 'OK' ? 'ONLINE' : cam.health_state === 'DEGRADED' ? 'DEGRADED' : 'UNKNOWN'}</div>
              {/* Explicitly labelled as Simulated Feed Preview — this is a static placeholder image, not a live RTSP stream */}
              <div className="absolute bottom-2 right-2 text-[10px] font-display bg-dark border rounded px-1 text-muted text-white">DEMO PREVIEW</div>
            </div>
          )}
          {cam.health_state === 'DEGRADED' && (
            <div className="absolute top-2 right-2 text-[10px] font-display bg-dark border rounded px-1 text-muted text-white">IR FALLBACK</div>
          )}
          {cam.health_state === 'FAILED' && (
            <div className="absolute top-2 left-2 text-[10px] font-display bg-danger text-white px-1 rounded">FAILED</div>
          )}
        </div>

        <div className="p-4 flex flex-col gap-4">
          <div className="flex justify-between items-center border-b border-color pb-2">
            <span className="text-main font-display">{cam.camera_id}</span>
            <span className="text-xs text-muted">{cam.location}</span>
          </div>

          {/* Not `grid grid-cols-2` (a class that does nothing in this
              project — see docs/LIMITATIONS.md's "grid classes are inert"
              entry) — real CSS Grid via inline style instead. */}
          <div className="text-xs font-display text-muted uppercase" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', rowGap: '1rem', columnGap: '0.5rem' }}>
            <div className="flex-col">
              <span>FPS {cam.fps_declared ? `(of ${cam.fps_declared})` : ''}</span>
              <span className="text-main mt-1 block">{cam.fps_actual != null ? cam.fps_actual.toFixed(1) : '-'}</span>
            </div>
            <div className="flex-col">
              <span>BLUR INDEX {cam.health_state === 'DEGRADED' ? '(FOG)' : ''}</span>
              <span className="text-main mt-1 block">{cam.blur_score != null ? cam.blur_score.toFixed(1) : '-'}</span>
            </div>
            <div className="flex-col">
              <span>EXPOSURE CLIP</span>
              <span className="text-main mt-1 block">{cam.exposure_clip_fraction != null ? `${(cam.exposure_clip_fraction * 100).toFixed(0)}%` : '-'}</span>
            </div>
            <div className="flex-col">
              <span>SYNC DRIFT</span>
              <span className="text-main mt-1 block lowercase">Δ {cam.drift_seconds != null ? `${cam.drift_seconds.toFixed(2)}s` : 'N/A'}</span>
            </div>
          </div>

          <div className="mt-auto pt-4 border-t border-color flex justify-between items-center text-xs font-display">
            <span className="text-muted">HEALTH</span>
            {cam.health_state === 'FAILED' ? (
              <span className="text-danger flex items-center gap-1"><CameraOff size={12}/> {cam.health_reason || 'FAILED'}</span>
            ) : cam.health_state === 'DEGRADED' ? (
              <span className="text-warning flex items-center gap-1"><AlertTriangle size={12}/> {cam.health_reason || 'DEGRADED'}</span>
            ) : cam.health_state === 'OK' ? (
              <span className="text-ok flex items-center gap-1"><ShieldCheck size={12}/> NOMINAL</span>
            ) : (
              <span className="text-muted flex items-center gap-1"><Activity size={12}/> NO DATA YET</span>
            )}
          </div>

          {cam.health_state === 'FAILED' && (
            <button
              disabled
              title="No remote reboot capability exists in this deployment — the backend has no endpoint for it. Left visible, disabled, rather than silently doing nothing on click."
              className="w-full mt-2 py-2 border border-danger text-danger text-xs font-display rounded opacity-40 cursor-not-allowed"
            >
              ⟲ INITIATE REBOOT (not implemented)
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col gap-4">
      <div className="section-header">
        <div>
          <div className="section-title">Camera Health Matrix</div>
          <div className="section-sub">Real-time sensor status · FPS · Optical clarity · Sync drift</div>
        </div>
        {status === 'ready' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div className="badge badge-ok">{okCount} OK</div>
            <div className="badge badge-warning">{degradedCount} Degraded</div>
            <div className="badge badge-danger">{failedCount} Failed</div>
          </div>
        )}
      </div>

      {/* Honest demo banner */}
      <div className="card" style={{ padding: '0.625rem 0.875rem', borderColor: 'rgba(245,158,11,0.2)', background: 'rgba(245,158,11,0.04)' }}>
        <span style={{ fontSize: '0.65rem', fontFamily: 'var(--font-display)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          <span className="text-warning">Demo Mode</span>
          {' — '}
          2 cameras registered: <span className="text-main">cam-border-01</span> (Border Post Alpha) and{' '}
          <span className="text-main">cam-checkpoint-01</span> (Checkpoint Bravo).
          Both run local video files. Architecture supports additional cameras via <code style={{ background: 'var(--bg-base)', padding: '0 4px', borderRadius: 2 }}>POST /cameras</code>.
        </span>
      </div>

      {status === 'loading' && <div className="state-loading"><span>Loading camera fleet…</span></div>}
      {status === 'error'   && <div className="state-error"><AlertTriangle size={18} /><span>Could not reach the backend.</span></div>}
      {status === 'access-denied' && (
        <div className="card" style={{ maxWidth: 360, borderColor: 'rgba(239,68,68,0.3)' }}>
          <h3 className="text-danger font-display tracking-widest uppercase" style={{ fontSize: '0.8rem' }}>Access Denied</h3>
          <p className="text-muted text-sm mt-2">You do not have permission to access this module.</p>
        </div>
      )}

      {status === 'ready' && (
        <>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              onClick={() => setFilter('all')}
              className="btn btn-sm"
              style={{
                borderStyle: 'solid',
                borderWidth: '1px',
                borderColor: filter === 'all' ? 'var(--accent)' : 'var(--border-color)',
                background:  filter === 'all' ? 'var(--accent-dim)' : 'transparent',
                color:       filter === 'all' ? 'var(--accent)' : 'var(--text-muted)',
              }}
            >
              All Sectors ({mergedCameras.length})
            </button>
            <button
              onClick={() => setFilter('attention')}
              className="btn btn-sm"
              style={{
                borderStyle: 'solid',
                borderWidth: '1px',
                borderColor: filter === 'attention' ? 'var(--color-warning)' : 'var(--border-color)',
                background:  filter === 'attention' ? 'rgba(245,158,11,0.1)' : 'transparent',
                color:       filter === 'attention' ? 'var(--color-warning)' : 'var(--text-muted)',
              }}
            >
              <AlertTriangle size={12} /> Needs Attention ({needsAttentionCount})
            </button>
          </div>

          {mergedCameras.length === 0 ? (
            <div className="text-muted text-sm text-center mt-8">No cameras registered yet.</div>
          ) : visibleCameras.length === 0 ? (
            <div className="text-muted text-sm text-center mt-8">No cameras need attention right now.</div>
          ) : (
            // Not `grid-cols-1 md:... lg:... xl:...` — those breakpoint
            // classes don't exist in this project's CSS either (no
            // @media rules at all — see docs/LIMITATIONS.md), so this
            // never responded to viewport width. `repeat(auto-fill, ...)`
            // gives real responsive column count with zero media queries
            // needed.
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '1.5rem' }}>
              {visibleCameras.map((cam) => <CameraCard key={cam.camera_id} cam={cam} />)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
