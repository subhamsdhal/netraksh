import { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { authFetch } from '../services/auth';

// Real geospatial map — replaces what used to be a fully decorative <div>
// (a static background image with 3 hardcoded pixel-position pins named
// "SECTOR 7"/"HQ"/"NODE C", tied to nothing real). No camera anywhere in
// this project had real coordinates before this component existed
// (backend/models/orm.py's Camera gained latitude/longitude specifically
// for this). Plots real registered camera positions and colors each
// marker by that camera's real latest health_state; alerts passed in are
// matched to their real camera_id to add a pulsing ring, not a separate
// invented pin.
//
// Uses vanilla Leaflet directly rather than react-leaflet: this project is
// on React 19, which react-leaflet does not yet reliably support, and a
// small imperative useEffect is simpler than fighting that version gap.
// Markers are inline SVG L.divIcon, not Leaflet's default pin image — the
// default image path breaks under Vite's bundling unless patched, and an
// inline SVG sidesteps that entirely while letting the color reflect real
// health state.
const HEALTH_COLORS = {
  OK: '#4ade80',
  DEGRADED: '#fbbf24',
  FAILED: '#f87171',
  UNKNOWN: '#64748b',
};

function markerIcon(color, pulsing) {
  return L.divIcon({
    className: '',
    html: `
      <div style="position:relative;width:16px;height:16px;">
        ${pulsing ? `<div style="position:absolute;inset:-6px;border-radius:50%;background:${color};opacity:0.35;animation:netraksh-pulse 1.5s ease-out infinite;"></div>` : ''}
        <div style="position:absolute;inset:0;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 0 6px ${color};"></div>
      </div>
      <style>
        @keyframes netraksh-pulse { 0% { transform: scale(0.6); opacity: 0.5; } 100% { transform: scale(2.2); opacity: 0; } }
      </style>
    `,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

export default function TacticalMap({ alerts = [] }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const [cameras, setCameras] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | auth-required | error

  useEffect(() => {
    const load = async () => {
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
    };
    load();
  }, []);

  // Init the map once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true, attributionControl: true }).setView([20.5937, 78.9629], 4); // India, default
    
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
      className: 'netraksh-dark-tiles',
    }).addTo(map);
    mapRef.current = map;

    // Leaflet reads its container's size once, at init — if the flex/grid
    // layout around it (this panel is sized by its flex-parent chain, not
    // a fixed pixel height) hasn't finished settling by then, the map's
    // internal size is wrong and it only renders tiles into a fraction of
    // its real box (confirmed live: a black gap below the rendered tiles
    // at first load). A ResizeObserver on the container re-syncs Leaflet's
    // idea of its own size whenever the real box changes, not just once.
    const resizeObserver = new ResizeObserver(() => map.invalidateSize());
    resizeObserver.observe(containerRef.current);
    // Also fire once shortly after mount, for the very first paint before
    // any resize has occurred to trigger the observer.
    const t = setTimeout(() => map.invalidateSize(), 100);

    return () => {
      clearTimeout(t);
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Re-plot markers whenever real camera/alert data changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    markersRef.current.forEach((m) => map.removeLayer(m));
    markersRef.current = [];

    const withCoords = cameras.filter((c) => c.latitude != null && c.longitude != null);
    const activeAlertCameraIds = new Set(alerts.filter((a) => !a.isMock && !a.acknowledged_at).map((a) => a.camera_id));

    withCoords.forEach((cam) => {
      const color = HEALTH_COLORS[cam.health_state] || HEALTH_COLORS.UNKNOWN;
      const pulsing = activeAlertCameraIds.has(cam.camera_id);
      const marker = L.marker([cam.latitude, cam.longitude], { icon: markerIcon(color, pulsing) }).addTo(map);
      marker.bindPopup(
        `<div style="font-family: sans-serif; font-size: 12px;">
          <strong>${cam.name}</strong><br/>
          ${cam.location}<br/>
          Health: ${cam.health_state || 'no data yet'}
          ${pulsing ? '<br/><span style="color:#f87171;">⚠ active alert</span>' : ''}
        </div>`
      );
      markersRef.current.push(marker);
    });

    if (withCoords.length > 0) {
      const bounds = L.latLngBounds(withCoords.map((c) => [c.latitude, c.longitude]));
      map.fitBounds(bounds.pad(0.5), { maxZoom: 15 });
    }
  }, [cameras, alerts]);

  const withCoordsCount = cameras.filter((c) => c.latitude != null && c.longitude != null).length;

  return (
    <div className="w-full h-full relative rounded overflow-hidden" style={{ border: '1px solid rgba(255,255,255,0.1)' }}>
      <style>
        {`
          .netraksh-dark-tiles {
            filter: brightness(0.6) invert(1) contrast(3) hue-rotate(200deg) saturate(0.3) brightness(0.7);
          }
          .leaflet-popup-content-wrapper {
            background-color: rgba(15,23,42,0.9);
            color: #e2e8f0;
            border: 1px solid rgba(239,68,68,0.3);
            border-radius: 4px;
          }
          .leaflet-popup-tip {
            background-color: rgba(15,23,42,0.9);
          }
        `}
      </style>
      <div ref={containerRef} className="w-full h-full" style={{ background: '#0a0f0d' }} />

      {status === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center text-muted text-sm font-display z-[1000]" style={{ backgroundColor: 'rgba(10,15,13,0.85)' }}>
          Loading real camera positions…
        </div>
      )}
      {status === 'access-denied' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-danger text-sm font-display text-center px-4 z-[1000]" style={{ backgroundColor: 'rgba(15,23,42,0.95)', backdropFilter: 'blur(4px)' }}>
          <span className="tracking-widest uppercase mb-1">Access Denied</span>
          <span className="text-xs text-muted">You do not have permission to view camera telemetry.</span>
        </div>
      )}
      {status === 'error' && (
        <div className="absolute inset-0 flex items-center justify-center text-danger text-xs font-display z-[1000]" style={{ backgroundColor: 'rgba(10,15,13,0.9)' }}>
          Could not reach the backend.
        </div>
      )}
      {status === 'ready' && withCoordsCount === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-muted text-xs font-display text-center px-6 z-[1000] pointer-events-none" style={{ backgroundColor: 'rgba(10,15,13,0.85)' }}>
          No camera has a registered location yet — set one via PUT /cameras/{'{id}'}/location.
        </div>
      )}

      <div className="absolute bottom-2 left-2 text-[10px] font-display text-muted bg-dark border border-color rounded px-2 py-1 z-[1000]">
        {withCoordsCount} camera{withCoordsCount === 1 ? '' : 's'} with real coordinates
      </div>
    </div>
  );
}
