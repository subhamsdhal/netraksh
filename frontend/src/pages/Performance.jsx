import { useState, useEffect, useCallback } from 'react';
import { Cpu, Zap, HardDrive, Gauge, AlertTriangle } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import { WS_URL, authFetch } from '../services/auth';
import { parseUtc } from '../utils/time';

// Real edge performance telemetry (edge/instrumentation/metrics.py's
// perf_counter()-measured latency/FPS/CPU/RSS) previously existed only as
// a local JSON file on the edge device — nothing exposed it anywhere. This
// page reads the real GET /system/metrics this session added, merged with
// live WS pushes for whichever edge device is currently reporting.
const FRAME_STAGE_LABELS = {
  health_condition_ms: 'Health + Condition',
  detection_tracking_ms: 'Detection + Tracking',
  event_processing_ms: 'Event Processing',
  total_frame_ms: 'Total Frame',
};
const EVENT_STAGE_LABELS = {
  snapshot_ms: 'Snapshot',
  hash_sign_ms: 'Hash + Sign',
  chain_store_ms: 'Chain Store',
  enqueue_ms: 'Enqueue',
  total_event_ms: 'Total (Decision → Enqueue)',
};

// Edges report metrics every 10 seconds.  Three missed reports means the
// newest snapshot is historical, not a current live observation.
const METRICS_STALE_AFTER_SECONDS = 30;

