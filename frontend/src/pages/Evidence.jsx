/**
 * NETRAKSH — Tamper-Evident Evidence Unit (Evidence.jsx)
 *
 * KEY FIX — Bounding Box Alignment:
 *   The previous implementation used CSS `background-image` with
 *   `background-size: cover` to render the decrypted evidence image.
 *   Bounding box overlays were then positioned with percentage values
 *   relative to the container DIV — but `cover` crops the image to fill
 *   the container, meaning the visible image origin is NOT at (0,0) of
 *   the container. This caused every bounding box to be misaligned and
 *   partially clipped outside the image edges.
 *
 *   The fix: render the image via an <img> element with object-fit:contain
 *   (no cropping). An <svg> is absolutely positioned to cover the img
 *   element. A ResizeObserver computes the same letterbox-offset math as
 *   VideoFeed.jsx so SVG coordinates map exactly to the frame pixels.
 *
 * SECURITY:
 *   - Evidence images are fetched via authFetch (JWT in Authorization header)
 *   - Blob URLs are revoked on component unmount to avoid memory leaks
 *   - Hash/signature display is read-only — never executed or eval'd
 */
import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Search, Shield, CheckCircle, Database, GitBranch, Cloud, Lock, Download } from 'lucide-react';
import { authFetch } from '../services/auth';
import { parseUtc } from '../utils/time';

// ─── Sub-component: Evidence Image + SVG bounding-box overlay ────────────────
/**
 * EvidenceImageOverlay
 *
 * Renders the decrypted JPEG inside a fixed-size container, then draws
 * the bounding box in an absolutely-positioned <svg> that tracks the
 * rendered image rect via ResizeObserver.
 *
 * COORDINATE MAPPING (identical algorithm to VideoFeed.jsx):
 *   The image uses object-fit:contain → letterbox offsets apply.
 *   We compute (left, top, renderedW, renderedH) the same way and
 *   translate normalised bbox coords to absolute SVG pixels.
 */
