import { User, Activity, AlertTriangle, Cpu, ChevronDown, ShieldCheck, ShieldAlert, LogOut, Radio } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import Logo from './Logo';
import { authFetch, logout, BACKEND_URL, WS_URL } from '../services/auth';
import useAuth from '../hooks/useAuth';
import useWebSocket from '../hooks/useWebSocket';
import { deriveGlobalEdgeStatus } from '../utils/liveMetrics';
import { startupWakeState } from '../services/startupWake';

// Freshness thresholds for edge telemetry
const EDGE_STALE_MS  = 30_000;   // >30s without telemetry → STALE
const EDGE_OFFLINE_MS = 120_000; // >2 min → OFFLINE

const ROLE_COLORS = {
  ADMIN:    { text: 'var(--color-danger)', border: 'var(--color-danger)' },
  OPERATOR: { text: 'var(--color-ok)',     border: 'var(--color-ok)'     },
  AUDITOR:  { text: 'var(--color-warning)',border: 'var(--color-warning)'},
};

export default function Header() {
  const { isAuthenticated, role, username } = useAuth();
  // Keep one lightweight application-level subscription alive on every
  // protected route. Data-heavy pages may create their own hook instance for
  // local state, but global system status must not falsely show DISCONNECTED
  // on pages such as Audit that do not otherwise consume realtime data.
  const { isConnected: isWsConnected, lastTelemetryAt } = useWebSocket(
    WS_URL,
    { fetchInitial: false },
  );
  const [timeStr, setTimeStr]           = useState('');
  const [showSyncPanel, setShowSyncPanel]       = useState(false);
  const [showAccountPanel, setShowAccountPanel] = useState(false);
  const [syncStatus, setSyncStatus]     = useState({ queued: 0, synced: 0, failed: 0 });
  const [pendingAlerts, setPendingAlerts] = useState(null);
  const [chainStatus, setChainStatus]   = useState(null);
  const [edgeWakeUntil, setEdgeWakeUntil] = useState(0);
  const [edgeTelemetrySignalAt, setEdgeTelemetrySignalAt] = useState(0);
  const [analysisStates, setAnalysisStates] = useState([]);
  const [edgePrewarm, setEdgePrewarm] = useState(null);
  const [startupWakeRequested, setStartupWakeRequested] = useState(() => startupWakeState().requested);

  // ── Real connectivity & edge freshness ────────────────────────────────────
  // Accept freshness from both this header's socket hook and the application
  // telemetry event emitted by any active dashboard socket. This prevents the
  // top bar from remaining WAKING when real edge telemetry is already flowing.
  const lastEdgeTelemetryMs = Math.max(lastTelemetryAt || 0, edgeTelemetrySignalAt || 0);
  // backendHealthy: whether GET /health returned 200 recently
  const [backendHealthy, setBackendHealthy] = useState(true);

  // ── Live clock ──────────────────────────────────────────────────────────
  useEffect(() => {
    const timer = setInterval(() => {
      const d = new Date();
      setTimeStr(d.toISOString().substring(11, 19));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Dashboard publishes per-camera analysis intent separately from worker
  // process connectivity. A finite upload that reached EOF is idle, not
  // offline, even though its last telemetry packet is old.
  useEffect(() => {
    const onAnalysisState = (event) => {
      const states = event?.detail?.cameraStates;
      if (Array.isArray(states)) setAnalysisStates(states);
    };
    window.addEventListener('netraksh:analysis-state', onAnalysisState);
    return () => window.removeEventListener('netraksh:analysis-state', onAnalysisState);
  }, []);

  // ── Backend health check (HTTP GET /health, every 10s) ──────────────────
  // Distinct from WS — backend may be reachable via HTTP even if WS drops.
  useEffect(() => {
    if (!isAuthenticated) return;
    const check = async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/health`, {
          signal: AbortSignal.timeout(3000),
        });
        setBackendHealthy(res.ok);
      } catch {
        setBackendHealthy(false);
      }
    };
    check();
    const t = setInterval(check, 10_000);
    return () => clearInterval(t);
  }, [isAuthenticated]);

  // Dashboard START / ANALYZE emits this local event while the backend keeps
  // the bounded free-tier cold-start retry alive.  It prevents a sleeping
  // worker from making the entire system look offline while control-plane and
  // WebSocket connectivity are healthy.
  useEffect(() => {
    const onWake = (event) => {
      if (event?.detail?.status === 'WAKING') setEdgeWakeUntil(Date.now() + 305_000);
      if (event?.detail?.status === 'LIVE') setEdgeWakeUntil(0);
    };
    const onTelemetry = (event) => {
      const ts = Number(event?.detail?.ts);
      const observedAt = Number.isFinite(ts) ? ts : Date.now();
      setEdgeTelemetrySignalAt(observedAt);
      setEdgeWakeUntil(0);
    };
    const onPrewarm = (event) => {
      const detail = event?.detail;
      if (detail && typeof detail === 'object') setEdgePrewarm(detail);
    };
    const onStartupWake = () => setStartupWakeRequested(true);
    window.addEventListener('netraksh:edge-wake', onWake);
    window.addEventListener('netraksh-edge-telemetry', onTelemetry);
    window.addEventListener('netraksh:edge-prewarm', onPrewarm);
    window.addEventListener('netraksh:startup-wake', onStartupWake);
    return () => {
      window.removeEventListener('netraksh:edge-wake', onWake);
      window.removeEventListener('netraksh-edge-telemetry', onTelemetry);
      window.removeEventListener('netraksh:edge-prewarm', onPrewarm);
      window.removeEventListener('netraksh:startup-wake', onStartupWake);
    };
  }, []);

  // ── Sync status (real queue size from /sync/status) ─────────────────────
  useEffect(() => {
    if (!isAuthenticated) return undefined;
    const fetchSync = async () => {
      try {
        const res = await authFetch('/sync/status');
        if (res.ok) setSyncStatus(await res.json());
      } catch (_) {}
    };
    fetchSync();
    const timer = setInterval(fetchSync, 5000);
    return () => clearInterval(timer);
  }, [isAuthenticated]);

  // ── Alert count (real from /system/status) ──────────────────────────────
  useEffect(() => {
    if (!isAuthenticated) return undefined;
    const fetchAlertCount = async () => {
      try {
        const res = await authFetch('/system/status');
        if (res.ok) {
          const data = await res.json();
          setPendingAlerts(data.pending_acknowledgements);
        }
      } catch (_e) {}
    };
    fetchAlertCount();
    const timer = setInterval(fetchAlertCount, 5000);
    return () => clearInterval(timer);
  }, [isAuthenticated]);

  // ── Chain integrity (on panel open) ────────────────────────────────────
  useEffect(() => {
    if (!showSyncPanel) return;
    const fetchChainStatus = async () => {
      try {
        const res = await authFetch('/system/verify-chain');
        if (res.ok) setChainStatus(await res.json());
      } catch (_e) {}
    };
    fetchChainStatus();
  }, [showSyncPanel]);

  // ── Derived status values ────────────────────────────────────────────────
  // Each signal is independent:

  // SYSTEM: reflects API/backend reachability + WS state
  const systemStatus =
    !backendHealthy  ? 'OFFLINE'     :
    !isWsConnected   ? 'DEGRADED'    :
                       'OPERATIONAL';
  const systemColor =
    systemStatus === 'OPERATIONAL' ? 'var(--color-ok)'      :
    systemStatus === 'DEGRADED'    ? 'var(--color-warning)'  :
                                     'var(--color-danger)';

  // EDGE: reflects analysis intent plus telemetry freshness. Worker/process
  // health is intentionally not treated as active analysis.
  const edgeAgeMs = lastEdgeTelemetryMs ? (Date.now() - lastEdgeTelemetryMs) : Infinity;
  const edgeWaking = edgeWakeUntil > Date.now();
  const activeStates = analysisStates.filter((state) => state.intent === 'ACTIVE');
  const anyActive = activeStates.length > 0;
  const anyWaking = analysisStates.some((state) => state.intent === 'WAKING') || (edgeWaking && !anyActive);
  const activeTelemetryAgeMs = activeStates.reduce((oldest, state) => Math.max(oldest, state.ageMs ?? Infinity), 0);
  // Fresh telemetry is stronger evidence than an outstanding wake timer.
  // Until Dashboard publishes intent, retain the legacy telemetry-only
  // fallback used by other protected pages.
  const edgeStatus = deriveGlobalEdgeStatus({
    analysisStates,
    lastTelemetryAt: lastEdgeTelemetryMs,
    edgeWakeUntil,
    prewarm: edgePrewarm,
    startupWakeRequested,
  });
  const edgeColor =
    edgeStatus === 'ONLINE'  ? 'var(--color-ok)'     :
    edgeStatus === 'READY' ? 'var(--color-ok)' :
    edgeStatus === 'STALE' || edgeStatus === 'WAKING' || edgeStatus === 'WARMING' ? 'var(--color-warning)' :
    edgeStatus === 'UNAVAILABLE' ? 'var(--color-danger)' :
                               'var(--text-dim)';
  const edgeDisplay = edgeStatus === 'WARMING'
    ? `WARMING · ${Number(edgePrewarm?.ready || 0)}/${Number(edgePrewarm?.eligible || 0)}`
    : edgeStatus === 'READY'
      ? `READY · ${Number(edgePrewarm?.ready || 0)}/${Number(edgePrewarm?.eligible || 0)}`
      : edgeStatus === 'UNAVAILABLE'
        ? `UNAVAILABLE · ${Number(edgePrewarm?.ready || 0)}/${Number(edgePrewarm?.eligible || 0)}`
      : edgeStatus;

  // SYNC: reflects WS link + queue state
  const syncBuffering = syncStatus.queued > 0;
  const syncStatus_val =
    !isWsConnected ? 'DISCONNECTED' :
    syncBuffering   ? 'BUFFERING'   :
                      'CURRENT';
  const syncColor =
    syncStatus_val === 'CURRENT'      ? 'var(--color-ok)'     :
    syncStatus_val === 'BUFFERING'    ? 'var(--color-warning)' :
                                        'var(--color-danger)';

  const roleStyle = ROLE_COLORS[role] || ROLE_COLORS.OPERATOR;

  const StatusItem = ({ label, value, valueColor }) => (
    <div className="topbar-status-item">
      <span className="topbar-status-label">{label}</span>
      <span className="topbar-status-value" style={{ color: valueColor || 'var(--text-main)' }}>
        {value}
      </span>
    </div>
  );

  return (
    <header className="header-top relative">
      {/* Left — Brand */}
      <div className="topbar-brand">
        <Logo size={28} />
        <div className="topbar-brand-text">
          <span className="topbar-title">NETRAKSH</span>
          <span className="topbar-sub">Border Intelligence Command Center</span>
        </div>
      </div>

      {/* Center — Mission Status Strip */}
      <div className="topbar-status-strip">
        <StatusItem
          label="Command Zone"
          value="Sector Alpha"
          valueColor="var(--accent)"
        />
        <StatusItem
          label="System"
          value={systemStatus}
          valueColor={systemColor}
        />
        <StatusItem
          label="Edge"
          value={edgeDisplay}
          valueColor={edgeColor}
        />
        <StatusItem
          label="Sync"
          value={syncStatus_val}
          valueColor={syncColor}
        />
      </div>

      {/* Right — Time + Alerts + Account */}
      <div className="topbar-right">
        {/* Time */}
        <div className="topbar-time">
          <span className="topbar-time-value">{timeStr} UTC</span>
          <span className="topbar-time-label">System Time</span>
        </div>

        {/* Sync detail panel toggle */}
        <button
          onClick={() => { setShowSyncPanel(!showSyncPanel); setShowAccountPanel(false); }}
          style={{
            display: 'flex', alignItems: 'center', gap: '0.3rem',
            padding: '0.3rem 0.625rem', borderRadius: 'var(--radius-md)',
            background: 'transparent', border: '1px solid var(--border-color)',
            color: 'var(--text-muted)', fontSize: '0.7rem',
            fontFamily: 'var(--font-display)', letterSpacing: '0.08em',
            textTransform: 'uppercase', cursor: 'pointer',
            transition: 'all 0.15s ease',
          }}
          className="hover:text-main"
          title="Sync Status"
        >
          <Activity size={12} style={{ color: syncColor }} />
          Sync
          <ChevronDown size={10} />
        </button>

        {/* Alert Badge */}
        <Link
          to="/cross-command-alerts"
          className="badge badge-danger"
          style={{ padding: '0.3rem 0.7rem', fontSize: '0.75rem' }}
          title="Pending alerts"
        >
          <AlertTriangle size={12} />
          {pendingAlerts != null ? String(pendingAlerts).padStart(2, '0') : '--'}
        </Link>

        {/* Account button */}
        <button
          onClick={() => { setShowAccountPanel(!showAccountPanel); setShowSyncPanel(false); }}
          style={{
            width: 32, height: 32, borderRadius: '50%',
            background: 'var(--bg-elevated)',
            border: `1px solid ${roleStyle.border}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: roleStyle.text, cursor: 'pointer',
            transition: 'all 0.15s ease',
          }}
          title={isAuthenticated ? `${username} (${role})` : 'Not signed in'}
        >
          <User size={14} />
        </button>
      </div>

      {/* Account Dropdown */}
      {showAccountPanel && (
        <div
          className="absolute bg-panel border rounded shadow-lg flex flex-col gap-3"
          style={{ top: 'calc(100% + 8px)', right: '1rem', width: 220, padding: '1rem', zIndex: 50 }}
        >
          {isAuthenticated && (
            <>
              <div className="flex justify-between items-center border-b border-color pb-2">
                <span className="text-xs font-display text-muted uppercase tracking-widest">Session</span>
                <span
                  style={{
                    fontSize: '0.6rem', fontFamily: 'var(--font-display)',
                    fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
                    padding: '0.1rem 0.4rem', borderRadius: 'var(--radius-sm)',
                    border: `1px solid ${roleStyle.border}`, color: roleStyle.text,
                  }}
                >{role}</span>
              </div>
              <div style={{ fontSize: '0.875rem', fontFamily: 'var(--font-body)', color: 'var(--text-main)' }}>
                {username}
              </div>
              <button
                onClick={() => { logout(); setShowAccountPanel(false); }}
                className="btn btn-danger"
                style={{ justifyContent: 'center' }}
              >
                <LogOut size={12} /> Sign Out
              </button>
            </>
          )}
        </div>
      )}

      {/* Sync Panel */}
      {showSyncPanel && (
        <div
          className="absolute bg-panel border rounded shadow-lg flex flex-col gap-3"
          style={{ top: 'calc(100% + 8px)', right: '7rem', width: 260, padding: '1rem', zIndex: 50 }}
        >
          <div className="flex justify-between items-center border-b border-color pb-2">
            <span className="text-xs font-display text-muted uppercase tracking-widest">Edge Sync Status</span>
            <div
              style={{
                width: 8, height: 8, borderRadius: '50%',
                background: syncColor,
                animation: syncBuffering ? 'pulse 2s infinite' : 'none',
              }}
            />
          </div>

          {/* Real status rows */}
          {[
            { label: 'System',    val: systemStatus,   col: systemColor },
            { label: 'Edge',      val: edgeStatus,     col: edgeColor   },
            { label: 'Sync',      val: syncStatus_val, col: syncColor   },
            { label: 'Buffered',  val: syncStatus.queued,  col: syncBuffering ? 'var(--color-warning)' : 'var(--text-main)' },
            { label: 'Synced',    val: syncStatus.synced,  col: 'var(--color-ok)' },
          ].map(({ label, val, col }) => (
            <div key={label} className="flex justify-between" style={{ fontSize: '0.8rem', fontFamily: 'var(--font-body)' }}>
              <span className="text-muted">{label}:</span>
              <span style={{ color: col, fontWeight: 600 }}>{val}</span>
            </div>
          ))}

          {/* Edge staleness note */}
          {edgeStatus !== 'ONLINE' && (
            <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)', fontFamily: 'var(--font-body)', lineHeight: 1.4, paddingTop: '0.25rem', borderTop: '1px solid var(--border-color)' }}>
              {edgeStatus === 'STALE'
                ? 'No recent current-run edge telemetry.'
                : edgeStatus === 'WAKING'
                  ? 'Analysis start accepted. Waiting for fresh current-run edge telemetry.'
                  : 'No analysis is currently running. Edge workers may sleep until START / ANALYZE.'}
            </div>
          )}

          <div className="mt-2 pt-2 border-t border-color flex items-center gap-2" style={{ fontSize: '0.7rem', fontFamily: 'var(--font-display)' }}>
            {chainStatus == null ? (
              <span className="text-muted">Checking chain integrity…</span>
            ) : chainStatus.is_valid ? (
              <>
                <ShieldCheck size={13} className="text-ok" />
                <span className="text-ok">{chainStatus.message}</span>
              </>
            ) : (
              <>
                <ShieldAlert size={13} className="text-danger" />
                <span className="text-danger">{chainStatus.message}</span>
              </>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
