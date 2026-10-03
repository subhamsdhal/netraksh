import React, { useState, useEffect } from 'react';
import { Shield, Clock, User, Activity, Globe } from 'lucide-react';
import { authFetch } from '../services/auth';

export const AUDIT_COLUMNS = 'minmax(180px, 1.35fr) minmax(150px, 1fr) minmax(260px, 1.8fr) minmax(150px, 1fr) minmax(90px, 0.65fr)';
export const AUDIT_PAGE_SIZE = 25;

export function formatAuditTimestampUtc(timestamp) {
  if (!timestamp) return 'UNKNOWN';
  const unambiguous = /(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp) ? timestamp : `${timestamp}Z`;
  const value = new Date(unambiguous);
  if (Number.isNaN(value.getTime())) return 'UNKNOWN';
  return value.toLocaleString('en-GB', {
    timeZone: 'UTC',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function operatorIdentity(log) {
  if (log.actor_type === 'USER') {
    return {
      primary: log.username || 'UNKNOWN USER',
      secondary: log.user_id ? `id: ${log.user_id.slice(0, 8)}…` : null,
      title: log.user_id ? `${log.username || 'Unknown user'} · User ID: ${log.user_id}` : log.username,
    };
  }
  if (log.actor_type === 'UNAUTHENTICATED' || log.action === 'LOGIN_FAILED') {
    return {
      primary: 'UNAUTHENTICATED',
      secondary: log.attempted_username ? `attempt: ${log.attempted_username}` : null,
      title: log.attempted_username ? `Unauthenticated login attempt: ${log.attempted_username}` : 'Unauthenticated request',
    };
  }
  return { primary: 'SYSTEM', secondary: null, title: 'System-generated action' };
}

export default function Audit() {
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [hasOlder, setHasOlder] = useState(false);
  const [hasNewer, setHasNewer] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const fetchAuditLogs = async () => {
      setLoading(true);
      setError(null);
      try {
        const skip = page * AUDIT_PAGE_SIZE;
        const response = await authFetch(`/api/audit?skip=${skip}&limit=${AUDIT_PAGE_SIZE}`);
        
        if (!response.ok) {
          if (response.status === 403) throw new Error('Insufficient permissions to view audit ledger.');
          throw new Error('Failed to fetch audit logs');
        }
        
        const data = await response.json();
        if (cancelled) return;
        setLogs(data.logs);
        setTotal(data.total);
        setHasOlder(data.has_older ?? skip + data.logs.length < data.total);
        setHasNewer(data.has_newer ?? skip > 0);
      } catch (err) {
        if (cancelled) return;
        setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    
    fetchAuditLogs();
    return () => { cancelled = true; };
  }, [page]);

  const firstShown = total === 0 ? 0 : page * AUDIT_PAGE_SIZE + 1;
  const lastShown = Math.min(page * AUDIT_PAGE_SIZE + logs.length, total);

  return (
    <div className="flex flex-col h-full overflow-y-auto" style={{ gap: '1rem' }}>
      <div className="section-header">
        <div>
          <div className="section-title">Audit Trail</div>
          <div className="section-sub">System action log · Recorded operator and system activity</div>
        </div>
        <div className="badge badge-accent">Audit Log</div>
      </div>

      <div className="card" style={{ padding: 0, overflowX: 'auto', flex: 1 }}>
        <div style={{ minWidth: '860px' }}>
          <div className="flex flex-col overflow-y-auto" style={{ '--audit-columns': AUDIT_COLUMNS, maxHeight: '70vh' }}>
          <div
            data-testid="audit-header"
            className="card-header"
            style={{
              display: 'grid', gridTemplateColumns: 'var(--audit-columns)', gap: '1rem',
              background: 'var(--bg-base)', borderRadius: 0, padding: '0.625rem 0.875rem',
              fontSize: '0.55rem', fontFamily: 'var(--font-display)', fontWeight: 700,
              letterSpacing: '0.12em', color: 'var(--text-dim)', textTransform: 'uppercase',
              position: 'sticky', top: 0, zIndex: 1,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}><Clock size={11} />Timestamp (UTC)</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}><User size={11} />Operator</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}><Activity size={11} />Action</div>
            <div title="Network peer observed by the backend" style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}><Globe size={11} />Request Peer IP</div>
            <div>Status</div>
          </div>

          {loading ? (
            <div className="state-loading"><span>Loading audit trail…</span></div>
          ) : error ? (
            <div className="state-error" style={{ gap: '0.5rem' }}>
              <Shield size={18} />
              <span>{error}</span>
            </div>
          ) : logs.length === 0 ? (
            <div className="state-empty">
              <div className="state-empty-icon"><Shield size={28} /></div>
              <div className="state-empty-title">No Audit Records</div>
              <div className="state-empty-sub">No audit log entries found for this system.</div>
            </div>
          ) : (
            logs.map(log => {
              const operator = operatorIdentity(log);
              const resourceTitle = log.resource_id
                ? `${log.resource_type || 'Resource'}: ${log.resource_id}`
                : undefined;
              return (
                <div
                  key={log.id}
                  data-testid="audit-row"
                  style={{
                    display: 'grid', gridTemplateColumns: 'var(--audit-columns)', gap: '1rem',
                    alignItems: 'start', padding: '0.5rem 0.875rem',
                    borderBottom: '1px solid rgba(30,48,80,0.5)',
                    fontSize: '0.72rem', fontFamily: 'var(--font-mono)',
                    transition: 'background 0.1s ease',
                  }}
                  className="hover-bg-elevated"
                >
                  <div style={{ color: 'var(--text-muted)' }}>{formatAuditTimestampUtc(log.timestamp)}</div>
                  <div style={{ minWidth: 0 }} title={operator.title}>
                    <div style={{ color: 'var(--text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{operator.primary}</div>
                    {operator.secondary && <div style={{ fontSize: '0.58rem', color: 'var(--text-dim)', marginTop: '0.1rem' }}>{operator.secondary}</div>}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <span style={{ color: 'var(--text-main)', fontWeight: 600, overflowWrap: 'anywhere' }}>{log.action}</span>
                    {log.resource_id && (
                      <div title={resourceTitle} style={{ fontSize: '0.6rem', color: 'var(--text-dim)', marginTop: '0.1rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        res: {log.resource_id.substring(0, 8)}…
                      </div>
                    )}
                  </div>
                  <div title="Network peer observed by the backend" style={{ color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>{log.ip_address || 'unknown'}</div>
                  <div>
                    <span className={`badge ${log.success ? 'badge-ok' : 'badge-danger'}`}>
                      {log.success ? 'Success' : 'Failed'}
                    </span>
                  </div>
                </div>
              );
            })
          )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', padding: '0.625rem 0.875rem', borderTop: '1px solid rgba(30,48,80,0.7)', background: 'var(--bg-base)' }}>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem', fontFamily: 'var(--font-mono)' }}>
              Showing {firstShown}–{lastShown} of {total} audit records
            </span>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button className="btn btn-secondary" disabled={loading || !hasNewer} onClick={() => setPage(value => Math.max(0, value - 1))}>Newer</button>
              <button className="btn btn-secondary" disabled={loading || !hasOlder} onClick={() => setPage(value => value + 1)}>Older</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
