import React, { useState, useEffect, useRef } from 'react';
import { Shield, Clock, User, Activity, Globe } from 'lucide-react';
import { authFetch } from '../services/auth';

export default function Audit() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const initialFetchStarted = useRef(false);

  useEffect(() => {
    // React StrictMode runs mount effects twice in development. A duplicate
    // preflight for this protected cross-origin request was cancelled by the
    // embedded Chromium host before either GET began.
    if (initialFetchStarted.current) return;
    initialFetchStarted.current = true;
    const fetchAuditLogs = async () => {
      try {
        const response = await authFetch('/api/audit?limit=100');
        
        if (!response.ok) {
          if (response.status === 403) throw new Error('Insufficient permissions to view audit ledger.');
          throw new Error('Failed to fetch audit logs');
        }
        
        const data = await response.json();
        setLogs(data.logs);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    
    fetchAuditLogs();
  }, []);

  return (
    <div className="flex flex-col h-full overflow-y-auto" style={{ gap: '1rem' }}>
      <div className="section-header">
        <div>
          <div className="section-title">Audit Trail</div>
          <div className="section-sub">System action log · All operator sessions recorded</div>
        </div>
        <div className="badge badge-accent">Append-Only Log</div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden', flex: 1 }}>
        <div className="card-header" style={{ background: 'var(--bg-base)', borderRadius: 0, padding: '0.625rem 0.875rem' }}>
          <div style={{ display: 'flex', gap: '2rem', fontSize: '0.55rem', fontFamily: 'var(--font-display)', fontWeight: 700, letterSpacing: '0.12em', color: 'var(--text-dim)', textTransform: 'uppercase' }}>
            <div style={{ width: '25%', display: 'flex', alignItems: 'center', gap: '0.375rem' }}><Clock size={11} />Timestamp</div>
            <div style={{ width: '15%', display: 'flex', alignItems: 'center', gap: '0.375rem' }}><User size={11} />Operator</div>
            <div style={{ width: '25%', display: 'flex', alignItems: 'center', gap: '0.375rem' }}><Activity size={11} />Action</div>
            <div style={{ width: '15%', display: 'flex', alignItems: 'center', gap: '0.375rem' }}><Globe size={11} />IP Address</div>
            <div style={{ flex: 1 }}>Status</div>
          </div>
        </div>

        <div className="flex flex-col overflow-y-auto" style={{ maxHeight: '70vh' }}>
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
            logs.map(log => (
              <div
                key={log.id}
                style={{
                  display: 'flex', alignItems: 'flex-start', gap: '0',
                  padding: '0.5rem 0.875rem',
                  borderBottom: '1px solid rgba(30,48,80,0.5)',
                  fontSize: '0.72rem', fontFamily: 'var(--font-mono)',
                  transition: 'background 0.1s ease',
                }}
                className="hover-bg-elevated"
              >
                <div style={{ width: '25%', color: 'var(--text-muted)', paddingRight: '0.5rem' }}>{new Date(log.timestamp).toLocaleString()}</div>
                <div style={{ width: '15%', color: 'var(--text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: '0.5rem' }} title={log.user_id}>
                  {log.user_id ? log.user_id.substring(0, 8) + '…' : 'SYSTEM'}
                </div>
                <div style={{ width: '25%', paddingRight: '0.5rem' }}>
                  <span style={{ color: 'var(--text-main)', fontWeight: 600 }}>{log.action}</span>
                  {log.resource_id && <div style={{ fontSize: '0.6rem', color: 'var(--text-dim)', marginTop: '0.1rem' }}>res: {log.resource_id.substring(0,8)}…</div>}
                </div>
                <div style={{ width: '15%', color: 'var(--text-muted)', paddingRight: '0.5rem' }}>{log.ip_address || 'unknown'}</div>
                <div style={{ flex: 1 }}>
                  <span className={`badge ${log.success ? 'badge-ok' : 'badge-danger'}`}>
                    {log.success ? 'Success' : 'Failed'}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
