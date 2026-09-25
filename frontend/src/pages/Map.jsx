import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { WS_URL } from '../services/auth';
import useWebSocket from '../hooks/useWebSocket';
import { Camera, MapPin, X } from 'lucide-react';
import { parseUtc } from '../utils/time';

const FRESH_SECONDS = 30;
const STATUS_COLORS = {
  PROCESSING: '#4ade80', COMPLETED: '#60a5fa', OK: '#4ade80',
  DEGRADED: '#fbbf24', FAILED: '#f87171', STALE: '#94a3b8', UNKNOWN: '#64748b',
};

function markerIcon(color, pulsing) {
  return L.divIcon({
    className: '',
    html: `<div style="position:relative;width:24px;height:24px;">
      ${pulsing ? `<div style="position:absolute;inset:-8px;border-radius:50%;background:${color};opacity:.35;animation:netraksh-pulse 1.5s ease-out infinite"></div>` : ''}
      <div style="position:absolute;inset:0;border-radius:50%;background:${color};border:2px solid #0f172a;box-shadow:0 0 10px ${color};display:flex;align-items:center;justify-content:center">
        <div style="width:8px;height:8px;background:white;border-radius:50%"></div>
      </div>
      <style>@keyframes netraksh-pulse{0%{transform:scale(.6);opacity:.6}100%{transform:scale(2.5);opacity:0}}</style>
    </div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

const eventId = event => event?.event_id || event?.id || null;

export default function MapView() {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const cameraMarkersRef = useRef({});
  const [selectedCameraId, setSelectedCameraId] = useState(null);
  const [now, setNow] = useState(Date.now());
  const { health, liveTracks, events, cameras: registeredCameras } = useWebSocket(WS_URL);
  const cameras = useMemo(
    () => registeredCameras.filter(camera => camera.latitude != null && camera.longitude != null),
    [registeredCameras],
  );

  useEffect(() => {
    const clock = window.setInterval(() => setNow(Date.now()), 5_000);
    return () => window.clearInterval(clock);
  }, []);

  const mappedCameras = useMemo(() => cameras.map(camera => {
    const cameraId = camera.camera_id;
    const telemetry = liveTracks[cameraId];
    const healthUpdate = health[cameraId];
    const telemetryFresh = Number.isFinite(telemetry?.timestamp) && now - telemetry.timestamp <= FRESH_SECONDS * 1000;
    const healthTimestamp = healthUpdate?.last_health_check || camera.last_health_check;
    const healthMs = healthTimestamp ? parseUtc(healthTimestamp)?.getTime() : NaN;
    const healthFresh = Number.isFinite(healthMs) && now - healthMs <= FRESH_SECONDS * 1000;
    let status = 'UNKNOWN';
    if (telemetryFresh) status = telemetry.analysis_state || 'PROCESSING';
    else if (healthFresh) status = healthUpdate?.health_state || camera.health_state || 'UNKNOWN';
    else if (healthTimestamp || telemetry?.timestamp) status = 'STALE';
    return { ...camera, cameraId, telemetry, healthTimestamp, status };
  }), [cameras, health, liveTracks, now]);

  const selectedCamera = mappedCameras.find(camera => camera.cameraId === selectedCameraId) || null;
  const selectedEvents = selectedCamera ? events.filter(event => event.camera_id === selectedCamera.cameraId) : [];
  const latestEvent = selectedEvents[0] || null;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: false }).setView([20.5937, 78.9629], 4.5);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    // Removed CartoDB tile layer to avoid any API KEY REQUIRED overlays or dependency on external providers.
    // The static map SVG background will serve as the visualization layer.
    mapRef.current = map;
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(containerRef.current);
    const initialResize = window.setTimeout(() => map.invalidateSize(), 100);
    return () => {
      window.clearTimeout(initialResize);
      observer.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const currentIds = new Set(mappedCameras.map(camera => camera.cameraId));
    Object.entries(cameraMarkersRef.current).forEach(([id, marker]) => {
      if (!currentIds.has(id)) {
        map.removeLayer(marker);
        delete cameraMarkersRef.current[id];
      }
    });
    mappedCameras.forEach(camera => {
      const hasCriticalEvent = events.some(event => event.camera_id === camera.cameraId && ['CRITICAL', 'SEVERE'].includes(event.severity));
      const color = STATUS_COLORS[camera.status] || STATUS_COLORS.UNKNOWN;
      let marker = cameraMarkersRef.current[camera.cameraId];
      if (!marker) {
        marker = L.marker([camera.latitude, camera.longitude]).addTo(map);
        marker.on('click', () => setSelectedCameraId(camera.cameraId));
        cameraMarkersRef.current[camera.cameraId] = marker;
      }
      marker.setLatLng([camera.latitude, camera.longitude]);
      marker.setIcon(markerIcon(color, hasCriticalEvent));
    });
    if (mappedCameras.length > 0) {
      const bounds = L.latLngBounds(mappedCameras.map(camera => [camera.latitude, camera.longitude]));
      map.fitBounds(bounds.pad(0.5), { maxZoom: 15 });
    }
  }, [mappedCameras, events]);

  return (
    <div className="h-full flex flex-col gap-4">
      <div className="section-header">
        <div>
          <h2 className="section-title">Geospatial Command Map</h2>
          <div className="section-sub">Registered camera/site coordinates and real runtime status</div>
        </div>
        <div className="flex gap-2 text-xs text-muted">
          <span>● <span className="text-ok">Processing/OK</span></span>
          <span>● <span className="text-warning">Degraded</span></span>
          <span>● <span className="text-muted">Stale/Unknown</span></span>
        </div>
      </div>

      <div className="relative flex-grow rounded border border-color overflow-hidden bg-panel">
        <div className="absolute inset-0 z-[0] opacity-40" style={{
            backgroundImage: `url('/assets/images/india_map_bg.svg')`,
            backgroundSize: 'cover',
            backgroundPosition: 'center'
        }} />
        <div ref={containerRef} className="w-full h-full z-10 relative" style={{ background: 'transparent' }} />
        {mappedCameras.length === 0 && <div className="absolute inset-0 z-[5] flex items-center justify-center bg-panel/90 text-muted text-sm text-center px-4">NO GEOLOCATION CONFIGURED<br />Register real camera coordinates to enable map markers.</div>}

        {selectedCamera && (
          <div className="card absolute top-4 left-4 w-96 z-10" style={{ maxHeight: 'calc(100% - 32px)', boxShadow: '0 10px 40px -10px rgba(0,0,0,.8)' }}>
            <div className="card-header border-b border-color" style={{ paddingBottom: '.75rem' }}>
              <div className="flex items-center gap-2"><Camera size={14} /><span className="card-title">Camera Site Details</span></div>
              <button onClick={() => setSelectedCameraId(null)} className="text-muted"><X size={16} /></button>
            </div>
            <div className="p-4 overflow-y-auto flex flex-col gap-3 text-sm">
              <div><span className="text-main font-bold">{selectedCamera.name}</span><div className="text-muted text-xs">{selectedCamera.cameraId}</div></div>
              <div className="text-muted flex items-center gap-1"><MapPin size={12} />{selectedCamera.location || 'N/A'}</div>
              <div className="text-xs text-muted">Registered camera/site coordinate — not an exact event or subject position.</div>
              <div className="grid grid-cols-2 gap-2">
                <div className="card p-2"><div className="text-muted text-xs">STATUS</div><div className="text-main">{selectedCamera.status}</div></div>
                <div className="card p-2"><div className="text-muted text-xs">LAST HEALTH</div><div className="text-main">{selectedCamera.healthTimestamp ? parseUtc(selectedCamera.healthTimestamp).toLocaleString() : 'N/A'}</div></div>
                <div className="card p-2"><div className="text-muted text-xs">ACTIVE STREAM</div><div className="text-main font-mono text-xs break-all">{selectedCamera.telemetry?.stream_id || 'N/A'}</div></div>
                <div className="card p-2"><div className="text-muted text-xs">RECENT EVENTS LOADED</div><div className="text-main">{selectedEvents.length}</div></div>
              </div>
              <div className="border-t border-color pt-3">
                <div className="text-muted text-xs mb-2">LATEST EVENT AT THIS CAMERA SITE</div>
                {latestEvent ? (
                  <div className="grid grid-cols-2 gap-1 text-xs">
                    <span className="text-muted">Event ID</span><span className="font-mono break-all">{eventId(latestEvent) || 'N/A'}</span>
                    <span className="text-muted">Type</span><span>{latestEvent.event_type || 'N/A'}</span>
                    <span className="text-muted">Severity</span><span>{latestEvent.severity || 'N/A'}</span>
                    <span className="text-muted">Decision</span><span>{latestEvent.decision_state || 'N/A'}</span>
                    <span className="text-muted">Timestamp</span><span>{latestEvent.timestamp ? parseUtc(latestEvent.timestamp).toLocaleString() : 'N/A'}</span>
                    <span className="text-muted">Video time</span><span>{Number.isFinite(latestEvent.video_time) ? `${latestEvent.video_time.toFixed(2)}s` : 'N/A'}</span>
                    <span className="text-muted">Stream</span><span className="font-mono break-all">{latestEvent.stream_id || 'N/A'}</span>
                  </div>
                ) : <div className="text-muted text-xs">No recent event is loaded for this camera.</div>}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
