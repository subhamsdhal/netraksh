import { useState, useEffect, useCallback, useMemo } from 'react';
import { AlertTriangle, Globe, Crosshair, MapPin, CheckCircle, Eye, Shield } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import { WS_URL, authFetch } from '../services/auth';
import useAuth from '../hooks/useAuth';
import TacticalMap from '../components/TacticalMap';
import { parseUtc } from '../utils/time';

// Real alert data has no free-text title/description field anywhere in the
// data model (AlertResponse only carries severity/camera/zone/event_type/
// jurisdiction/blockchain/ack fields) — these derive a readable headline
// from what actually exists, instead of claiming specific incident text
// ("Multiple Armed Intruders") that was never real.
const EVENT_TYPE_LABELS = {
  VIRTUAL_FENCE_CROSSING: 'Virtual Fence Crossing',
  LINE_CROSSING:          'Line Crossing',
  LOITERING:              'Loitering Detected',
  ABANDONED_OBJECT:       'Abandoned Object',
  VEHICLE_DETECTED:       'Vehicle Detected',
};

function alertTitle(alert) {
  const type = EVENT_TYPE_LABELS[alert.event_type] || alert.event_type || alert.decision_state || 'Escalated Event';
  return `${alert.severity} — ${type}`;
}

function severityClass(severity) {
  if (!severity) return 'severity-medium';
  const s = severity.toUpperCase();
  if (s === 'HIGH' || s === 'CRITICAL')    return 'severity-high';
  if (s === 'MEDIUM' || s === 'ELEVATED')  return 'severity-medium';
  return 'severity-low';
}

function severityBadgeColor(severity) {
  const s = (severity || '').toUpperCase();
  if (s === 'CRITICAL') return { color: '#dc2626', bg: 'rgba(220,38,38,0.1)', border: 'rgba(220,38,38,0.3)' };
  if (s === 'HIGH')     return { color: 'var(--color-danger)',  bg: 'rgba(239,68,68,0.1)',  border: 'rgba(239,68,68,0.3)' };
  if (s === 'MEDIUM' || s === 'ELEVATED')
                        return { color: 'var(--color-warning)', bg: 'rgba(245,158,11,0.1)', border: 'rgba(245,158,11,0.3)' };
  return               { color: 'var(--text-muted)', bg: 'rgba(77,96,128,0.1)', border: 'rgba(77,96,128,0.2)' };
}

function formatAge(ts) {
  if (!ts) return '—';
  const diff = Math.floor((Date.now() - (parseUtc(ts) || new Date())) / 60000);
  if (diff < 1) return 'just now';
  if (diff < 60) return `${diff}m ago`;
  return `${Math.floor(diff / 60)}h ${diff % 60}m ago`;
}