function formatUptime(seconds) {
  if (seconds == null) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0 ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`;
}

function formatMetric(value, suffix = '') {
  return Number.isFinite(value) ? `${value.toFixed(1)}${suffix}` : '—';
}

function formatCounter(value) {
  return Number.isInteger(value) && value >= 0 ? value.toLocaleString() : '—';
}

export default function Performance() {
  const { metrics: wsMetrics } = useWebSocket(WS_URL);
  const [restMetrics, setRestMetrics] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | auth-required | error
  const [nowMs, setNowMs] = useState(Date.now());

  const loadMetrics = useCallback(async () => {
    setStatus('loading');
    try {
      const res = await authFetch('/system/metrics');
      if (res.status === 403) {
        setStatus('access-denied');
        return;
      }
      if (!res.ok) {
        setStatus('error');
        return;
      }
      setRestMetrics(await res.json());
      setStatus('ready');
    } catch (_e) {
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    loadMetrics();
    const refresh = window.setInterval(loadMetrics, 10_000);
    return () => window.clearInterval(refresh);
  }, [loadMetrics]);

  useEffect(() => {
    const clock = window.setInterval(() => setNowMs(Date.now()), 5_000);
    return () => window.clearInterval(clock);
  }, []);

  // Merge: REST gives every device's latest snapshot as of page load; WS
  // pushes update whichever device reports again while the page is open.
  const merged = { ...Object.fromEntries(restMetrics.map((m) => [m.edge_device_id, m])), ...wsMetrics };
  const devices = Object.values(merged).sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));

  const StatTile = ({ icon: Icon, label, value, sub }) => (
    <div className="card" style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
      <div className="flex items-center gap-2 text-muted font-display uppercase tracking-widest" style={{ fontSize: '0.65rem' }}>
        <Icon size={14} /> {label}
      </div>
      <span className="text-2xl font-display text-main">{value}</span>
      {sub && <span className="text-muted" style={{ fontSize: '0.65rem' }}>{sub}</span>}
    </div>
  );

  const StageRow = ({ label, stats }) => (
    <div className="flex items-center justify-between text-sm font-body py-1.5 border-b border-color last:border-b-0">
      <span className="text-muted">{label}</span>
      <div className="flex gap-4 text-xs">
        <span>mean <span className="text-main">{formatMetric(stats?.mean_ms, 'ms')}</span></span>
        <span>p95 <span className="text-warning">{formatMetric(stats?.p95_ms, 'ms')}</span></span>
        <span>max <span className="text-danger">{formatMetric(stats?.max_ms, 'ms')}</span></span>
        <span className="text-muted">(n={stats?.count ?? 0})</span>
      </div>
    </div>
  );

  const DeviceCard = ({ m }) => {
    const reportedAt = m.timestamp ? parseUtc(m.timestamp)?.getTime() : NaN;
    const ageSeconds = Number.isFinite(reportedAt) ? Math.max(0, (nowMs - reportedAt) / 1000) : Infinity;
    const fresh = ageSeconds <= METRICS_STALE_AFTER_SECONDS;
    const freshnessLabel = fresh ? 'LIVE' : 'STALE';
    const staleNote = `STALE · last report ${Number.isFinite(ageSeconds) ? `${Math.floor(ageSeconds)}s ago` : 'unknown'}`;

    return (
    <div className="card" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div className="flex justify-between items-start">
        <div className="flex-col">
          <div className="flex items-center gap-2">
            <span className="text-lg font-display text-main uppercase tracking-widest">{m.edge_device_id}</span>
            {/* Explicit prototype disclaimer — no Jetson/GPU/TensorRT hardware */}
            <span className="badge badge-warning">CPU PROTOTYPE — not Jetson/GPU</span>
            <span className={fresh ? 'badge badge-ok' : 'badge badge-danger'}>{freshnessLabel}</span>
          </div>
          <span className="font-display text-muted uppercase tracking-widest block mt-1" style={{ fontSize: '0.65rem' }}>
            Uptime {formatUptime(m.uptime_seconds)} · Last report {m.timestamp ? parseUtc(m.timestamp).toLocaleTimeString() : '—'}
          </span>
        </div>
        <Gauge size={24} className="text-muted" />
      </div>

      {/* Not `grid-cols-2 md:grid-cols-4` — those breakpoint classes don't
          exist in this project's CSS (see docs/LIMITATIONS.md); auto-fill
          gives real responsive columns with no media query needed. */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '0.75rem' }}>
        <StatTile icon={Zap} label="Measured FPS" value={fresh ? formatMetric(m.fps) : '—'} sub={fresh ? 'rolling window, not declared rate' : staleNote} />
        {/* CPU and RSS gate independently on their own field being non-null,
            not jointly on `psutil_available` — a single end-of-run CPU%
            sample can be uncredible (see docs/PERFORMANCE_REPORT.md: "this
            reading is not credible... do not put 0% CPU in the PPT") while
            the RSS reading from that exact same run is fine to quote. A
            shared gate would have hidden a real, credible RSS number just
            because CPU wasn't trustworthy that run. */}
        <StatTile
          icon={Cpu} label="CPU"
          value={fresh && m.cpu_percent != null ? `${m.cpu_percent.toFixed(1)}%` : '—'}
          sub={fresh ? (m.cpu_percent != null ? undefined : (m.psutil_available ? 'not sampled this run' : 'psutil not installed on edge')) : staleNote}
        />
        <StatTile
          icon={HardDrive} label="Memory (RSS)"
          value={fresh && m.rss_mb != null ? `${m.rss_mb.toFixed(0)} MB` : '—'}
          sub={fresh ? (m.rss_mb != null ? undefined : (m.psutil_available ? 'not sampled this run' : 'psutil not installed on edge')) : staleNote}
        />
        <StatTile icon={AlertTriangle} label="Alerts Generated" value={m.alerts_generated} sub={fresh ? "this process's lifetime" : 'final process count'} />
        <StatTile icon={Gauge} label="Telemetry Produced" value={formatCounter(m.telemetry_produced)} sub={m.telemetry_produced == null ? 'not available for this snapshot' : (fresh ? 'current process counter' : 'final snapshot')} />
        <StatTile icon={AlertTriangle} label="Telemetry Dropped" value={formatCounter(m.telemetry_dropped)} sub={m.telemetry_dropped == null ? 'not available for this snapshot' : (fresh ? 'current process counter' : 'final snapshot')} />
        <StatTile icon={AlertTriangle} label="Telemetry Errors" value={formatCounter(m.telemetry_errors)} sub={m.telemetry_errors == null ? 'not available for this snapshot' : (fresh ? 'current process counter' : 'final snapshot')} />
      </div>

      <div>
        <span className="text-xs font-display text-muted uppercase tracking-widest">Per-Frame Stage Latency {fresh ? '' : '· final measured snapshot'}</span>
        <div className="mt-2">
          {Object.entries(m.frames || {}).map(([stage, stats]) => (
            <StageRow key={stage} label={FRAME_STAGE_LABELS[stage] || stage} stats={stats} />
          ))}
        </div>
      </div>

      {m.events?.total_event_ms?.count > 0 && (
        <div>
          <span className="text-xs font-display text-muted uppercase tracking-widest">Per-Event Stage Latency (evidence path)</span>
          <div className="mt-2">
            {Object.entries(m.events || {}).map(([stage, stats]) => (
              <StageRow key={stage} label={EVENT_STAGE_LABELS[stage] || stage} stats={stats} />
            ))}
          </div>
        </div>
      )}

      {m.adaptive_gate && (
        <div className="flex justify-between items-center text-xs font-display text-muted border-t border-color pt-3">
          <span>Adaptive Compute Gate</span>
          <span className={fresh && m.adaptive_gate.state === 'ACTIVE' ? 'text-ok' : 'text-muted'}>
            {m.adaptive_gate.state} · skipped {(m.adaptive_gate.skip_ratio * 100).toFixed(0)}%
            ({m.adaptive_gate.frames_skipped}/{m.adaptive_gate.frames_run + m.adaptive_gate.frames_skipped} frames)
          </span>
        </div>
      )}
    </div>
    );
  };

  return (
    <div className="h-full flex flex-col gap-4 overflow-hidden">
      <div className="section-header flex-shrink-0">
        <div>
          <h2 className="section-title">CPU Prototype Metrics</h2>
          <div className="section-sub">
            Real, locally-measured pipeline latency and resource usage from this CPU-based prototype.
            No GPU, TensorRT, or Jetson hardware — all numbers are from <code>perf_counter()</code> calls
            in the running Python process on this machine.
            Not simulated, not declared/configured values.
          </div>
        </div>
      </div>

      {status === 'access-denied' && (
        <div className="max-w-xs bg-panel border border-danger rounded p-4 text-center">
          <h3 className="text-danger font-display tracking-widest uppercase">Access Denied</h3>
          <p className="text-muted text-sm mt-2">You do not have permission to access this module.</p>
        </div>
      )}

      {status === 'loading' && <div className="text-muted text-sm text-center mt-8">Loading real metrics…</div>}
      {status === 'error' && <div className="text-danger text-sm text-center mt-8">Could not reach the backend.</div>}

      {status === 'ready' && (
        devices.length === 0 ? (
          <div className="text-muted text-sm text-center mt-8">
            No edge device has reported performance metrics yet. This page fills in automatically once
            edge/main.py's EdgePipeline is running against a real camera feed.
          </div>
        ) : (
          <div className="flex flex-col gap-6 overflow-y-auto pr-2">
            {devices.map((m) => <DeviceCard key={m.edge_device_id} m={m} />)}
          </div>
        )
      )}
    </div>
  );
}
