// Coordinated, bounded cold-start readiness for the three independent Render
// services. This module only calls /ready and /wake; it never invokes camera
// control, uploads, analysis, telemetry, events, or evidence endpoints.

const backendUrl = String(import.meta.env.VITE_BACKEND_URL || '').replace(/\/$/, '');
const configuredServices = {
  backend: {
    url: backendUrl && `${backendUrl}/ready`,
    kind: 'backend',
  },
  camBorder01: {
    url: String(import.meta.env.VITE_EDGE_WAKE_URL_CAM_BORDER_01 || '').replace(/\/$/, '') + '/wake',
    kind: 'edge',
    cameraId: 'cam-border-01',
  },
  camCheckpoint01: {
    url: String(import.meta.env.VITE_EDGE_WAKE_URL_CAM_CHECKPOINT_01 || '').replace(/\/$/, '') + '/wake',
    kind: 'edge',
    cameraId: 'cam-checkpoint-01',
  },
};

const SERVICE_KEYS = Object.freeze(['backend', 'camBorder01', 'camCheckpoint01']);
export const STARTUP_STATUS = Object.freeze({
  UNKNOWN: 'UNKNOWN',
  WAKING: 'WAKING',
  READY: 'READY',
  TIMEOUT: 'TIMEOUT',
});

const DEFAULT_MAX_STARTUP_MS = 305_000;
const DEFAULT_POLL_INTERVAL_MS = 1_750;
const DEFAULT_REQUEST_TIMEOUT_MS = 12_000;
const RESUME_AFTER_MS = 60_000;

function initialSnapshot() {
  return {
    requested: false,
    backend: { status: STARTUP_STATUS.UNKNOWN },
    camBorder01: { status: STARTUP_STATUS.UNKNOWN },
    camCheckpoint01: { status: STARTUP_STATUS.UNKNOWN },
    allReady: false,
    startedAt: null,
    readyAt: null,
  };
}

function backendReady(response, payload) {
  return Boolean(
    response?.ok
    && payload?.status === 'ready'
    && payload?.database === 'connected',
  );
}

function edgeReady(response, payload, expectedCameraId) {
  return Boolean(
    response?.ok
    && payload?.camera_id === expectedCameraId
    && payload?.worker_alive === true
    && !payload?.last_error,
  );
}

export function classifyStartupResponse(service, response, payload) {
  if (service.kind === 'backend') {
    return backendReady(response, payload) ? STARTUP_STATUS.READY : STARTUP_STATUS.WAKING;
  }
  return edgeReady(response, payload, service.cameraId)
    ? STARTUP_STATUS.READY
    : STARTUP_STATUS.WAKING;
}