export default function Alerts() {
  // REST below owns the initial lifecycle snapshot. Avoid the hook's
  // unrelated five-request bootstrap here; this page only needs its live
  // WebSocket alert additions.
  const { alerts: wsAlerts } = useWebSocket(WS_URL, { fetchInitial: false });
  const { role } = useAuth();
  // Backend's real RBAC (require_operator_or_admin, backend/api/alerts.py)
  // already rejects AUDITOR's acknowledge attempt with a 403 — this just
  // reflects that real permission in the UI instead of letting an AUDITOR
  // click a button that was always going to fail.
  const canAcknowledge = role === 'ADMIN' || role === 'OPERATOR';
  const [restAlerts, setRestAlerts] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | auth-required | error
  const [ackingId, setAckingId] = useState(null);
  const [closingId, setClosingId] = useState(null);
  const [severityFilter, setSeverityFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  const loadAlerts = useCallback(async () => {
    setStatus('loading');
    try {
      // The page exposes a CLOSED filter, so request lifecycle history rather
      // than the backend's active-only default.
      const res = await authFetch('/alerts?include_closed=true');
      if (res.status === 403) {
        setStatus('access-denied');
        return;
      }
      if (!res.ok) {
        setStatus('error');
        return;
      }
      setRestAlerts(await res.json());
      setStatus('ready');
    } catch (_e) {
      setStatus('error');
    }
  }, []);

  useEffect(() => { loadAlerts(); }, [loadAlerts]);

  // Real alerts only — deduped by alert_id from REST + WS
  const realAlerts = useMemo(() => {
    const byId = new Map();
    // WebSocket creation payloads are immutable snapshots and therefore do
    // not learn about a later acknowledge/close transition. Seed from WS so
    // newly-created alerts appear immediately, then let the fresh REST load
    // win for lifecycle fields after an operator action or refresh.
    for (const a of wsAlerts) byId.set(a.alert_id, a);
    for (const a of restAlerts) byId.set(a.alert_id, { ...byId.get(a.alert_id), ...a });
    return [...byId.values()].sort((a, b) =>
      (parseUtc(b.timestamp || b.created_at) || new Date(0)) - (parseUtc(a.timestamp || a.created_at) || new Date(0))
    );
  }, [restAlerts, wsAlerts]);

  const displayAlerts = useMemo(() => {
    return realAlerts.filter(a => {
      if (severityFilter !== 'all' && (a.severity || '').toUpperCase() !== severityFilter) return false;
      if (statusFilter === 'open' && (a.acknowledged_at || a.closed_at)) return false;
      if (statusFilter === 'ack' && !a.acknowledged_at) return false;
      if (statusFilter === 'closed' && !a.closed_at) return false;
      return true;
    });
  }, [realAlerts, severityFilter, statusFilter]);

  const handleAcknowledge = async (alertId) => {
    setAckingId(alertId);
    try {
      const res = await authFetch(`/alerts/${alertId}/acknowledge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ receiving_command_id: 'COMMAND_A', status: 'ACKNOWLEDGED' }),
      });
      if (res.ok) await loadAlerts();
    } catch (_e) {
      // best-effort
    } finally {
      setAckingId(null);
    }
  };

  // Real terminal close action (POST /alerts/{id}/close)
  const handleClose = async (alertId) => {
    setClosingId(alertId);
    try {
      const res = await authFetch(`/alerts/${alertId}/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (res.ok) await loadAlerts();
    } catch (_e) {
      // best-effort
    } finally {
      setClosingId(null);
    }
  };

  const FilterBtn = ({ value, label, current, onChange }) => (
    <button
      onClick={() => onChange(value)}
      style={{
        padding: '0.3rem 0.75rem',
        borderRadius: 'var(--radius-md)',
        borderStyle: 'solid',
        borderWidth: '1px',
        borderColor: current === value ? 'var(--accent)' : 'var(--border-color)',
        background: current === value ? 'var(--accent-dim)' : 'transparent',
        color: current === value ? 'var(--accent)' : 'var(--text-muted)',
        fontFamily: 'var(--font-display)',
        fontSize: '0.6rem',
        fontWeight: 700,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        cursor: 'pointer',
        transition: 'all 0.15s ease',
      }}
    >
      {label}
    </button>
  );

  return (
    <div className="h-full flex flex-col" style={{ gap: '1rem' }}>
      {/* Page Header */}
      <div className="section-header">
        <div>
          <div className="section-title">Alerts &amp; Incidents</div>
          <div className="section-sub">
            Cross-command escalated events · Temporal/spatial corroboration active
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div
            style={{
              display: 'flex', alignItems: 'center', gap: '0.375rem',
              padding: '0.3rem 0.75rem',
              borderRadius: 'var(--radius-md)',
              border: '1px solid rgba(34,211,164,0.25)',
              background: 'rgba(34,211,164,0.06)',
              fontSize: '0.6rem',
              fontFamily: 'var(--font-display)',
              letterSpacing: '0.1em',
              color: 'var(--color-ok)',
              fontWeight: 700,
              textTransform: 'uppercase',
            }}
          >
            <Shield size={11} />
            Network Secure
          </div>
          <div className="badge badge-outline">
            {realAlerts.length} Total
          </div>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.6rem', fontFamily: 'var(--font-display)', color: 'var(--text-dim)', letterSpacing: '0.1em', textTransform: 'uppercase', marginRight: '0.25rem' }}>Severity:</span>
        {['all', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(v => (
          <FilterBtn key={v} value={v} label={v === 'all' ? 'All' : v} current={severityFilter} onChange={setSeverityFilter} />
        ))}
        <div style={{ width: 1, height: 18, background: 'var(--border-color)', margin: '0 0.25rem' }} />
        <span style={{ fontSize: '0.6rem', fontFamily: 'var(--font-display)', color: 'var(--text-dim)', letterSpacing: '0.1em', textTransform: 'uppercase', marginRight: '0.25rem' }}>Status:</span>
        {[['all', 'All'], ['open', 'Open'], ['ack', 'Acknowledged'], ['closed', 'Closed']].map(([v, l]) => (
          <FilterBtn key={v} value={v} label={l} current={statusFilter} onChange={setStatusFilter} />
        ))}
      </div>

      {status === 'access-denied' && (
        <div className="card" style={{ maxWidth: 380, borderColor: 'rgba(239,68,68,0.3)' }}>
          <h3 className="text-danger font-display tracking-widest uppercase" style={{ fontSize: '0.8rem' }}>Access Denied</h3>
          <p className="text-muted text-sm mt-2">You do not have permission to access this module.</p>
        </div>
      )}

      {status !== 'access-denied' && (
        <div className="flex gap-4 flex-grow" style={{ minHeight: 0 }}>
          {/* Alert List */}
          <div className="flex flex-col overflow-y-auto pr-1" style={{ flex: '1 1 0%', minWidth: 0, gap: '0.625rem' }}>
            {status === 'loading' && (
              <div className="state-loading"><span>Loading incidents…</span></div>
            )}
            {status === 'error' && (
              <div className="state-error"><AlertTriangle size={20} /><span>Could not reach the backend.</span></div>
            )}
            {displayAlerts.length === 0 && status === 'ready' && (
              <div className="state-empty">
                <CheckCircle size={28} className="state-empty-icon" />
                <div className="state-empty-title">No Active Incidents</div>
                <div className="state-empty-sub">No alerts match the current filters. The sector is clear.</div>
              </div>
            )}

            {displayAlerts.map(alert => {
              const sc = severityBadgeColor(alert.severity);
              const isOpen = !alert.acknowledged_at && !alert.closed_at;
              return (
                <div
                  key={alert.alert_id}
                  className={`incident-card ${severityClass(alert.severity)}`}
                >
                  {/* Header row */}
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <AlertTriangle size={14} style={{ color: sc.color, flexShrink: 0 }} />
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '0.65rem',
                          color: 'var(--text-dim)',
                          letterSpacing: '0.06em',
                        }}
                      >
                        #{alert.alert_id?.substring(0, 8)}
                      </span>
                      {alert.isMock && (
                        <span className="badge badge-outline" style={{ fontSize: '0.5rem' }}>DEMO</span>
                      )}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', flexShrink: 0 }}>
                      <span
                        style={{
                          fontSize: '0.6rem', fontFamily: 'var(--font-display)',
                          fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
                          padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)',
                          color: sc.color, background: sc.bg, border: `1px solid ${sc.border}`,
                        }}
                      >
                        {alert.severity}
                      </span>
                      {alert.closed_at ? (
                        <span className="badge badge-neutral" style={{ fontSize: '0.55rem' }}>CLOSED</span>
                      ) : alert.acknowledged_at ? (
                        <span className="badge badge-ok" style={{ fontSize: '0.55rem' }}>ACK</span>
                      ) : (
                        <span className="badge badge-danger" style={{ fontSize: '0.55rem', animation: 'pulse 2s infinite' }}>OPEN</span>
                      )}
                    </div>
                  </div>

                  {/* Title */}
                  <div
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: '0.875rem',
                      fontWeight: 700,
                      color: 'var(--text-main)',
                      letterSpacing: '0.04em',
                    }}
                  >
                    {alert.isMock ? alert.event_type : alertTitle(alert)}
                  </div>

                  {/* Corroboration */}
                  {!alert.isMock && alert.escalated_via_corroboration && (
                    <div style={{ fontSize: '0.7rem', color: 'var(--color-ok)', fontFamily: 'var(--font-body)' }}>
                      Escalated via temporal/spatial corroboration — multi-camera corroborated event.
                    </div>
                  )}
                  {alert.crosses_jurisdiction_boundary && (
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'var(--font-body)' }}>
                      Crosses jurisdiction boundary — cross-command escalation.
                    </div>
                  )}

                  {/* Meta row */}
                  <div
                    style={{
                      display: 'flex', alignItems: 'center', gap: '1rem',
                      paddingTop: '0.625rem',
                      borderTop: '1px solid var(--border-color)',
                      flexWrap: 'wrap',
                    }}
                  >
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'var(--font-display)', letterSpacing: '0.04em' }}>
                      <MapPin size={11} /> {alert.camera_id || alert.zone_id || 'Unknown'}
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'var(--font-display)', letterSpacing: '0.04em' }}>
                      <Crosshair size={11} /> {formatAge(alert.timestamp || alert.created_at)}
                    </span>

                    {!alert.isMock && (
                      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                        {alert.closed_at ? (
                          <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.65rem', color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
                            <CheckCircle size={11} /> Closed{alert.closed_by ? ` by ${alert.closed_by}` : ''}
                          </span>
                        ) : alert.acknowledged_at ? (
                          <>
                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.65rem', color: 'var(--color-ok)', fontFamily: 'var(--font-display)' }}>
                              <CheckCircle size={11} /> Ack{alert.acknowledged_by ? ` by ${alert.acknowledged_by}` : ''}
                            </span>
                            {canAcknowledge && (
                              <button
                                onClick={() => handleClose(alert.alert_id)}
                                disabled={closingId === alert.alert_id}
                                className="btn btn-outline btn-sm"
                                style={{ opacity: closingId === alert.alert_id ? 0.5 : 1 }}
                              >
                                {closingId === alert.alert_id ? 'Closing…' : 'Close'}
                              </button>
                            )}
                          </>
                        ) : canAcknowledge ? (
                          <button
                            onClick={() => handleAcknowledge(alert.alert_id)}
                            disabled={ackingId === alert.alert_id}
                            className="btn btn-ok btn-sm"
                            style={{ opacity: ackingId === alert.alert_id ? 0.5 : 1 }}
                          >
                            {ackingId === alert.alert_id ? 'Acknowledging…' : 'Acknowledge'}
                          </button>
                        ) : (
                          <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.65rem', color: 'var(--text-dim)', fontFamily: 'var(--font-display)' }} title="AUDITOR role is read-only">
                            <Eye size={11} /> View only
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Map Panel */}
          <div
            className="card"
            style={{ flex: '1 1 0%', minWidth: 0, minHeight: '400px', padding: '0.5rem' }}
          >
            <TacticalMap alerts={realAlerts} />
          </div>
        </div>
      )}
    </div>
  );
}