function EvidenceImageOverlay({ imageUrl, event, status }) {
  const wrapRef  = useRef(null);
  const imgRef   = useRef(null);
  const [imgRect, setImgRect] = useState({ left: 0, top: 0, w: 0, h: 0 });

  const computeImgRect = useCallback(() => {
    const wrap = wrapRef.current;
    const img  = imgRef.current;
    if (!wrap || !img) return;

    const cr   = wrap.getBoundingClientRect();
    const cw   = cr.width;
    const ch   = cr.height;
    // naturalWidth/Height are the intrinsic JPEG dimensions
    const iw   = img.naturalWidth  || cw;
    const ih   = img.naturalHeight || ch;

    if (iw === 0 || ih === 0) return;

    const containerRatio = cw / ch;
    const imageRatio     = iw / ih;

    let left, top, renderedW, renderedH;
    if (containerRatio > imageRatio) {
      // Container wider → pillarbox
      renderedH = ch;
      renderedW = ch * imageRatio;
      left = (cw - renderedW) / 2;
      top  = 0;
    } else {
      // Container taller → letterbox
      renderedW = cw;
      renderedH = cw / imageRatio;
      left = 0;
      top  = (ch - renderedH) / 2;
    }

    setImgRect({ left, top, w: renderedW, h: renderedH });
  }, []);

  useEffect(() => {
    computeImgRect();
    const ro = new ResizeObserver(computeImgRect);
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [computeImgRect, imageUrl]);

  // Bounding box data from event
  const hasBbox = event?.bbox_w != null && event?.bbox_h != null;

  // SVG bounding box coordinates in container-space pixels
  const bboxPx = hasBbox ? {
    x: imgRect.left + event.bbox_x * imgRect.w,
    y: imgRect.top  + event.bbox_y * imgRect.h,
    w: event.bbox_w * imgRect.w,
    h: event.bbox_h * imgRect.h,
  } : null;

  return (
    <div
      ref={wrapRef}
      style={{
        position: 'relative',
        width: '100%', height: '100%',
        background: '#000',
        borderRadius: '0.25rem',
        overflow: 'hidden',
      }}
    >
      {/* Status banner */}
      <div style={{
        position: 'absolute', top: '0.5rem', left: '0.5rem',
        zIndex: 10,
        background: 'rgba(15,23,42,0.88)',
        border: '1px solid rgba(255,255,255,0.12)',
        borderRadius: '0.2rem',
        padding: '0.15rem 0.5rem',
        fontFamily: 'var(--font-display)',
        fontSize: '0.6rem', letterSpacing: '0.1em',
        color: status === 'ready' ? '#4ade80' : '#94a3b8',
        display: 'flex', alignItems: 'center', gap: '0.3rem',
      }}>
        <Lock size={8} />
        {status === 'ready' ? 'DECRYPTED EVIDENCE' : 'CH-04 | PREVIEW'}
      </div>

      {/* Evidence image — object-fit:contain keeps full frame visible, no crop */}
      {imageUrl && (
        <img
          ref={imgRef}
          src={imageUrl}
          onLoad={computeImgRect}
          alt="Decrypted evidence frame"
          style={{
            position: 'absolute', inset: 0,
            width: '100%', height: '100%',
            objectFit: 'contain',
            opacity: status === 'ready' ? 1 : 0.3,
          }}
        />
      )}

      {/* Tactical scanline effect */}
      {status === 'ready' && (
        <div className="scanline" style={{ zIndex: 5, pointerEvents: 'none' }} />
      )}

      {/* Loading overlay */}
      {(status === 'loading' || status === 'syncing') && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 20,
          background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <span className="animate-pulse" style={{
            fontFamily: 'var(--font-display)', fontSize: '0.65rem',
            letterSpacing: '0.1em', color: status === 'syncing' ? '#fbbf24' : '#4ade80',
          }}>
            {status === 'syncing' ? 'SYNCING EVIDENCE...' : 'DECRYPTING…'}
          </span>
        </div>
      )}

      {/* Access denied */}
      {status === 'access-denied' && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 20,
          background: 'rgba(0,0,0,0.85)',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: '0.4rem',
        }}>
          <span style={{
            fontFamily: 'var(--font-display)', fontSize: '0.7rem',
            letterSpacing: '0.1em', color: '#ef4444', textTransform: 'uppercase',
          }}>ACCESS DENIED</span>
          <span style={{ fontSize: '0.6rem', color: '#94a3b8', textAlign: 'center', padding: '0 1rem' }}>
            You do not have permission to view evidence
          </span>
        </div>
      )}

      {/* Inline status banners for non-blocking states */}
      {(status === 'no-key' || status === 'no-evidence' || status === 'error' || status === 'sync-timeout') && (
        <div style={{
          position: 'absolute', bottom: '0.5rem', left: '0.5rem', right: '0.5rem',
          zIndex: 20,
          background: 'rgba(15,23,42,0.9)',
          border: `1px solid ${status === 'error' ? 'rgba(239,68,68,0.5)' : 'rgba(251,191,36,0.4)'}`,
          borderRadius: '0.2rem',
          padding: '0.3rem 0.5rem',
          fontFamily: 'var(--font-display)',
          fontSize: '0.58rem', letterSpacing: '0.05em',
          color: status === 'error' ? '#ef4444' : '#fbbf24',
        }}>
          {status === 'no-key'    && "Camera's evidence key isn't registered — run scripts/upload_evidence_key.py"}
          {status === 'no-evidence' && 'No evidence image is available for this event'}
          {status === 'sync-timeout' && 'Evidence sync timed out. Please try refreshing later.'}
          {status === 'error'     && 'Could not reach the backend — check connectivity'}
        </div>
      )}

      {/* ── SVG bounding-box overlay (pixel-accurate) ── */}
      {status === 'ready' && event && (
        <svg
          style={{
            position: 'absolute', inset: 0,
            width: '100%', height: '100%',
            zIndex: 15, pointerEvents: 'none',
            overflow: 'visible',
          }}
        >
          {bboxPx ? (
            <g>
              {/* Main box */}
              <rect
                x={bboxPx.x} y={bboxPx.y}
                width={bboxPx.w} height={bboxPx.h}
                fill="rgba(74,222,128,0.08)"
                stroke="#4ade80"
                strokeWidth={1.5}
                style={{ filter: 'drop-shadow(0 0 4px rgba(74,222,128,0.5))' }}
              />
              {/* Corner accents */}
              {[
                [bboxPx.x,          bboxPx.y,            8,  0, 0,  8],
                [bboxPx.x+bboxPx.w, bboxPx.y,           -8,  0, 0,  8],
                [bboxPx.x,          bboxPx.y+bboxPx.h,   8,  0, 0, -8],
                [bboxPx.x+bboxPx.w, bboxPx.y+bboxPx.h, -8,  0, 0, -8],
              ].map(([cx, cy, dx1, dy1, dx2, dy2], i) => (
                <g key={i}>
                  <line x1={cx} y1={cy} x2={cx+dx1} y2={cy+dy1} stroke="#4ade80" strokeWidth={2.5} />
                  <line x1={cx} y1={cy} x2={cx+dx2} y2={cy+dy2} stroke="#4ade80" strokeWidth={2.5} />
                </g>
              ))}
              {/* Label */}
              <rect
                x={bboxPx.x} y={bboxPx.y - 16}
                width={120} height={16}
                fill="#4ade80" rx={2}
              />
              <text
                x={bboxPx.x + 5} y={bboxPx.y - 4}
                fill="#000" fontSize={9}
                fontFamily="'Space Grotesk', ui-monospace, monospace"
                fontWeight={700} letterSpacing="0.06em"
              >
                {`TRACK #${event.track_id ?? 'N/A'} (Tracker Identity)`}
              </text>
            </g>
          ) : (
            /* No bbox — show a "bbox unavailable" notice instead of nothing */
            <foreignObject x="8" y="8" width="200" height="28">
              <div
                style={{
                  background: 'rgba(15,23,42,0.9)',
                  border: '1px solid rgba(251,191,36,0.4)',
                  borderRadius: '0.2rem', padding: '0.25rem 0.5rem',
                  fontFamily: 'var(--font-display)', fontSize: '0.58rem',
                  letterSpacing: '0.05em', color: '#fbbf24',
                }}
              >
                Bounding box unavailable for this event
              </div>
            </foreignObject>
          )}
        </svg>
      )}
    </div>
  );
}

