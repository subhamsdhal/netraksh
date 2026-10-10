// One browser-session coordinator for the three independent Render services.
// Startup only wakes and checks processes; it never starts camera analysis.

const backendUrl = String(import.meta.env.VITE_BACKEND_URL || '').replace(/\/$/, '');
const edgeService = (envName, cameraId) => {
  const baseUrl = String(import.meta.env[envName] || '').replace(/\/$/, '');
  return {
    url: baseUrl && `${baseUrl}/health`,
    wakeUrl: baseUrl && `${baseUrl}/wake`,
    kind: 'edge',
    cameraId,
  };
};

const configuredServices = {
  backend: { url: backendUrl && `${backendUrl}/ready`, wakeUrl: backendUrl && `${backendUrl}/ready`, kind: 'backend' },
  camBorder01: edgeService('VITE_EDGE_WAKE_URL_CAM_BORDER_01', 'cam-border-01'),
  camCheckpoint01: edgeService('VITE_EDGE_WAKE_URL_CAM_CHECKPOINT_01', 'cam-checkpoint-01'),
};

const SERVICE_KEYS = Object.freeze(['backend', 'camBorder01', 'camCheckpoint01']);
export const STARTUP_STATUS = Object.freeze({
  UNKNOWN: 'UNKNOWN',
  WAKING: 'WAKING',
  RETRYING: 'RETRYING',
  READY: 'READY',
  TIMEOUT: 'TIMEOUT',
});

const DEFAULT_MAX_STARTUP_MS = 240_000;
const DEFAULT_POLL_INTERVAL_MS = 5_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 15_000;
const MAX_RETRY_BACKOFF_MS = 20_000;
export const RESUME_AFTER_MS = 60_000;

function initialSnapshot() {
  return {
    requested: false,
    backend: { status: STARTUP_STATUS.UNKNOWN },
    camBorder01: { status: STARTUP_STATUS.UNKNOWN },
    camCheckpoint01: { status: STARTUP_STATUS.UNKNOWN },
    allReady: false,
    admitted: false,
    revalidating: false,
    lastReadyEdgeCount: 0,
    startedAt: null,
    readyAt: null,
    lastReadyAt: null,
  };
}

function backendReady(response, payload) {
  return Boolean(
    response?.status === 200
    && response?.ok
    && payload && typeof payload === 'object' && !Array.isArray(payload)
    && payload.status === 'ready'
    && payload.database === 'connected',
  );
}

