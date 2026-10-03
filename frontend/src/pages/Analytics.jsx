/**
 * NETRAKSH — Analytics Page (Phase 2 hardened)
 *
 * All data sourced from real backend aggregation endpoints:
 *   GET /analytics/summary
 *   GET /analytics/timeseries
 *   GET /analytics/by-type
 *   GET /analytics/by-camera
 *   GET /analytics/by-severity
 *
 * No fabricated values. Every displayed number comes from the database.
 * Fields that cannot be derived from the current schema are shown as
 * "Not available" with a brief explanation.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import { Download, Activity, AlertTriangle, Camera, Filter, RefreshCw } from 'lucide-react';
import { authFetch } from '../services/auth';
import { buildAnalyticsCsv } from '../utils/analyticsCsv';

// ─── Time-range presets ───────────────────────────────────────────────────────
const PRESETS = [
  { label: '1 h', hours: 1 },
  { label: '6 h', hours: 6 },
  { label: '24 h', hours: 24 },
  { label: '7 d', hours: 168 },
];

const SEVERITY_COLORS = {
  HIGH: '#ef4444',
  MEDIUM: '#f59e0b',
  LOW: '#64748b',
  CRITICAL: '#dc2626',
  SEVERE: '#f97316',
  ELEVATED: '#eab308',
  NONE: '#475569',
};

const TYPE_COLORS = [
  '#4ade80', '#3b82f6', '#fbbf24', '#ef4444', '#a78bfa', '#f87171', '#34d399',
];

function fmtNum(n) {
  return n == null ? '—' : n.toLocaleString();
}

function fmtPercent(n) {
  return n == null ? '—' : `${Number(n).toFixed(2)}%`;
}

function fmtFractionPercent(n) {
  return n == null ? '—' : `${(Number(n) * 100).toFixed(2)}%`;
}

function fmtRatio(n) {
  return n == null ? '—' : Number(n).toFixed(3);
}

function NotAvailable({ reason }) {
  return (
    <span className="text-xs text-muted italic">
      Not available{reason ? ` — ${reason}` : ''}
    </span>
  );
}

function StatCard({ icon: Icon, label, value, color = 'text-main', notAvailable, naReason, format = fmtNum }) {
  return (
    <div className="stat-card">
      <div className="stat-card-label" style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
        {Icon && <Icon size={12} />}
        {label}
      </div>
      <div className={`stat-card-value ${color || 'text-main'}`}>
        {notAvailable ? <NotAvailable reason={naReason} /> : format(value)}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function Analytics() {
  // Header owns the application-level WebSocket subscription and dispatches
  // the targeted live-event signal consumed below. Analytics keeps no second
  // socket and its aggregate REST responses remain authoritative.

  // Time window state
  const [preset, setPreset] = useState(PRESETS[2]); // default: 24h
  const [customSince, setCustomSince] = useState('');
  const [customUntil, setCustomUntil] = useState('');
  const [useCustom, setUseCustom] = useState(false);
  const [filters, setFilters] = useState({ stream_id: '', camera_id: '', event_type: '' });
  const [options, setOptions] = useState({ streams: [], cameras: [], event_types: [] });
  const liveRefreshTimer = useRef(null);

  // API data state
  const [summary, setSummary] = useState(null);
  const [timeseries, setTimeseries] = useState(null);
  const [byType, setByType] = useState(null);
  const [byCamera, setByCamera] = useState(null);
  const [bySeverity, setBySeverity] = useState(null);
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState(null);
  const inFlightLoad = useRef(null);

  // Build since/until from current selection
  const buildWindow = useCallback(() => {
    if (useCustom && customSince && customUntil) {
      return { since: customSince, until: customUntil };
    }
    // Use the same five-second boundary as the live refresh debounce. This
    // makes React StrictMode's immediate remount compute an identical request
    // key instead of launching a second five-endpoint batch a few milliseconds
    // later.
    const until = new Date(Math.floor(Date.now() / 5000) * 5000);
    const since = new Date(until.getTime() - preset.hours * 3600 * 1000);
    return {
      since: since.toISOString(),
      until: until.toISOString(),
    };
  }, [preset, useCustom, customSince, customUntil]);

  const load = useCallback(async () => {
    const { since, until } = buildWindow();
    const params = new URLSearchParams({ since, until });
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
    const qs = `?${params.toString()}`;

    // React StrictMode intentionally re-runs effects in development. Reuse an
    // identical active request rather than issuing ten aggregate fetches at
    // once and exhausting embedded-browser per-origin connection capacity.
    if (inFlightLoad.current?.key === qs) return inFlightLoad.current.promise;

    setStatus('loading');
    setError(null);

    const request = (async () => {
      let currentPath = 'analytics request';
      try {
        // Read each response body before starting the next request. The
        // aggregate payloads are small, and this avoids a Chromium failure
        // observed when five preflighted requests plus the WebSocket opened
        // simultaneously on first render.
        const payloads = [];
        for (const path of [
          `/analytics/summary${qs}`,
          `/analytics/timeseries${qs}&bucket=hour`,
          `/analytics/by-type${qs}`,
          `/analytics/by-camera${qs}`,
          `/analytics/by-severity${qs}`,
        ]) {
          currentPath = path.split('?')[0];
          let response;
          let lastNetworkError;
          for (let attempt = 0; attempt < 3; attempt += 1) {
            try {
              response = await authFetch(path);
              break;
            } catch (networkError) {
              lastNetworkError = networkError;
              if (attempt < 2) {
                await new Promise(resolve => window.setTimeout(resolve, 150 * (attempt + 1)));
              }
            }
          }
          if (!response) throw lastNetworkError || new Error('request failed');
          if (!response.ok) {
            setStatus('error');
            setError(`Analytics endpoint returned ${response.status}. Check backend logs.`);
            return;
          }
          // Consume each body before opening the next request. Keeping five
          // unread responses alive can exhaust Chromium's per-origin sockets
          // when the dashboard WebSocket is connected.
          payloads.push(await response.json());
        }
        const [s, t, ty, c, sv] = payloads;

        setSummary(s);
        setTimeseries(t);
        setByType(ty);
        setByCamera(c);
        setBySeverity(sv);
        setStatus('ready');
      } catch (err) {
        setStatus('error');
        setError(`Network error loading ${currentPath}: ${err.message}`);
      }
    })();
    inFlightLoad.current = { key: qs, promise: request };
    try {
      return await request;
    } finally {
      if (inFlightLoad.current?.promise === request) inFlightLoad.current = null;
    }
  }, [buildWindow, filters]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    authFetch('/analytics/options')
      .then(response => response.ok ? response.json() : null)
      .then(data => { if (data) setOptions(data); })
      .catch(() => { });
  }, []);

  useEffect(() => {
    const refreshForLiveEvent = () => {
      // Debounce: collapse a burst of live events (Edge emits ~10/sec) into a
      // single refresh at most once every 5 seconds. 250ms was too short —
      // each new event reset the timer before it fired, producing a continuous
      // load() call storm that caused the Analytics page to visually reload.
      window.clearTimeout(liveRefreshTimer.current);
      liveRefreshTimer.current = window.setTimeout(() => load(), 5000);
    };
    window.addEventListener('netraksh-analytics-event', refreshForLiveEvent);
    return () => {
      window.removeEventListener('netraksh-analytics-event', refreshForLiveEvent);
      window.clearTimeout(liveRefreshTimer.current);
    };
  }, [load]);

  // CSV export — uses exactly the fetched data, never static arrays
  const handleExport = () => {
    if (status !== 'ready') return;
    const csv = buildAnalyticsCsv(summary, timeseries, byType, byCamera, bySeverity);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `netraksh_analytics_${new Date().toISOString().slice(0, 19)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // Keep the object URL alive long enough for browsers to begin the download.
    // Immediate revocation can cancel the transfer in embedded Chromium hosts.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const isLoading = status === 'loading';

  // Severity pie data from real API
  const severityPieData = (bySeverity?.by_severity ?? []).map((r, i) => ({
    name: r.severity,
    value: r.count,
    fill: SEVERITY_COLORS[r.severity] || TYPE_COLORS[i % TYPE_COLORS.length],
  }));

  // Type bar data from real API
  const typeBarData = (byType?.by_type ?? []).slice(0, 8);

  // Timeseries bar data from real API
  const tsData = (timeseries?.series ?? []).map(r => ({
    ...r,
    bucket: r.bucket.length > 13 ? r.bucket.slice(11, 16) : r.bucket, // show HH:MM for hour buckets
  }));

  return (
    <div className="flex flex-col h-full overflow-y-auto gap-6">
      {/* Header */}
      <div className="section-header">
        <div>
          <div className="section-title">Command Analytics</div>
          <div className="section-sub">
            Real data from database · {summary ? `${summary.window.since.slice(0, 16)} → ${summary.window.until.slice(0, 16)}` : 'Loading…'}
          </div>
          <div className="section-sub">Metrics below use the selected time window and filters.</div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Time presets */}
          <div style={{ display: 'flex', gap: '0.25rem' }}>
            {PRESETS.map(p => (
              <button
                key={p.label}
                onClick={() => { setUseCustom(false); setPreset(p); }}
                className="btn btn-sm"
                style={{
                  borderColor: (!useCustom && preset.label === p.label) ? 'var(--accent)' : 'var(--border-color)',
                  background: (!useCustom && preset.label === p.label) ? 'var(--accent-dim)' : 'transparent',
                  color: (!useCustom && preset.label === p.label) ? 'var(--accent)' : 'var(--text-muted)',
                  borderStyle: 'solid',
                  borderWidth: '1px',
                }}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Custom range */}
          <div className="flex items-center gap-1">
            <input
              type="datetime-local"
              value={customSince}
              onChange={e => { setCustomSince(e.target.value); setUseCustom(true); }}
              className="input"
              style={{ width: 'auto', fontSize: '0.75rem', padding: '0.3rem 0.5rem' }}
            />
            <span className="text-muted text-xs">→</span>
            <input
              type="datetime-local"
              value={customUntil}
              onChange={e => { setCustomUntil(e.target.value); setUseCustom(true); }}
              className="input"
              style={{ width: 'auto', fontSize: '0.75rem', padding: '0.3rem 0.5rem' }}
            />
          </div>


          <select
            className="input"
            aria-label="Analytics camera filter"
            value={filters.camera_id}
            onChange={e => setFilters(previous => ({ ...previous, camera_id: e.target.value }))}
          >
            <option value="">All cameras</option>
            {options.cameras.map(camera => <option key={camera} value={camera}>{camera}</option>)}
          </select>
          <select
            className="input"
            aria-label="Analytics event type filter"
            value={filters.event_type}
            onChange={e => setFilters(previous => ({ ...previous, event_type: e.target.value }))}
          >
            <option value="">All event types</option>
            {options.event_types.map(type => <option key={type} value={type}>{type}</option>)}
          </select>

          <button onClick={load} disabled={isLoading} className="btn btn-outline btn-sm">
            <RefreshCw size={11} className={isLoading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button onClick={handleExport} disabled={status !== 'ready'} className="btn btn-outline btn-sm" style={{ opacity: status !== 'ready' ? 0.4 : 1 }}>
            <Download size={11} /> Export CSV
          </button>
        </div>
      </div>

      {/* Error state */}
      {status === 'error' && (
        <div className="state-error" style={{ padding: '1rem', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 'var(--radius-lg)', background: 'rgba(239,68,68,0.06)', alignItems: 'flex-start' }}>
          <AlertTriangle size={16} />
          <span>{error || 'Could not load analytics. Check backend connectivity.'}</span>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="state-loading"><span>Loading real analytics data…</span></div>
      )}

      {(status === 'ready' || status === 'loading') && (
        <>
          {/* Summary stat cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '0.75rem' }}>
            <StatCard icon={Activity} label="Total Event Records" value={summary?.events?.raw_total} color="text-ok" />
            <StatCard label="Detected" value={summary?.events?.detected} color="text-ok" />
            <StatCard label="ABSTAIN" value={summary?.events?.abstain} color="text-warning" />
            <StatCard icon={AlertTriangle} label="Total Alerts" value={summary?.alerts?.total} color="text-danger" />
            <StatCard icon={AlertTriangle} label="Unresolved" value={summary?.alerts?.unresolved} color="text-warning" />
            <StatCard icon={AlertTriangle} label="Watchlist Matches" value={summary?.events?.watchlist_matches} color="text-danger" />
            <StatCard label="ANPR Events" value={summary?.events?.anpr} />
            <StatCard label="Intrusions" value={summary?.events?.intrusion} />
            <StatCard label="Vehicle Events" value={summary?.events?.vehicle} />
            <StatCard label="Person Events" value={summary?.events?.person} />
            <StatCard label="Verified Event Packages" value={summary?.events?.verified_packages} color="text-ok" />
            <StatCard label="Detection Rate" value={summary?.events?.detection_rate_pct} color="text-ok" format={fmtPercent} />
            <StatCard label="Average Reliability (Computed Rows)" value={summary?.events?.reliability?.average} format={fmtRatio} />
            <StatCard label="Average Detection Confidence" value={summary?.events?.confidence?.average} format={fmtFractionPercent} />
            <StatCard icon={Camera} label="Cameras With Events" value={summary?.cameras?.with_events} />
            <StatCard
              label="Fleet Uptime"
              notAvailable={summary?.uptime_not_available ?? true}
              naReason="see Performance page"
            />
          </div>

          {/* Alert lifecycle */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem' }}>
            <StatCard label="Acknowledged" value={summary?.alerts?.acknowledged} color="text-ok" />
            <StatCard label="Unresolved" value={summary?.alerts?.unresolved} color="text-warning" />
            <StatCard label="Closed" value={summary?.alerts?.closed} color="text-muted" />
          </div>

          {/* Charts row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.875rem', minHeight: '260px' }}>
            {/* Timeseries */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
              <div className="card-header">
                <span className="card-title">Temporal Detected Incident Frequency</span>
                <span className="badge badge-ok" style={{ fontSize: '0.5rem' }}>Real Data</span>
              </div>
              {tsData.length === 0 ? (
                <div className="flex-1 flex items-center justify-center text-muted text-sm">
                  No events in this window
                </div>
              ) : (
                <div className="flex-1" style={{ minHeight: '200px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={tsData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e3050" />
                      <XAxis dataKey="bucket" stroke="#4d6080" fontSize={10} />
                      <YAxis stroke="#4d6080" fontSize={10} allowDecimals={false} />
                      <Tooltip contentStyle={{ backgroundColor: '#111d30', borderColor: '#1e3050', color: '#e8eef8', fontSize: '0.75rem' }} />
                      <Legend wrapperStyle={{ fontSize: '10px', color: '#5d7a9e' }} />
                      <Bar dataKey="person" name="Person" fill="#4d6080" radius={[2, 2, 0, 0]} stackId="a" />
                      <Bar dataKey="vehicle" name="Vehicle" fill="#00b4d8" radius={[2, 2, 0, 0]} stackId="a" />
                      <Bar dataKey="intrusion" name="Intrusion" fill="#f59e0b" radius={[2, 2, 0, 0]} stackId="a" />
                      <Bar dataKey="watchlist" name="Watchlist" fill="#ef4444" radius={[2, 2, 0, 0]} stackId="a" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Severity pie */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
              <div className="card-header">
                <span className="card-title">Detected Severity Distribution</span>
                <span className="badge badge-ok" style={{ fontSize: '0.5rem' }}>Real Data</span>
              </div>
              {severityPieData.length === 0 ? (
                <div className="flex-1 flex items-center justify-center text-muted text-sm">
                  No events with severity in this window
                </div>
              ) : (
                <div className="flex-1" style={{ minHeight: '200px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={severityPieData}
                        innerRadius={55}
                        outerRadius={80}
                        paddingAngle={4}
                        dataKey="value"
                        stroke="none"
                      >
                        {severityPieData.map((entry, i) => (
                          <Cell key={`cell-${i}`} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={{ backgroundColor: '#111d30', borderColor: '#1e3050', color: '#e8eef8', fontSize: '0.75rem' }} />
                      <Legend verticalAlign="middle" align="right" layout="vertical" wrapperStyle={{ fontSize: '10px', color: '#5d7a9e' }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>

          {/* Event type + camera breakdown */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.875rem', minHeight: '240px' }}>
            {/* By event type */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
              <div className="card-header">
                <span className="card-title">Detected Events By Type</span>
                <span className="badge badge-ok" style={{ fontSize: '0.5rem' }}>Real Data</span>
              </div>
              {typeBarData.length === 0 ? (
                <div className="flex-1 flex items-center justify-center text-muted text-sm">No events</div>
              ) : (
                <div className="flex-1" style={{ minHeight: '180px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={typeBarData} layout="vertical" margin={{ top: 0, right: 20, left: 60, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e3050" />
                      <XAxis type="number" stroke="#4d6080" fontSize={10} allowDecimals={false} />
                      <YAxis type="category" dataKey="event_type" stroke="#4d6080" fontSize={9} width={58} />
                      <Tooltip contentStyle={{ backgroundColor: '#111d30', borderColor: '#1e3050', color: '#e8eef8', fontSize: '0.75rem' }} />
                      <Bar dataKey="count" name="Events" radius={[0, 2, 2, 0]}>
                        {typeBarData.map((_, i) => (
                          <Cell key={i} fill={TYPE_COLORS[i % TYPE_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* By camera */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
              <div className="card-header">
                <span className="card-title">Detected Events By Camera</span>
                <span className="badge badge-ok" style={{ fontSize: '0.5rem' }}>Real Data</span>
              </div>
              {(byCamera?.by_camera ?? []).length === 0 ? (
                <div className="flex-1 flex items-center justify-center text-muted text-sm">No events</div>
              ) : (
                <div className="flex flex-col gap-2 overflow-y-auto">
                  {(byCamera?.by_camera ?? []).map((row, i) => (
                    <div key={row.camera_id} className="flex items-center justify-between text-sm border-b border-color pb-2">
                      <span className="text-muted font-mono text-xs truncate max-w-[180px]" title={row.camera_name}>
                        {row.camera_name}
                      </span>
                      <span className="text-main font-bold text-sm">{fmtNum(row.count)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