// ─── Verification step indicator ──────────────────────────────────────────────
const VerificationStep = ({ icon: Icon, title, status, active }) => (
  <div className="flex flex-col items-center gap-2 text-center relative flex-1">
    <div className={`w-12 h-12 rounded-full border-2 flex items-center justify-center ${
      active ? 'border-ok text-ok bg-[rgba(74,222,128,0.1)]' : 'border-color text-muted'
    }`}>
      <Icon size={20} />
    </div>
    <div className="flex flex-col">
      <span className="text-xs font-display text-muted">STEP</span>
      <span className="text-sm font-display text-main uppercase mt-1">{title}</span>
      <span className={`text-[10px] font-display px-2 py-1 border rounded mt-2 ${
        status === 'VERIFIED' || status === 'MATCH'
          ? 'text-ok border-ok'
          : 'text-muted border-color'
      }`}>
        {status}
      </span>
    </div>
  </div>
);

// ─── Main page component ──────────────────────────────────────────────────────
export default function Evidence() {
  const [selectedEvent, setSelectedEvent]   = useState(null);
  const [verifyStatus, setVerifyStatus]     = useState(null); // 'verifying'|'verified'|'failed'
  const [verifyData, setVerifyData]         = useState(null);
  const [searchQuery, setSearchQuery]       = useState('');
  const [decisionFilter, setDecisionFilter] = useState('ALL');
  const [typeFilter, setTypeFilter]         = useState('ALL');
  const [streamFilter, setStreamFilter]     = useState('ALL');
  const [cameraFilter, setCameraFilter]     = useState('ALL');
  const [chainFilter, setChainFilter]       = useState('ALL');
  const [vaultEvents, setVaultEvents]       = useState([]);
  const [totalEvidence, setTotalEvidence]   = useState(0);
  const [page, setPage]                     = useState(0);
  const [vaultStatus, setVaultStatus]       = useState('loading');
  const [vaultError, setVaultError]         = useState(null);
  const pageSize = 50;

  // Evidence image state
  const [evidenceImageUrl, setEvidenceImageUrl]           = useState(null);
  const [evidenceImageStatus, setEvidenceImageStatus]     = useState('idle');
  const [evidenceImageSizeBytes, setEvidenceImageSizeBytes] = useState(null);

  const displayEvents = vaultEvents;
  const filteredEvents = vaultEvents;
  const [filterOptions, setFilterOptions] = useState({ decisions: [], types: [], streams: [], cameras: [] });

  const loadVault = useCallback(async () => {
    setVaultStatus('loading');
    setVaultError(null);
    const params = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize) });
    if (searchQuery.trim()) params.set('search', searchQuery.trim());
    if (cameraFilter !== 'ALL') params.set('camera_id', cameraFilter);
    if (decisionFilter !== 'ALL') params.set('decision_state', decisionFilter);
    if (typeFilter !== 'ALL') params.set('event_type', typeFilter);
    if (streamFilter !== 'ALL') params.set('stream_id', streamFilter);
    if (chainFilter !== 'ALL') params.set('chain_status', chainFilter);
    try {
      const response = await authFetch(`/events/evidence-vault?${params.toString()}`);
      if (!response.ok) throw new Error(`Evidence request failed (${response.status})`);
      const payload = await response.json();
      const items = Array.isArray(payload.items) ? payload.items : [];
      setVaultEvents(items);
      setTotalEvidence(Number(payload.total || 0));
      setSelectedEvent(current => items.find(item => item.event_id === current?.event_id) || items[0] || null);
      setVaultStatus(items.length ? 'ready' : 'empty');
      setFilterOptions(current => ({
        decisions: [...new Set([...current.decisions, ...items.map(ev => ev.decision_state).filter(Boolean)])].sort(),
        types: [...new Set([...current.types, ...items.map(ev => ev.event_type).filter(Boolean)])].sort(),
        streams: [...new Set([...current.streams, ...items.map(ev => ev.stream_id).filter(Boolean)])].sort(),
        cameras: [...new Set([...current.cameras, ...items.map(ev => ev.camera_id).filter(Boolean)])].sort(),
      }));
    } catch (error) {
      setVaultEvents([]);
      setSelectedEvent(null);
      setVaultStatus('error');
      setVaultError(error instanceof Error ? error.message : 'Unable to load evidence');
    }
  }, [page, searchQuery, cameraFilter, decisionFilter, typeFilter, streamFilter, chainFilter]);

  useEffect(() => {
    const timer = setTimeout(loadVault, searchQuery ? 250 : 0);
    return () => clearTimeout(timer);
  }, [loadVault, searchQuery]);

  useEffect(() => { setPage(0); }, [searchQuery, cameraFilter, decisionFilter, typeFilter, streamFilter, chainFilter]);

  useEffect(() => {
    setVerifyData(null);
    setVerifyStatus(null);
  }, [selectedEvent?.event_id]);

  useEffect(() => {
    if (!selectedEvent) return;
    
    let active = true;
    let timer = null;

    const loadEvidenceImage = async (eventId, attempt = 1) => {
      if (!active) return;
      
      // Only show 'loading' or 'syncing' initially, avoid flickering on retry
      if (attempt === 1) {
        setEvidenceImageStatus('loading');
        setEvidenceImageSizeBytes(null);
      }
      
      try {
        const res = await authFetch(`/events/${eventId}/evidence-image`);
        if (!active) return;
        
        if (res.status === 425) {
          if (attempt >= 10) {
            setEvidenceImageStatus('sync-timeout');
            return;
          }
          setEvidenceImageStatus('syncing');
          timer = setTimeout(() => {
            loadEvidenceImage(eventId, attempt + 1);
          }, 3000); // 3 seconds * 10 = 30 seconds maximum
          return;
        }

        if (res.status === 403) { setEvidenceImageStatus('access-denied'); return; }
        if (res.status === 409) { setEvidenceImageStatus('no-key');        return; }
        if (res.status === 404 || !res.ok) { setEvidenceImageStatus('no-evidence'); return; }
        
        const blob = await res.blob();
        if (!active) return;
        
        setEvidenceImageSizeBytes(blob.size);
        setEvidenceImageUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return URL.createObjectURL(blob);
        });
        setEvidenceImageStatus('ready');
      } catch {
        // A live edge run can briefly outpace the backend while it is
        // ingesting evidence. Treat that as a bounded sync retry rather than
        // claiming the backend is unreachable on the first transient fetch
        // failure. The same 30-second limit used for HTTP 425 applies here.
        if (!active) return;
        if (attempt >= 10) {
          setEvidenceImageStatus('sync-timeout');
          return;
        }
        setEvidenceImageStatus('syncing');
        timer = setTimeout(() => loadEvidenceImage(eventId, attempt + 1), 3000);
      }
    };

    loadEvidenceImage(selectedEvent.event_id);

    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [selectedEvent?.event_id]);

  // Revoke blob URL on unmount
  useEffect(() => () => {
    setEvidenceImageUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return prev; });
  }, []);

  // Integrity chain verification
  const handleVerify = async () => {
    if (!selectedEvent) return;
    setVaultError('');
    setVerifyStatus('verifying');
    try {
      const res = await authFetch(`/events/${selectedEvent.event_id}/verify`, { method: 'POST' });
      if (res.status === 403) {
        setVerifyStatus('failed');
        setVaultError('Verification is restricted to authorized operators.');
        return;
      }
      const data = await res.json();
      if (!res.ok) {
        setVerifyStatus('failed');
        setVaultError(data?.detail || `Verification failed (${res.status}).`);
        return;
      }
      const allValid = res.ok && data.hash_valid && data.signature_valid && data.chain_valid;
      setVerifyStatus(allValid ? 'verified' : 'failed');
      setVerifyData(data);
      setVaultEvents(current => current.map(event => event.event_id === selectedEvent.event_id ? {
        ...event,
        hash_valid: data.hash_valid,
        signature_valid: data.signature_valid,
        chain_valid: data.chain_valid,
        chain_status: data.chain_status,
        verified_ok: allValid,
        evidence_verified_at: data.verified_at,
      } : event));
      setSelectedEvent(current => current?.event_id === selectedEvent.event_id ? {
        ...current,
        hash_valid: data.hash_valid,
        signature_valid: data.signature_valid,
        chain_valid: data.chain_valid,
        chain_status: data.chain_status,
        verified_ok: allValid,
        evidence_verified_at: data.verified_at,
      } : current);
    } catch {
      setVerifyStatus('failed');
      setVaultError('Verification could not reach the evidence service. Retry when connectivity is restored.');
    }
  };

  const handleExportCSV = async () => {
    const params = new URLSearchParams();
    if (searchQuery.trim()) params.set('search', searchQuery.trim());
    if (cameraFilter !== 'ALL') params.set('camera_id', cameraFilter);
    if (decisionFilter !== 'ALL') params.set('decision_state', decisionFilter);
    if (typeFilter !== 'ALL') params.set('event_type', typeFilter);
    if (streamFilter !== 'ALL') params.set('stream_id', streamFilter);
    if (chainFilter !== 'ALL') params.set('chain_status', chainFilter);
    const response = await authFetch(`/events/evidence-vault/export?${params.toString()}`);
    if (!response.ok) {
      setVaultError(`Export failed (${response.status})`);
      return;
    }
    const blobUrl = URL.createObjectURL(await response.blob());
    const disposition = response.headers.get('content-disposition') || '';
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || 'netraksh_evidence_vault.csv';
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
  };

  // Never substitute a fabricated/static image for missing evidence.
  const displayImageUrl = evidenceImageStatus === 'ready' ? evidenceImageUrl : null;
  const currentVerification = verifyData || (selectedEvent ? {
    hash_valid: selectedEvent.hash_valid,
    signature_valid: selectedEvent.signature_valid,
    chain_valid: selectedEvent.chain_valid,
    chain_status: selectedEvent.chain_status,
    stored_hash: selectedEvent.hash,
    calculated_hash: null,
    verified_at: selectedEvent.evidence_verified_at,
  } : null);
  const locallyVerified = Boolean(
    currentVerification?.hash_valid
    && currentVerification?.signature_valid
    && currentVerification?.chain_valid,
  );

  return (
    <div className="h-full flex flex-col gap-6">
      <div className="section-header">
        <div>
          <h2 className="section-title">Cryptographic Evidence Vault</h2>
          <div className="section-sub">Tamper-Evident Chain & Media Verification</div>
        </div>
        <button
          onClick={handleExportCSV}
          className="btn btn-outline flex items-center gap-2"
        >
          <Download size={14} />
          EXPORT LEDGER (CSV)
        </button>
      </div>

      <div className="evidence-vault-layout flex gap-4" style={{ height: 'calc(100% - 40px)' }}>

        {/* ── Left: Evidence Vault list ── */}
        <div className="card h-full evidence-vault-list" style={{ width: '320px' }}>
          <div className="card-header border-b border-color" style={{ paddingBottom: '0.75rem' }}>
            <div className="flex items-center gap-2">
              <Shield size={16} className="text-ok" />
              <span className="card-title">Evidence Vault · {totalEvidence.toLocaleString()}</span>
            </div>
          </div>
          
          <div className="flex flex-col h-full" style={{ padding: '0.75rem' }}>
            <div className="relative mb-3 flex items-center">
              <Search size={14} className="absolute left-3 text-muted pointer-events-none" />
              <input
                type="text"
                placeholder="Search by ID or Hash..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-dark border border-color rounded py-2 pr-3 font-body text-main"
                style={{ fontSize: '0.75rem', paddingLeft: '2.5rem' }}
              />
            </div>

            <div className="flex flex-col gap-2 mb-3">
              <select aria-label="Camera filter" value={cameraFilter} onChange={e => setCameraFilter(e.target.value)} className="bg-dark border border-color rounded px-1 py-1 text-main" style={{fontSize:'0.62rem'}}>
                <option value="ALL">All cameras</option>
                {filterOptions.cameras.map(value => <option key={value} value={value}>{value}</option>)}
              </select>
              <select aria-label="Decision filter" value={decisionFilter} onChange={e => setDecisionFilter(e.target.value)} className="bg-dark border border-color rounded px-1 py-1 text-main" style={{fontSize:'0.62rem'}}>
                <option value="ALL">All states</option>
                {filterOptions.decisions.map(value => <option key={value} value={value}>{value}</option>)}
              </select>
              <select aria-label="Event type filter" value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="bg-dark border border-color rounded px-1 py-1 text-main" style={{fontSize:'0.62rem'}}>
                <option value="ALL">All types</option>
                {filterOptions.types.map(value => <option key={value} value={value}>{value}</option>)}
              </select>
              <select aria-label="Stream filter" value={streamFilter} onChange={e => setStreamFilter(e.target.value)} className="bg-dark border border-color rounded px-1 py-1 text-main" style={{fontSize:'0.62rem'}}>
                <option value="ALL">All streams</option>
                {filterOptions.streams.map(value => <option key={value} value={value}>{value.slice(0, 8)}</option>)}
              </select>
              <select aria-label="Integrity filter" value={chainFilter} onChange={e => setChainFilter(e.target.value)} className="bg-dark border border-color rounded px-1 py-1 text-main" style={{fontSize:'0.62rem'}}>
                <option value="ALL">All chain states</option>
                <option value="VALID">VALID</option>
                <option value="PENDING">PENDING</option>
                <option value="INVALID">INVALID</option>
              </select>
            </div>

            <div className="flex flex-col gap-2 overflow-y-auto pr-1 flex-grow custom-scrollbar">
              {vaultStatus === 'loading' && (
                <div className="state-empty" style={{ marginTop: '1rem' }}>
                  <div className="state-empty-sub">LOADING EVIDENCE…</div>
                </div>
              )}
              {vaultStatus === 'error' && (
                <div className="state-empty" style={{ marginTop: '1rem' }}>
                  <div className="state-empty-sub">EVIDENCE REQUEST FAILED</div>
                  <div className="text-muted" style={{ fontSize: '0.65rem', marginTop: '0.5rem' }}>{vaultError}</div>
                  <button className="btn btn-sm btn-outline" onClick={loadVault} style={{ marginTop: '0.75rem' }}>RETRY</button>
                </div>
              )}
              {vaultStatus === 'empty' && (
                <div className="state-empty" style={{ marginTop: '1rem' }}>
                  <div className="state-empty-sub">NO EVIDENCE AVAILABLE FOR CURRENT FILTERS</div>
                </div>
              )}
              {vaultStatus === 'ready' && filteredEvents.map((ev) => {
                const isSelected = selectedEvent?.event_id === ev.event_id;
                const integrityLabel = ev.hash_valid === false || ev.signature_valid === false
                  ? 'CRYPTO INVALID'
                  : ev.chain_status === 'VALID' ? 'VERIFIED'
                    : ev.chain_status === 'PENDING' ? 'CHAIN PENDING'
                      : ev.chain_status === 'INVALID' ? 'CHAIN BROKEN' : 'UNVERIFIED';
                const badgeColor = integrityLabel === 'VERIFIED' ? 'ok'
                  : integrityLabel === 'CHAIN PENDING' || integrityLabel === 'UNVERIFIED' ? 'warning' : 'danger';
                return (
                  <div
                    key={ev.event_id}
                    onClick={() => setSelectedEvent(ev)}
                    className={`p-2 border rounded cursor-pointer transition-colors ${
                      isSelected
                        ? 'border-ok bg-[rgba(34,211,164,0.05)]'
                        : 'border-color hover-bg-elevated'
                    }`}
                  >
                    <div className="flex justify-between items-center mb-1">
                      <span className="font-display text-main" style={{ fontSize: '0.75rem' }}>
                        #{ev.event_id.split('-')[0]}
                      </span>
                      <span className={`text-[9px] px-1 font-display border rounded text-${badgeColor} border-${badgeColor}`}>
                        {integrityLabel}
                      </span>
                    </div>
                    <div className="font-body text-main mb-1 truncate" style={{ fontSize: '0.7rem' }}>
                      {ev.event_type || ev.decision_state}
                    </div>
                    <div className="text-muted font-body" style={{ fontSize: '0.6rem' }}>
                      {parseUtc(ev.timestamp).toISOString().substring(11, 19)} UTC • {ev.camera_id}
                    </div>
                    <div className="font-display" style={{ fontSize: '0.55rem', marginTop: '0.2rem' }}>
                      <span className={ev.hash_valid === true ? 'text-ok' : ev.hash_valid === false ? 'text-danger' : 'text-muted'}>HASH {ev.hash_valid === true ? 'VALID' : ev.hash_valid === false ? 'INVALID' : 'UNVERIFIED'}</span>
                      {' · '}
                      <span className={ev.signature_valid === true ? 'text-ok' : ev.signature_valid === false ? 'text-danger' : 'text-muted'}>SIG {ev.signature_valid === true ? 'VALID' : ev.signature_valid === false ? 'INVALID' : 'UNVERIFIED'}</span>
                      {' · '}
                      <span className={ev.chain_status === 'VALID' ? 'text-ok' : ev.chain_status === 'PENDING' ? 'text-warning' : 'text-danger'}>CHAIN {ev.chain_status || 'UNKNOWN'}</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex items-center justify-between gap-2 border-t border-color" style={{ paddingTop: '0.65rem', marginTop: '0.65rem' }}>
              <button className="btn btn-sm btn-outline" onClick={() => setPage(value => Math.max(0, value - 1))} disabled={page === 0}>PREVIOUS</button>
              <span className="text-muted font-display" style={{ fontSize: '0.58rem' }}>
                {totalEvidence ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, totalEvidence)} / ${totalEvidence}` : '0 / 0'}
              </span>
              <button className="btn btn-sm btn-outline" onClick={() => setPage(value => value + 1)} disabled={(page + 1) * pageSize >= totalEvidence}>NEXT</button>
            </div>
          </div>
        </div>

        {/* ── Center: Details + Media ── */}
        <div className="evidence-vault-detail flex-grow flex flex-col gap-4">
          {selectedEvent ? <>
          <div className="evidence-vault-detail-top flex gap-4">

            {/* Metadata card */}
            <div className="card flex-grow">
              <div className="card-header border-b border-color" style={{ paddingBottom: '0.75rem', marginBottom: '1rem' }}>
                <div className="flex flex-col">
                  <span className="text-main font-body" style={{ fontSize: '0.65rem' }}>
                    Event #{selectedEvent?.event_id.split('-')[0]}
                  </span>
                  <span className="card-title mt-1">
                    NETRAKSH INTEGRITY DEEP DIVE
                  </span>
                </div>
                {locallyVerified && (
                  <div className="badge badge-outline text-ok border-ok flex items-center gap-1.5 glow-ok">
                    <CheckCircle size={12} /> EVIDENCE VERIFIED
                  </div>
                )}
              </div>

              <div className="mb-6 px-4" style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(2, 1fr)',
                rowGap: '1.5rem', columnGap: '1rem',
              }}>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">CAPTURE TIME</span>
                  <span className="text-sm font-body">
                    {selectedEvent
                      ? parseUtc(selectedEvent.timestamp).toISOString().replace('T', ' ')
                      : 'N/A'}
                  </span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">EVIDENCE CREATED</span>
                  <span className="text-sm font-body">{selectedEvent?.evidence_created_at ? parseUtc(selectedEvent.evidence_created_at).toISOString().replace('T', ' ') : 'N/A'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">STORAGE</span>
                  <span className="text-sm font-body">{selectedEvent?.storage_provider || 'N/A'} · {selectedEvent?.storage_status || 'UNKNOWN'}{selectedEvent?.content_size != null ? ` · ${(selectedEvent.content_size / 1024).toFixed(1)} KB` : ''}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">INTEGRITY PROFILE</span>
                  <span className="text-sm font-body">Schema {selectedEvent?.schema_version || 'LEGACY'} · Crypto {selectedEvent?.crypto_version || 'LEGACY'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">SIGNING KEY ID</span>
                  <span className="text-sm font-body break-all">{selectedEvent?.kid || 'LEGACY KEY RESOLUTION'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">SOURCE STREAM</span>
                  <span className="text-sm font-body break-all">{selectedEvent?.stream_id || 'N/A'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">VIDEO POSITION</span>
                  <span className="text-sm font-body">{selectedEvent?.video_time != null ? `${Number(selectedEvent.video_time).toFixed(2)} s` : 'N/A'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">EVENT TYPE</span>
                  <span className="text-sm font-body border px-2 py-1 rounded w-max bg-[rgba(255,255,255,0.05)] border-color font-bold">
                    {selectedEvent?.event_type ? selectedEvent.event_type.replace(/_/g, ' ') : (selectedEvent?.decision_state || 'N/A')}
                  </span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">SENSOR ID</span>
                  <span className="text-sm font-body border px-2 py-1 rounded w-max">
                    {selectedEvent?.camera_id || 'N/A'}
                  </span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">DETECTION CLASS</span>
                  <span className="text-sm font-body">
                    {selectedEvent?.detection_class
                      ? (String(selectedEvent.detection_class).toLowerCase() === 'vehicle' ? 'VEHICLE / TRACK' : String(selectedEvent.detection_class).toUpperCase())
                      : 'N/A'}
                    {selectedEvent?.vehicle_subtype &&
                      ` (${String(selectedEvent.vehicle_subtype).toUpperCase()})`}
                  </span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">EDGE NODE</span>
                  <span className="text-sm font-body">
                    {selectedEvent?.edge_device_id
                      ? `${selectedEvent.edge_device_id} (Active)`
                      : <span className="text-muted">Not tracked</span>}
                  </span>
                </div>

                {/* Cross-camera corroboration */}
                <div className="flex-col" style={{ gridColumn: 'span 2' }}>
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">
                    CROSS-CAMERA CORROBORATION
                  </span>
                  {selectedEvent?.corroboration_status === 'CORROBORATED' ? (
                    <div className="flex-col gap-1">
                      <span className="text-sm font-body text-ok block">
                        Tc={selectedEvent.corroboration_score?.toFixed(2)} · camera{' '}
                        {selectedEvent.corroborating_camera_id?.split('-')[0]} event{' '}
                        {selectedEvent.corroborated_by_event_id?.split('-')[0]}
                        {selectedEvent.corroboration_distance_m != null &&
                          ` · ${selectedEvent.corroboration_distance_m.toFixed(0)}m away`}
                        {selectedEvent.corroboration_delta_t_s != null &&
                          ` · seen ${selectedEvent.corroboration_delta_t_s.toFixed(0)}s apart`}
                      </span>
                      <span className="text-[10px] text-muted font-display uppercase tracking-widest block mt-1">
                        Formula: Tc = e^(-|Δt - t_expected| / σ)
                        {selectedEvent.corroboration_t_expected_s != null &&
                          ` | Δt = ${selectedEvent.corroboration_delta_t_s?.toFixed(1)}s,
                            t_expected = ${selectedEvent.corroboration_t_expected_s?.toFixed(1)}s,
                            σ = ${selectedEvent.corroboration_sigma_s?.toFixed(1)}s`}
                      </span>
                    </div>
                  ) : selectedEvent?.corroboration_status === 'NO_MATCH' ? (
                    <span className="text-sm font-body text-warning block mt-1">
                      NO CORROBORATION: no physically plausible matching event found
                    </span>
                  ) : (
                    <span className="text-sm font-body text-muted block mt-1">
                      CORROBORATION UNAVAILABLE: Missing GPS or insufficient event data
                    </span>
                  )}
                </div>

                {/* Reliability scoring */}
                <div className="flex-col" style={{ gridColumn: 'span 2' }}>
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">
                    RELIABILITY SCORING
                  </span>
                  {selectedEvent?.score_r != null ? (
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] text-muted font-display uppercase tracking-widest block mt-1">
                        Formula: R = (0.40 × D) + (0.20 × T) + (0.20 × S) + (0.20 × H)
                      </span>
                      <span className="text-sm font-body">
                        D = {selectedEvent.score_d?.toFixed(2)} | T = {selectedEvent.score_t?.toFixed(2)} | S = {selectedEvent.score_s?.toFixed(2)} | H = {selectedEvent.score_h?.toFixed(2)}
                      </span>
                      <span className="text-sm font-body font-bold text-main mt-1">
                        R = {selectedEvent.score_r?.toFixed(3)}
                      </span>
                    </div>
                  ) : (
                    <span className="text-sm font-body block">
                      {selectedEvent?.decision_reason || 'N/A'}
                    </span>
                  )}
                </div>

                {/* Watchlist match (face events only) */}
                {selectedEvent?.detection_class === 'face' && (
                  <div className="flex-col" style={{ gridColumn: 'span 2' }}>
                    <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">
                      WATCHLIST MATCH
                    </span>
                    {selectedEvent?.face_match_person_id ? (
                      <span className="text-sm font-body text-danger">
                        {selectedEvent.face_match_person_name} (LBPH distance=
                        {selectedEvent.face_match_confidence?.toFixed(1)}, lower=stronger) —
                        lead for human review, not a confirmed identification
                      </span>
                    ) : (
                      <span className="text-sm font-body text-muted">No watchlist match</span>
                    )}
                  </div>
                )}
              </div>
              
              <div className="px-4 pb-4">
                <button
                  onClick={handleVerify}
                  disabled={verifyStatus === 'verifying'}
                  className="btn btn-primary w-full flex items-center justify-center gap-2"
                >
                  <GitBranch size={16} />
                  {verifyStatus === 'verifying' ? 'Verifying Chain…' : 'Verify Netraksh Integrity Chain'}
                </button>
              </div>
            </div>

            {/* ── Evidence media card (FIXED: img + SVG overlay, not backgroundImage) ── */}
            <div
              className="card flex-shrink-0"
              style={{ width: '300px', minHeight: '220px', padding: '0.5rem' }}
            >
              <EvidenceImageOverlay
                imageUrl={displayImageUrl}
                event={selectedEvent}
                status={evidenceImageStatus}
              />
            </div>
          </div>

          {/* ── Cryptographic hash verification panel ── */}
          <div className="card mt-auto">
            <div className="card-header border-b border-color" style={{ paddingBottom: '0.75rem', marginBottom: '1.5rem' }}>
              <div className="flex items-center gap-2">
                <GitBranch size={14} className="text-muted" />
                <span className="card-title">
                  Cryptographic Hash Verification
                </span>
              </div>
            </div>

            <div className="flex justify-between relative px-8">
              {/* Connecting line */}
              <div
                className="absolute top-6 bg-color border-b border-color -z-10"
                style={{ left: '10%', right: '10%', height: '1px' }}
              />
              <VerificationStep
                icon={Database} title="Event Data Extracted"
                status={selectedEvent?.storage_status === 'AVAILABLE' ? 'AVAILABLE' : (selectedEvent?.storage_status || 'UNKNOWN')}
                active={selectedEvent?.storage_status === 'AVAILABLE'}
              />
              <VerificationStep
                icon={Shield} title="Content Hash"
                status={currentVerification?.hash_valid === true ? 'VALID' : currentVerification?.hash_valid === false ? 'INVALID' : 'UNVERIFIED'}
                active={currentVerification?.hash_valid === true}
              />
              <VerificationStep
                icon={Lock} title="Ed25519 Signature"
                status={currentVerification?.signature_valid === true ? 'VALID' : currentVerification?.signature_valid === false ? 'INVALID' : 'UNVERIFIED'}
                active={currentVerification?.signature_valid === true}
              />
              <VerificationStep
                icon={GitBranch} title="Local Chain Check"
                status={currentVerification?.chain_status || 'UNVERIFIED'}
                active={currentVerification?.chain_valid === true}
              />
              <VerificationStep
                icon={Cloud} title="External Anchor"
                status="UNAVAILABLE (MOCK)"
                active={false}
              />
            </div>

            {/* Hash detail area */}
            {currentVerification && (
              <div className="mt-6 mx-4 mb-4 p-3 bg-dark border border-color rounded">
                <div className="flex flex-col gap-2">
                  <div className="flex justify-between items-center">
                    <span className="font-display text-muted uppercase" style={{ fontSize: '0.65rem' }}>Hashed Artifact</span>
                    <span className="font-body text-main ml-4 text-right" style={{ fontSize: '0.7rem' }}>
                      Evidence Package (payload fields)
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="font-display text-muted uppercase" style={{ fontSize: '0.65rem' }}>Calculated SHA-256</span>
                    <span className="font-body text-main break-all ml-4 text-right select-all" style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)' }}>
                      {currentVerification.calculated_hash || 'Run verification to recompute'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="font-display text-muted uppercase" style={{ fontSize: '0.65rem' }}>Stored SHA-256 (evidence_packages)</span>
                    <span className="font-body text-main break-all ml-4 text-right select-all" style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)' }}>
                      {currentVerification.stored_hash || 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center border-t border-color pt-2">
                    <span className="font-display text-muted uppercase" style={{ fontSize: '0.65rem' }}>Ed25519 Signature</span>
                    <span className={`font-body font-bold ml-4 text-right ${
                      currentVerification.signature_valid ? 'text-ok' : 'text-danger'
                    }`} style={{ fontSize: '0.7rem' }}>
                      {currentVerification.signature_valid ? '✓ VALID' : '✗ INVALID'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="font-display text-muted uppercase" style={{ fontSize: '0.65rem' }}>Hash Chain</span>
                    <span className={`font-body font-bold ml-4 text-right ${
                      currentVerification.chain_valid ? 'text-ok' : currentVerification.chain_status === 'PENDING' ? 'text-warning' : 'text-danger'
                    }`} style={{ fontSize: '0.7rem' }}>
                      {currentVerification.chain_valid ? '✓ VALID' : currentVerification.chain_status === 'PENDING' ? '⌛ PENDING — PREDECESSOR NOT YET RESOLVED' : `✗ ${currentVerification.chain_status || 'BROKEN'}`}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="font-display text-muted uppercase" style={{ fontSize: '0.65rem' }}>Previous Evidence Hash</span>
                    <span className="font-body text-main break-all ml-4 text-right select-all" style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)' }}>
                      {selectedEvent?.previous_hash || 'GENESIS / NO PREDECESSOR'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="font-display text-muted uppercase" style={{ fontSize: '0.65rem' }}>Last Verified</span>
                    <span className="font-body text-main ml-4 text-right" style={{ fontSize: '0.7rem' }}>
                      {currentVerification.verified_at ? parseUtc(currentVerification.verified_at).toISOString().replace('T', ' ') : 'Never'}
                    </span>
                  </div>
                  {selectedEvent?.blockchain_tx_id && (
                    <>
                      <div className="flex justify-between items-center border-t border-color pt-2">
                        <span className="font-display text-muted uppercase" style={{ fontSize: '0.65rem' }}>External Ledger Anchor</span>
                        <span className="font-body text-warning font-bold break-all ml-4 text-right" style={{ fontSize: '0.7rem' }}>
                          LOCAL MOCK RECEIPT — NOT FABRIC ANCHORED
                        </span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="font-display text-muted uppercase" style={{ fontSize: '0.65rem' }}>Mock Ledger Reference</span>
                        <span className="font-body text-warning break-all ml-4 text-right select-all" style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)' }}>
                          {selectedEvent.blockchain_tx_id}
                        </span>
                      </div>
                    </>
                  )}
                  {locallyVerified ? (
                    <div className="text-ok font-display text-xs uppercase text-center mt-2 flex items-center justify-center gap-1">
                      <CheckCircle size={14} /> INTEGRITY VERIFIED
                    </div>
                  ) : (
                    <div className="text-danger font-display text-xs uppercase text-center mt-2 flex items-center justify-center gap-1">
                      LOCAL INTEGRITY NOT FULLY VERIFIED — {currentVerification.chain_status || 'UNVERIFIED'}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
          </> : (
            <div className="card state-empty" style={{ minHeight: '260px' }}>
              <div className="state-empty-sub">SELECT AN EVIDENCE RECORD TO INSPECT FORENSIC DETAILS</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