function edgeReady(response, payload, expectedCameraId) {
  return Boolean(
    response?.status === 200
    && response?.ok
    && payload && typeof payload === 'object' && !Array.isArray(payload)
    && payload.camera_id === expectedCameraId
    && payload.worker_alive === true
    && !payload.last_error,
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
  const sleepResolvers = new Map();
  const inFlight = new Map();
  let retryAttempts = new Map();
  let nextProbeAt = new Map();
  let wakeSent = new Set();

  const clearAllTimers = () => {
    timers.forEach((timer) => {
      clearTimer(timer);
      const resolve = sleepResolvers.get(timer);
      if (resolve) resolve();
    });
    timers.clear();
    sleepResolvers.clear();
  };

  const publish = (updates = {}) => {
    snapshot = { ...snapshot, ...updates };
    snapshot.allReady = SERVICE_KEYS.every((key) => snapshot[key].status === STARTUP_STATUS.READY);
    if (snapshot.allReady && !snapshot.readyAt) {
      const completedAt = now();
      snapshot.readyAt = completedAt;
      snapshot.lastReadyAt = completedAt;
      snapshot.lastReadyEdgeCount = 2;
      snapshot.revalidating = false;
      snapshot.admitted = true;
      inFlight.forEach(({ controller }) => controller.abort());
      clearAllTimers();
    }
    listeners.forEach((listener) => listener(snapshot));
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('netraksh:startup-wake', { detail: snapshot }));
    }
    return snapshot;
  };

  const sleep = (delay) => new Promise((resolve) => {
    const timer = setTimer(() => {
      timers.delete(timer);
      sleepResolvers.delete(timer);
      resolve();
    }, delay);
    timers.add(timer);
    sleepResolvers.set(timer, resolve);
  });

  const launchProbe = (key, generation, { wake = false } = {}) => {
    if (inFlight.has(key)) return inFlight.get(key).promise;
    const service = services[key];
    const url = wake && !wakeSent.has(key) ? service?.wakeUrl : service?.url;
    if (!url) {
      publish({ [key]: { status: STARTUP_STATUS.RETRYING, detail: 'Service URL is not configured.' } });
      return Promise.resolve();
    }
    if (wake) wakeSent.add(key);

    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimer(() => {
      timedOut = true;
      controller.abort();
    }, requestTimeoutMs);
    timers.add(timeout);
    let request;
    try {
      request = fetchImpl(url, { cache: 'no-store', signal: controller.signal });
    } catch {
      request = Promise.reject(new Error('request failed'));
    }
    const promise = Promise.resolve(request).then(async (response) => {
      let payload = null;
      try { payload = await response.json(); } catch { payload = null; }
      const classified = classifyStartupResponse(service, response, payload);
      if (classified === STARTUP_STATUS.READY) {
        retryAttempts.set(key, 0);
        nextProbeAt.set(key, 0);
        return { status: STARTUP_STATUS.READY, payload, checkedAt: now() };
      }
      const retryable = !response.ok || response.status === 429 || !payload || typeof payload !== 'object';
      if (retryable) {
        const attempts = (retryAttempts.get(key) || 0) + 1;
        retryAttempts.set(key, attempts);
        const backoff = Math.min(pollIntervalMs * (2 ** Math.min(attempts - 1, 4)), MAX_RETRY_BACKOFF_MS);
        nextProbeAt.set(key, now() + backoff);
        return {
          status: STARTUP_STATUS.RETRYING,
          detail: response.status === 429 ? 'Service asked the browser to retry later (HTTP 429).' : `Health request returned HTTP ${response.status}.`,
          checkedAt: now(),
        };
      }
      retryAttempts.set(key, 0);
      nextProbeAt.set(key, 0);
      return { status: STARTUP_STATUS.WAKING, detail: 'Service responded and is still warming.', checkedAt: now() };
    }).catch(() => {
      if (generation !== cycleGeneration) return null;
      const attempts = (retryAttempts.get(key) || 0) + 1;
      retryAttempts.set(key, attempts);
      const backoff = Math.min(pollIntervalMs * (2 ** Math.min(attempts - 1, 4)), MAX_RETRY_BACKOFF_MS);
      nextProbeAt.set(key, now() + backoff);
      return {
        status: STARTUP_STATUS.RETRYING,
        detail: timedOut ? `Health request timed out after ${Math.round(requestTimeoutMs / 1000)} seconds.` : 'Health request failed or was blocked by the browser.',
        checkedAt: now(),
      };
    }).then((result) => {
      if (result && generation === cycleGeneration
        && snapshot[key].status !== STARTUP_STATUS.READY
        && snapshot[key].status !== STARTUP_STATUS.TIMEOUT) {
        publish({ [key]: result });
      }
      return result;
    }).finally(() => {
      clearTimer(timeout);
      timers.delete(timeout);
      if (inFlight.get(key)?.promise === promise) inFlight.delete(key);
    });
    inFlight.set(key, { controller, promise });
    return promise;
  };

  const dispatch = (keys, generation, { wake = false } = {}) => {
    keys.forEach((key) => launchProbe(key, generation, { wake }));
  };

  const runCycle = async (generation) => {
    const deadline = snapshot.startedAt + maxStartupMs;
    let unfinished = SERVICE_KEYS.filter((key) => snapshot[key].status !== STARTUP_STATUS.READY);

    dispatch(unfinished, generation, { wake: true });
    while (generation === cycleGeneration) {
      unfinished = SERVICE_KEYS.filter((key) => snapshot[key].status !== STARTUP_STATUS.READY);
      if (unfinished.length === 0) {
        clearAllTimers();
        return snapshot;
      }

      const remaining = deadline - now();
      if (remaining <= 0) {
        const updates = {};
        unfinished.forEach((key) => {
          updates[key] = { ...snapshot[key], status: STARTUP_STATUS.TIMEOUT };
        });
        publish({ ...updates, revalidating: false });
        clearAllTimers();
        return snapshot;
      }

      await sleep(Math.min(pollIntervalMs, remaining));
      if (generation !== cycleGeneration) return snapshot;
      const due = SERVICE_KEYS.filter((key) => (
        snapshot[key].status !== STARTUP_STATUS.READY
        && !inFlight.has(key)
        && (nextProbeAt.get(key) || 0) <= now()
      ));
      dispatch(due, generation);
    }
    return snapshot;
  };

  const start = ({ force = false } = {}) => {
    if (activeCycle) return activeCycle;
    if (snapshot.allReady && !force) return Promise.resolve(snapshot);

    clearAllTimers();
    inFlight.forEach(({ controller }) => controller.abort());
    inFlight.clear();
    retryAttempts = new Map();
    nextProbeAt = new Map();
    wakeSent = new Set(
      force
        ? SERVICE_KEYS.filter((key) => snapshot[key].status === STARTUP_STATUS.READY)
        : [],
    );
    const startedAt = now();
    const preserveReady = force && !snapshot.allReady;
    const priorReadyEdgeCount = ['camBorder01', 'camCheckpoint01'].filter(
      (key) => snapshot[key].status === STARTUP_STATUS.READY,
    ).length;
    const revalidating = Boolean(force && (snapshot.allReady || snapshot.lastReadyAt));
    const updates = Object.fromEntries(SERVICE_KEYS.map((key) => [
      key,
      preserveReady && snapshot[key].status === STARTUP_STATUS.READY
        ? snapshot[key]
        : { status: STARTUP_STATUS.WAKING },
    ]));
    publish({
      requested: true,
      ...updates,
      allReady: false,
      revalidating,
      lastReadyEdgeCount: revalidating
        ? Math.max(snapshot.lastReadyEdgeCount || 0, priorReadyEdgeCount)
        : 0,
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
    return () => {
      listeners.delete(listener);
      // React StrictMode may immediately remount the hook; defer cancellation
      // one microtask so a replacement subscriber can keep the same cycle.
      Promise.resolve().then(() => {
        if (listeners.size !== 0 || !activeCycle) return;
        cycleGeneration += 1;
        activeCycle = null;
        clearAllTimers();
        inFlight.forEach(({ controller }) => controller.abort());
        inFlight.clear();
      });
    };
  };

  const waitForBackend = () => {
    if (snapshot.backend.status === STARTUP_STATUS.READY) return Promise.resolve(snapshot);
    if (snapshot.backend.status === STARTUP_STATUS.TIMEOUT) {
      return Promise.reject(new Error('Required services did not become ready. Retry startup.'));
    }
    start();
    return new Promise((resolve, reject) => {
      const unsubscribe = subscribe((next) => {
        if (next.backend.status === STARTUP_STATUS.READY) {
          unsubscribe();
          resolve(next);
        } else if (next.backend.status === STARTUP_STATUS.TIMEOUT) {
          unsubscribe();
          reject(new Error('Required services did not become ready. Retry startup.'));
        }
      });
    });
  };

  const reset = () => {
    cycleGeneration += 1;
    activeCycle = null;
    clearAllTimers();
    inFlight.forEach(({ controller }) => controller.abort());
    inFlight.clear();
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

export function shouldRevalidateOnResume(state, now = Date.now()) {
  const lastActivity = state.readyAt || state.lastReadyAt || state.startedAt || 0;
  return lastActivity > 0 && now - lastActivity >= RESUME_AFTER_MS;
}

export function installStartupResumeHandlers() {
  if (resumeHandlersInstalled || typeof window === 'undefined' || typeof document === 'undefined') return;
  resumeHandlersInstalled = true;
  const resume = () => {
    const state = startupWakeState();
    if (shouldRevalidateOnResume(state)) requestStartupWake({ force: true });
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') resume();
  });
  window.addEventListener('online', resume);
}

export function __resetStartupWakeForTests() {
  coordinator.reset();
}
