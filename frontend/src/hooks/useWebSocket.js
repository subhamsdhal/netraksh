/**
 * NETRAKSH — useWebSocket hook (Phase 5 hardened)
 *
 * Changes vs Phase 4:
 *   1. Responds to server "ping" messages with a "pong" so the backend
 *      heartbeat doesn't consider the client dead.
 *   2. Exposes `isConnected` state so UI components can show connection status.
 *   3. Fetches initial watchlist data on mount alongside events/alerts/health.
 *   4. Exposes `watchlist` state for the new Watchlist page.
 *   5. Handles new "watchlist_update" push message type for real-time additions.
 *
 * Reconnection strategy (unchanged but documented):
 *   Exponential backoff: 1s, 2s, 4s, 8s... capped at 30s.
 *   Max 10 attempts before giving up (prevents battery drain on mobile).
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { authFetch, getToken, logout } from '../services/auth';
import { shouldAcceptTelemetry } from '../utils/dashboardScope';

export default function useWebSocket(url, { fetchInitial = true } = {}) {
  const [events,   setEvents]   = useState([]);
  const [health,   setHealth]   = useState({});
  const [alerts,   setAlerts]   = useState([]);
  const [metrics,  setMetrics]  = useState({});
  const [liveTracks, setLiveTracks] = useState({});
  const [watchlist, setWatchlist] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState('CONNECTING');
  const [lastMessageAt, setLastMessageAt] = useState(null);
  const [lastTelemetryAt, setLastTelemetryAt] = useState(null);
  const [cameras, setCameras] = useState([]);
  const [correlation, setCorrelation] = useState(null);

  const latestTelemetry = useRef({});
  const telemetryResetAt = useRef(0);
  const telemetryContextRequest = useRef({});
  const eventsContextRequest = useRef({});
  const wsRef        = useRef(null);

  // Start a fresh dashboard video session. This clears sequence cursors and
  // rejects delayed messages from the previous run until their timestamps
  // are newer than the reset point.
  const resetRealtimeState = useCallback(() => {
    telemetryResetAt.current = Date.now();
    // Replacing the maps invalidates every in-flight contextual request while
    // still allowing independent camera requests to run concurrently.
    telemetryContextRequest.current = {};
    eventsContextRequest.current = {};
    latestTelemetry.current = {};
    setEvents([]);
    setLiveTracks({});
    setCorrelation(null);
  }, []);

  // ── Initial REST fetch ────────────────────────────────────────────────────
  const fetchInitialData = useCallback(async () => {
    const safeJson = async (promise) => {
      try {
        const res = await promise;
        return res.ok ? res.json() : null;
      } catch { return null; }
    };

    const [evs, als, cams, wl, metricSnapshots] = await Promise.all([
      safeJson(authFetch('/events?limit=100')),
      safeJson(authFetch('/alerts?limit=100')),
      safeJson(authFetch('/cameras')),
      safeJson(authFetch('/watchlist')),
      safeJson(authFetch('/system/metrics')),
    ]);

    if (Array.isArray(evs))  setEvents(dedupeEvents(evs));
    if (Array.isArray(als))  setAlerts(als);
    if (Array.isArray(wl))   setWatchlist(wl);
    if (Array.isArray(cams)) {
      setCameras(cams);
      const hMap = {};
      cams.forEach(c => {
        hMap[c.camera_id] = { health_state: c.health_state, camera_id: c.camera_id };
      });
      setHealth(hMap);
    }
    if (Array.isArray(metricSnapshots)) {
      setMetrics(Object.fromEntries(metricSnapshots.map(item => [item.edge_device_id, item])));
    }
  }, []);

  const refreshEventsForContext = useCallback(async (cameraId, streamId) => {
    const requestKey = cameraId || '*';
    const requestId = (eventsContextRequest.current[requestKey] || 0) + 1;
    eventsContextRequest.current[requestKey] = requestId;
    const params = new URLSearchParams({ limit: '100' });
    if (cameraId) params.set('camera_id', cameraId);
    if (streamId) params.set('stream_id', streamId);
    try {
      const response = await authFetch(`/events?${params.toString()}`);
      if (!response.ok) return [];
      const contextualEvents = await response.json();
      if (!Array.isArray(contextualEvents)) return [];
      if (requestId !== eventsContextRequest.current[requestKey]) return [];
      setEvents(previous => dedupeEvents([...contextualEvents, ...previous]).slice(0, 100));
      return contextualEvents;
    } catch {
      return [];
    }
  }, []);

  const refreshTelemetryForContext = useCallback(async (cameraId, streamId) => {
    const requestKey = cameraId || '*';
    const requestId = (telemetryContextRequest.current[requestKey] || 0) + 1;
    telemetryContextRequest.current[requestKey] = requestId;
    const params = new URLSearchParams();
    if (cameraId) params.set('camera_id', cameraId);
    if (streamId) params.set('stream_id', streamId);
    try {
      const response = await authFetch(`/system/telemetry/latest?${params.toString()}`);
      if (!response.ok) return [];
      const payload = await response.json();
      // The filtered endpoint returns one snapshot while the unfiltered form
      // may return a list. Normalize both shapes before applying scope checks.
      const snapshots = Array.isArray(payload) ? payload : (payload ? [payload] : []);
      if (requestId !== telemetryContextRequest.current[requestKey]) return [];
      const matchingSnapshots = snapshots.filter(tel => (
        (!cameraId || tel?.camera_id === cameraId)
        && (!streamId || tel?.stream_id === streamId)
      ));
      setLiveTracks(previous => {
        const next = { ...previous };
        if (cameraId && matchingSnapshots.length === 0) delete next[cameraId];
        matchingSnapshots.forEach(tel => {
          if (!tel?.camera_id || !Array.isArray(tel.tracks)) return;
          const state = telemetryToState(tel);
          if (!shouldAcceptTelemetry(latestTelemetry.current[tel.camera_id], state)) return;
          latestTelemetry.current[tel.camera_id] = state;
          next[tel.camera_id] = state;
        });
        return next;
      });
      return matchingSnapshots;
    } catch {
      return [];
    }
  }, []);

  // ── WebSocket connect + message handler ───────────────────────────────────
  useEffect(() => {
    if (fetchInitial) fetchInitialData();

    let isMounted = true;
    let reconnectTimer = null;
    let reconnectAttempts = 0;
    const connect = () => {
      if (!isMounted) return;
      setConnectionStatus(reconnectAttempts === 0 ? 'CONNECTING' : 'RECONNECTING');
      const token = getToken();
      // Keep bearer credentials out of the URL and therefore out of routine
      // proxy/server access logs. Browsers cannot set Authorization on a
      // WebSocket upgrade, so use a negotiated subprotocol token instead.
      const ws = token
        ? new WebSocket(url, ['netraksh.jwt', token])
        : new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMounted) { ws.close(); return; }
        reconnectAttempts = 0;
        setIsConnected(true);
        setConnectionStatus('CONNECTED');
        window.dispatchEvent(new Event('netraksh-ws-connect'));
      };

      ws.onmessage = (event) => {
        if (!isMounted) return;
        setLastMessageAt(Date.now());
        try {
          const data = JSON.parse(event.data);

          switch (data.type) {
            // ── Server keepalive ping → respond with pong ────────────────
            case 'ping':
              ws.send(JSON.stringify({ type: 'pong', timestamp: data.timestamp }));
              break;

            // ── Auth error ────────────────────────────────────────────────
            case 'auth_error':
              console.error('[WS] Auth error:', data.detail);
              logout(); // trigger global redirect to login
              break;

            // ── New detection event ───────────────────────────────────────
            case 'new_event':
              if (data.payload?.timestamp) {
                // Backend datetimes are UTC but legacy SQLite/FastAPI responses
                // may omit the trailing timezone marker. Date.parse() treats an
                // unmarked value as browser-local time, which made fresh events
                // look several hours older than the upload reset on IST clients.
                const eventMs = parseServerTimestamp(data.payload.timestamp);
                if (Number.isFinite(eventMs) && eventMs < telemetryResetAt.current) break;
              }
              setEvents(prev => dedupeEvents([data.payload, ...prev]).slice(0, 100));
              // Analytics listens for this targeted signal and refetches its
              // server-side aggregates. Existing event consumers are unchanged.
              window.dispatchEvent(new CustomEvent('netraksh-analytics-event', { detail: data.payload }));
              break;

            case 'correlation':
              setCorrelation(data.data || null);
              break;

            // ── Camera health change ──────────────────────────────────────
            case 'camera_health':
              setHealth(prev => ({ ...prev, [data.health.camera_id]: data.health }));
              break;

            // ── New alert ─────────────────────────────────────────────────
            case 'new_alert':
              setAlerts(prev => [data.alert, ...prev]);
              break;

            // ── Edge performance metrics ──────────────────────────────────
            case 'pipeline_metrics':
              setMetrics(prev => ({ ...prev, [data.metrics.edge_device_id]: data.metrics }));
              break;

            // ── Live telemetry (batched — arrives at most every 100ms) ────
            case 'live_telemetry': {
              const tel = data.telemetry;
              const cid = tel.camera_id;
              if (!cid || !Array.isArray(tel.tracks)) break;
              if (Number.isFinite(tel.timestamp) && tel.timestamp * 1000 < telemetryResetAt.current) break;
              // Out-of-order / duplicate suppression
              const state = telemetryToState(tel, Date.now());
              if (!shouldAcceptTelemetry(latestTelemetry.current[cid], state)) break;
              latestTelemetry.current[cid] = state;
              setLastTelemetryAt(Date.now());
              setLiveTracks(prev => ({
                ...prev,
                [cid]: state,
              }));
              // Signal edge health to Header.jsx. Edge ONLINE status is only
              // true when real telemetry is arriving — not just WS connected.
              window.dispatchEvent(new CustomEvent('netraksh-edge-telemetry', {
                detail: { camera_id: cid, ts: Date.now() },
              }));
              break;
            }

            // ── Watchlist push update (admin added/updated a subject) ─────
            case 'watchlist_update':
              if (data.action === 'added' && data.person) {
                setWatchlist(prev => [data.person, ...prev]);
              } else if (data.action === 'updated' && data.person) {
                setWatchlist(prev =>
                  prev.map(p => p.person_id === data.person.person_id ? data.person : p)
                );
              } else if (data.action === 'removed' && data.person_id) {
                setWatchlist(prev =>
                  prev.filter(p => p.person_id !== data.person_id)
                );
              }
              break;

            default:
              break;
          }
        } catch (err) {
          console.error('[WS] Parse error:', err);
        }
      };

      ws.onerror = () => {
        // onclose fires after onerror — reconnect logic lives there
      };

      ws.onclose = () => {
        if (!isMounted) return;
        setIsConnected(false);
        setConnectionStatus('RECONNECTING');
        wsRef.current = null;
        window.dispatchEvent(new Event('netraksh-ws-disconnect'));
        // Keep retrying with capped exponential backoff so a backend restart
        // can recover without a manual page refresh.
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30_000);
        reconnectAttempts++;
        reconnectTimer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      isMounted = false;
      clearTimeout(reconnectTimer);
      if (wsRef.current) wsRef.current.close();
    };
  }, [url, fetchInitialData]);

  return {
    events, health, alerts, metrics, liveTracks, watchlist, cameras, correlation,
    isConnected, connectionStatus, lastMessageAt, lastTelemetryAt,
    resetRealtimeState, refreshEventsForContext, refreshTelemetryForContext,
  };
}

function parseServerTimestamp(value) {
  const raw = String(value || '').trim();
  if (!raw) return NaN;
  const timezoneMarked = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  return Date.parse(timezoneMarked ? raw : `${raw}Z`);
}

/**
 * Normalise a telemetry frame to a state object ready for liveTracks.
 *
 * Timestamp normalisation (root-cause fix for STALE-on-REST-restore):
 *   Edge always sends `timestamp` as a Unix epoch float in SECONDS
 *   (e.g. 1758167446.5).  The stale-check in Dashboard computes
 *   `Date.now() - liveTracks[id].timestamp` and expects MILLISECONDS.
 *
 *   WS live path: receivedAt = Date.now()  → always shows LIVE immediately.
 *
 *   REST restore path: receivedAt = null.
 *     1. Convert seconds → ms  (sourceTimestamp = tel.timestamp * 1000).
 *     2. If sourceTimestamp is within TELEMETRY_LIVE_WINDOW_MS of now,
 *        the edge was recently active — use Date.now() so the stale-check
 *        shows LIVE correctly.
 *     3. If older than that window, use the real sourceTimestamp so the
 *        existing stale-check (>5 s → STALE, >30 s → OFFLINE) fires
 *        correctly.  This prevents arbitrarily old REST telemetry from
 *        being displayed as LIVE indefinitely.
 */
