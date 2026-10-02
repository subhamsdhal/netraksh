import { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, Database, HardDrive, Radio, Server } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import useStartupReadiness from '../hooks/useStartupReadiness';
import { WS_URL, authFetch } from '../services/auth';
import { deriveCameraOperationalState } from '../utils/systemTruth';

const tone = (status) => ['READY', 'LIVE', 'CURRENT', 'CONFIGURED'].includes(status)
  ? 'var(--color-ok)'
  : ['IDLE', 'NOT CONFIGURED', 'NONE'].includes(status)
    ? 'var(--text-muted)'
    : ['WARMING', 'DEGRADED', 'BUFFERING', 'STALE'].includes(status)
      ? 'var(--color-warning)'
      : 'var(--color-danger)';

const HEALTH_FRESHNESS_MS = 30_000;

function formatFps(value) {
  const fps = Number(value);
  return Number.isFinite(fps) ? fps.toFixed(2) : null;
}

function formatSampleAge(ageMs) {
  const seconds = Math.floor(Math.max(0, ageMs) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function cameraHealthPresentation(camera, now = Date.now()) {
  const hasSample = [camera.health_state, camera.health_reason, camera.fps_actual, camera.last_health_check]
    .some((value) => value !== null && value !== undefined && value !== '');
  if (!hasSample) {
    return { health: 'NOT REPORTED', fps: 'N/A', reason: 'N/A', sample: 'Never', stale: false };
  }

  const measuredAt = Date.parse(camera.last_health_check);
  const validTimestamp = Number.isFinite(measuredAt);
  const ageMs = validTimestamp ? Math.max(0, now - measuredAt) : null;
  const current = validTimestamp && ageMs <= HEALTH_FRESHNESS_MS;
  const measuredHealth = camera.health_state || 'NOT REPORTED';
  const measuredFps = formatFps(camera.fps_actual);
  const measuredReason = camera.health_reason || 'N/A';

  if (current) {
    return {
      health: measuredHealth,
      fps: measuredFps ?? 'N/A',
      reason: measuredReason,
      sample: formatSampleAge(ageMs),
      stale: false,
    };
  }

  const absoluteTimestamp = validTimestamp
    ? `${new Date(measuredAt).toISOString().replace('T', ' ').replace('.000Z', ' UTC').replace('Z', ' UTC')}`
    : 'Invalid timestamp';
  return {
    health: `STALE · LAST MEASURED ${measuredHealth}`,
    fps: 'N/A CURRENT',
    fpsDetail: measuredFps ? `Last measured: ${measuredFps} FPS` : 'Last measured: N/A',
    reason: `Last measured: ${measuredReason}`,
    sample: validTimestamp ? `${formatSampleAge(ageMs)} · ${absoluteTimestamp}` : `${absoluteTimestamp} · STALE`,
    stale: true,
  };
}

function StatusCard({ label, value, detail, Icon = Activity }) {
  return <div className="card" style={{ minHeight: 104 }}>
    <div className="flex items-center gap-2 text-muted"><Icon size={14} /><span className="text-xs uppercase tracking-widest">{label}</span></div>
    <div style={{ marginTop: 12, color: tone(value), fontFamily: 'var(--font-display)', fontWeight: 700 }}>{value}</div>
    {detail && <div className="text-xs text-dim" style={{ marginTop: 6 }}>{detail}</div>}
  </div>;
}

export default function Health() {
  const { health, isConnected, liveTracks } = useWebSocket(WS_URL, { fetchInitial: false });
  const startup = useStartupReadiness();
  const [data, setData] = useState({ cameras: [], ready: null, capabilities: null, sync: null });
  const [loadState, setLoadState] = useState('loading');

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const paths = ['/cameras', '/ready', '/system/status', '/system/capabilities', '/sync/status'];
        const responses = await Promise.all(paths.map((path) => authFetch(path)));
        if (!responses.every((response) => response.ok)) throw new Error('health request failed');
        const [cameras, ready, status, capabilities, sync] = await Promise.all(responses.map((response) => response.json()));
        if (mounted) { setData({ cameras, ready, status, capabilities, sync }); setLoadState('ready'); }
      } catch { if (mounted) setLoadState('error'); }
    };
    load();
    const timer = setInterval(load, 10_000);
    return () => { mounted = false; clearInterval(timer); };
  }, []);

  const cameras = useMemo(() => (Array.isArray(data.cameras) ? data.cameras : []).map((camera) => ({
    ...camera,
    ...(health[camera.camera_id] || {}),
  })), [data.cameras, health]);
  const cameraNode = (cameraId) => cameraId === 'cam-border-01' ? startup.camBorder01 : cameraId === 'cam-checkpoint-01' ? startup.camCheckpoint01 : null;
  const storage = data.capabilities?.evidence;
  const sync = data.sync;
  const syncState = !isConnected ? 'OFFLINE' : sync?.failed > 0 ? 'FAILED' : sync?.queued > 0 ? 'BUFFERING' : sync?.has_activity ? 'CURRENT' : 'IDLE';

  return <div className="h-full overflow-y-auto" style={{ paddingBottom: 24 }}>
    <div className="section-header">
      <div><div className="section-title">System Health</div><div className="section-sub">Authoritative component readiness, analysis state, and persistence limits</div></div>
      <div className="badge badge-outline">{loadState === 'ready' ? 'LIVE CONFIGURATION' : loadState.toUpperCase()}</div>
    </div>
    {loadState === 'error' && <div className="state-error"><AlertTriangle size={20} />Health data could not be loaded.</div>}
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" style={{ marginTop: 16 }}>
      <StatusCard label="Frontend" value="READY" detail="This interface is running" />
      <StatusCard label="Backend" value={data.ready?.status === 'ready' ? 'READY' : 'DEGRADED'} detail="Readiness endpoint" Icon={Server} />
      <StatusCard label="Database" value={data.ready?.database === 'connected' ? 'READY' : 'OFFLINE'} detail={data.ready?.database || 'Not reported'} Icon={Database} />
      <StatusCard label="WebSocket" value={isConnected ? 'READY' : 'OFFLINE'} detail="Realtime control plane" Icon={Radio} />
      <StatusCard label="Evidence storage" value={!storage ? 'NOT REPORTED' : storage.durable_storage ? 'CONFIGURED' : 'NOT CONFIGURED'} detail={!storage ? 'Runtime configuration unavailable' : storage.durable_storage ? storage.storage_provider : 'Local ephemeral storage is not durable'} Icon={HardDrive} />
      <StatusCard label="Blockchain" value={!data.capabilities?.blockchain ? 'NOT REPORTED' : data.capabilities.blockchain.simulated ? 'DEGRADED' : 'READY'} detail={data.capabilities?.blockchain?.simulated ? 'SIMULATED / MOCK MODE' : data.capabilities?.blockchain?.mode || 'Not reported'} />
      <StatusCard label="Sync queue" value={syncState} detail={`queued ${sync?.queued ?? 0} · failed ${sync?.failed ?? 0}`} />
      <StatusCard label="Chain verification" value="IDLE" detail="Verification is run on demand; no validity is implied here" />
    </div>
    <div className="section-header" style={{ marginTop: 24 }}><div><div className="section-title">Camera and edge state</div><div className="section-sub">Worker process, analysis, telemetry, and camera measurements are independent</div></div></div>
    <div className="card overflow-x-auto" style={{ marginTop: 12 }}>
      <table className="data-table w-full"><thead><tr><th>Camera</th><th>Location</th><th>Edge node</th><th>Analysis</th><th>Telemetry</th><th>Camera health</th><th>FPS measured</th><th>Reason</th><th>Last health sample</th></tr></thead>
        <tbody>
          {cameras.length === 0 && <tr><td colSpan="9" className="text-center text-muted">No registered cameras.</td></tr>}
          {cameras.map((camera) => {
            const operational = deriveCameraOperationalState({ nodeStatus: cameraNode(camera.camera_id)?.status, sourceState: null, telemetry: liveTracks[camera.camera_id] });
            const cameraHealth = cameraHealthPresentation(camera);
            return <tr key={camera.camera_id}>
              <td>{camera.name || camera.camera_id}<div className="text-xs text-dim">{camera.camera_id}</div></td>
              <td>{camera.location || 'Location not registered'}</td>
              <td style={{ color: tone(operational.node) }}>{operational.node}</td><td style={{ color: tone(operational.analysis) }}>{operational.analysis}</td><td style={{ color: tone(operational.telemetry) }}>{operational.telemetry}</td>
              <td style={{ color: tone(cameraHealth.stale ? 'STALE' : cameraHealth.health) }}>{cameraHealth.health}</td>
              <td>{cameraHealth.fps}{cameraHealth.fpsDetail && <div className="text-xs text-dim">{cameraHealth.fpsDetail}</div>}</td>
              <td>{cameraHealth.reason}</td><td>{cameraHealth.sample}</td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>
  </div>;
}
