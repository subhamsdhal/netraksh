// A page-load wake hint for the three independent free Render services.  This
// is deliberately not a control action: it never creates or changes a video
// scenario, analysis session, event, or camera generation.
const backendUrl = String(import.meta.env.VITE_BACKEND_URL || '').replace(/\/$/, '');
const edgeUrls = [
  import.meta.env.VITE_EDGE_WAKE_URL_CAM_BORDER_01,
  import.meta.env.VITE_EDGE_WAKE_URL_CAM_CHECKPOINT_01,
].map((url) => String(url || '').replace(/\/$/, '')).filter(Boolean);

let startupWakePromise = null;
let startupWakeRequested = false;

export function startupWakeState() {
  return { requested: startupWakeRequested };
}

export function createStartupWakeRequests({ backend = backendUrl, edges = edgeUrls } = {}) {
  return [
    backend && fetch(`${String(backend).replace(/\/$/, '')}/ready`, { cache: 'no-store' }),
    ...edges.filter(Boolean).map((url) => fetch(`${String(url).replace(/\/$/, '')}/wake`, { cache: 'no-store' })),
  ].filter(Boolean);
}

export function requestStartupWake() {
  if (startupWakePromise) return startupWakePromise;
  startupWakeRequested = true;
  const requests = createStartupWakeRequests();
  // allSettled makes this a best-effort early cold-start signal. The
  // authenticated backend prewarm remains the source of readiness truth.
  startupWakePromise = Promise.allSettled(requests).then((results) => {
    window.dispatchEvent(new CustomEvent('netraksh:startup-wake', {
      detail: { requested: true, results: results.map((result) => result.status) },
    }));
    return results;
  });
  return startupWakePromise;
}

export function __resetStartupWakeForTests() {
  startupWakePromise = null;
  startupWakeRequested = false;
}