const TELEMETRY_LIVE_WINDOW_MS = 30_000; // 30 s — match the STALE→OFFLINE boundary

function normaliseTimestamp(tel) {
  // If tel.timestamp is already in millisecond range (> 1e12) it was
  // incorrectly pre-multiplied upstream — use it directly.
  const raw = tel.timestamp;
  if (!Number.isFinite(raw)) return null;
  return raw > 1e12 ? raw : raw * 1000;
}

function telemetryToState(tel, receivedAt = null) {
  const sourceTimestamp = normaliseTimestamp(tel);

  let effectiveTimestamp;
  if (receivedAt != null) {
    // WS live path — use browser reception time (unchanged behaviour).
    effectiveTimestamp = receivedAt;
  } else if (sourceTimestamp != null) {
    // REST restore path — use browser time only when the source timestamp
    // indicates the edge was recently active; otherwise use the real
    // source time so the stale-check can fire correctly.
    const ageMs = Date.now() - sourceTimestamp;
    effectiveTimestamp = ageMs <= TELEMETRY_LIVE_WINDOW_MS ? Date.now() : sourceTimestamp;
  } else {
    effectiveTimestamp = Date.now();
  }

  return {
    ...tel,
    timestamp: effectiveTimestamp,
    source_timestamp: tel.source_timestamp,
    processed_timestamp: tel.processed_timestamp ?? tel.timestamp,
    analysis_session_id: tel.analysis_session_id || tel.stream_id,
    analysis_state: tel.analysis_state || 'PROCESSING',
  };
}

function dedupeEvents(items) {
  const seen = new Set();
  return items.filter(item => {
    const key = item?.event_id || item?.id;
    if (!key) return true;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