export function createStartupCoordinator({
  services = configuredServices,
  fetchImpl = (...args) => fetch(...args),
  now = () => Date.now(),
  setTimer = (...args) => setTimeout(...args),
  clearTimer = (timer) => clearTimeout(timer),
  maxStartupMs = DEFAULT_MAX_STARTUP_MS,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
} = {}) {
  let snapshot = initialSnapshot();
  let activeCycle = null;
  let cycleGeneration = 0;
  const listeners = new Set();
  const timers = new Set();

  const publish = (updates = {}) => {
    snapshot = { ...snapshot, ...updates };
    snapshot.allReady = SERVICE_KEYS.every(
      (key) => snapshot[key].status === STARTUP_STATUS.READY,
    );
    if (snapshot.allReady && !snapshot.readyAt) snapshot.readyAt = now();
    listeners.forEach((listener) => listener(snapshot));
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('netraksh:startup-wake', { detail: snapshot }));
    }
    return snapshot;
  };

  const updateService = (key, status) => publish({ [key]: { status } });

  const clearAllTimers = () => {
    timers.forEach((timer) => clearTimer(timer));
    timers.clear();
  };

  const sleep = (delay) => new Promise((resolve) => {
    const timer = setTimer(() => {
      timers.delete(timer);
      resolve();
    }, delay);
    timers.add(timer);
  });

  const probe = async (key) => {
    const service = services[key];
    if (!service?.url || service.url === '/wake') return STARTUP_STATUS.WAKING;

    const controller = new AbortController();
    const timeout = setTimer(() => controller.abort(), requestTimeoutMs);
    timers.add(timeout);
    try {
      // fetch() is invoked synchronously before the first await. dispatch()
      // constructs all probe promises first, preserving the three-way fanout.
      const request = fetchImpl(service.url, {
        cache: 'no-store',
        signal: controller.signal,
      });
      const response = await request;
      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      return classifyStartupResponse(service, response, payload);
    } catch {
      return STARTUP_STATUS.WAKING;
    } finally {
      clearTimer(timeout);
      timers.delete(timeout);
    }
  };

  const dispatch = async (keys, generation) => {
    // Do not insert an await between these calls. All unfinished services are
    // triggered from the same turn and then awaited together.
    const probes = keys.map((key) => ({ key, promise: probe(key) }));
    const results = await Promise.allSettled(probes.map(({ promise }) => promise));
    if (generation !== cycleGeneration) return;
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') updateService(probes[index].key, result.value);
    });
  };

  const runCycle = async (generation) => {
    const deadline = snapshot.startedAt + maxStartupMs;
    let unfinished = [...SERVICE_KEYS];

    await dispatch(unfinished, generation);
    while (generation === cycleGeneration) {
      unfinished = SERVICE_KEYS.filter(
        (key) => snapshot[key].status !== STARTUP_STATUS.READY,
      );
      if (unfinished.length === 0) {
        clearAllTimers();
        return snapshot;
      }

      const remaining = deadline - now();
      if (remaining <= 0) {
        const updates = {};
        unfinished.forEach((key) => { updates[key] = { status: STARTUP_STATUS.TIMEOUT }; });
        publish(updates);
        clearAllTimers();
        return snapshot;
      }

      await sleep(Math.min(pollIntervalMs, remaining));
      if (generation !== cycleGeneration) return snapshot;
      await dispatch(unfinished, generation);
    }
    return snapshot;
  };

  const start = ({ force = false } = {}) => {
    if (activeCycle) return activeCycle;
    if (snapshot.allReady && !force) return Promise.resolve(snapshot);

    clearAllTimers();
    const startedAt = now();
    const waking = Object.fromEntries(
      SERVICE_KEYS.map((key) => [key, { status: STARTUP_STATUS.WAKING }]),
    );
    publish({
      requested: true,
      ...waking,
      allReady: false,
      startedAt,
      readyAt: null,
    });
    const generation = ++cycleGeneration;
    activeCycle = runCycle(generation).finally(() => {
      if (generation === cycleGeneration) activeCycle = null;
    });
    return activeCycle;
  };

  const subscribe = (listener) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  };

  const waitForBackend = () => {
    if (snapshot.backend.status === STARTUP_STATUS.READY) return Promise.resolve(snapshot);
    if (snapshot.backend.status === STARTUP_STATUS.TIMEOUT) {
      return Promise.reject(new Error('Secure services did not become ready. Retry startup.'));
    }
    start();
    return new Promise((resolve, reject) => {
      const unsubscribe = subscribe((next) => {
        if (next.backend.status === STARTUP_STATUS.READY) {
          unsubscribe();
          resolve(next);
        } else if (next.backend.status === STARTUP_STATUS.TIMEOUT) {
          unsubscribe();
          reject(new Error('Secure services did not become ready. Retry startup.'));
        }
      });
    });
  };

  const reset = () => {
    cycleGeneration += 1;
    activeCycle = null;
    clearAllTimers();
    snapshot = initialSnapshot();
  };

  return {
    getSnapshot: () => snapshot,
    start,
    waitForBackend,
    subscribe,
    reset,
    hasActiveCycle: () => Boolean(activeCycle),
    pendingTimerCount: () => timers.size,
  };
}

const coordinator = createStartupCoordinator();
let resumeHandlersInstalled = false;

export function startupWakeState() {
  return coordinator.getSnapshot();
}

export function subscribeStartupWake(listener) {
  return coordinator.subscribe(listener);
}

export function requestStartupWake(options) {
  return coordinator.start(options);
}

export function retryStartupWake() {
  return coordinator.start({ force: true });
}

export function waitForBackendReady() {
  return coordinator.waitForBackend();
}

export function installStartupResumeHandlers() {
  if (resumeHandlersInstalled || typeof window === 'undefined' || typeof document === 'undefined') return;
  resumeHandlersInstalled = true;
  const resume = () => {
    const state = startupWakeState();
    const lastActivity = state.readyAt || state.startedAt || 0;
    if (Date.now() - lastActivity >= RESUME_AFTER_MS) requestStartupWake({ force: true });
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') resume();
  });
  window.addEventListener('online', resume);
}

export function __resetStartupWakeForTests() {
  coordinator.reset();
}
