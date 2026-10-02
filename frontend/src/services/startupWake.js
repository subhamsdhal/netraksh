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

const configuredPrewarm = {
  triggerUrl: backendUrl && `${backendUrl}/api/dashboard/startup/prewarm`,
  statusUrl: backendUrl && `${backendUrl}/api/dashboard/startup/prewarm/status`,
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
const DEFAULT_BACKEND_TIMEOUT_MS = 12_000;
const DEFAULT_EDGE_TIMEOUT_MS = 5_000;
const DEFAULT_PREWARM_TIMEOUT_MS = 8_000;
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
  prewarm = configuredPrewarm,
  fetchImpl = (...args) => fetch(...args),
  now = () => Date.now(),
  setTimer = (...args) => setTimeout(...args),
  clearTimer = (timer) => clearTimeout(timer),
  maxStartupMs = DEFAULT_MAX_STARTUP_MS,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  requestTimeoutMs = null,
  backendTimeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
  edgeTimeoutMs = DEFAULT_EDGE_TIMEOUT_MS,
  prewarmTimeoutMs = DEFAULT_PREWARM_TIMEOUT_MS,
} = {}) {
  let snapshot = initialSnapshot();
  let activeCycle = null;
  let cycleGeneration = 0;
  const listeners = new Set();
  const timers = new Set();
  const sleepResolvers = new Map();
  const inFlight = new Map();
  let prewarmAccepted = false;

  const publish = (updates = {}) => {
    snapshot = { ...snapshot, ...updates };
    snapshot.allReady = SERVICE_KEYS.every(
      (key) => snapshot[key].status === STARTUP_STATUS.READY,
    );
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

  const updateService = (key, result) => publish({ [key]: result });

  const clearAllTimers = () => {
    timers.forEach((timer) => {
      clearTimer(timer);
      const resolve = sleepResolvers.get(timer);
      if (resolve) resolve();
    });
    timers.clear();
    sleepResolvers.clear();
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

  const requestTimeoutFor = (service) => requestTimeoutMs
    ?? (service.kind === 'edge' ? edgeTimeoutMs : backendTimeoutMs);

  const launchProbe = (key, generation) => {
    if (inFlight.has(key)) return inFlight.get(key).promise;
    const service = services[key];
    if (!service?.url || service.url === '/wake') return Promise.resolve();

    const controller = new AbortController();
    const timeout = setTimer(() => controller.abort(), requestTimeoutFor(service));
    timers.add(timeout);
    let request;
    try {
      request = fetchImpl(service.url, {
        cache: 'no-store',
        signal: controller.signal,
      });
    } catch {
      request = Promise.reject(new Error('startup request failed'));
    }
    const promise = Promise.resolve(request).then(async (response) => {
      let payload = null;
      try { payload = await response.json(); } catch { payload = null; }
      return { status: classifyStartupResponse(service, response, payload), payload };
    }).catch(() => ({ status: STARTUP_STATUS.WAKING, payload: null })).then((result) => {
      if (generation === cycleGeneration
        && ![STARTUP_STATUS.READY, STARTUP_STATUS.TIMEOUT].includes(snapshot[key].status)) {
        updateService(key, result);
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

  const applyBackendAuthority = (payload) => {
    const mappings = [
      ['camBorder01', 'cam-border-01'],
      ['camCheckpoint01', 'cam-checkpoint-01'],
    ];
    mappings.forEach(([key, cameraId]) => {
      const item = payload?.cameras?.[cameraId];
      if (item?.camera_id === cameraId
        && item?.status === 'ready'
        && snapshot[key].status !== STARTUP_STATUS.TIMEOUT) {
        updateService(key, { status: STARTUP_STATUS.READY, payload: item, authority: 'backend' });
      }
    });
  };

  const launchPrewarmStatus = (generation) => {
    const key = 'prewarmStatus';
    if (!prewarm?.statusUrl || inFlight.has(key) || snapshot.allReady) return;
    const controller = new AbortController();
    const timeout = setTimer(() => controller.abort(), prewarmTimeoutMs);
    timers.add(timeout);
    let request;
    try {
      request = fetchImpl(prewarm.statusUrl, { cache: 'no-store', signal: controller.signal });
    } catch {
      request = Promise.reject(new Error('prewarm status request failed'));
    }
    const promise = Promise.resolve(request).then(async (response) => {
      if (!response.ok) return null;
      try { return await response.json(); } catch { return null; }
    }).then((payload) => {
      if (generation === cycleGeneration && payload) applyBackendAuthority(payload);
    }).catch(() => {}).finally(() => {
      clearTimer(timeout);
      timers.delete(timeout);
      if (inFlight.get(key)?.promise === promise) inFlight.delete(key);
    });
    inFlight.set(key, { controller, promise });
  };

  const launchPrewarmTrigger = (generation) => {
    const key = 'prewarmTrigger';
    if (!prewarm?.triggerUrl || inFlight.has(key) || prewarmAccepted) return;
    const controller = new AbortController();
    const timeout = setTimer(() => controller.abort(), prewarmTimeoutMs);
    timers.add(timeout);
    let request;
    try {
      request = fetchImpl(prewarm.triggerUrl, {
        method: 'POST', cache: 'no-store', signal: controller.signal,
      });
    } catch {
      request = Promise.reject(new Error('prewarm trigger request failed'));
    }
    const promise = Promise.resolve(request).then(async (response) => {
      if (!response.ok) return null;
      try { return await response.json(); } catch { return {}; }
    }).then((payload) => {
      if (generation !== cycleGeneration || payload === null) return;
      prewarmAccepted = true;
      applyBackendAuthority(payload);
      launchPrewarmStatus(generation);
    }).catch(() => {}).finally(() => {
      clearTimer(timeout);
      timers.delete(timeout);
      if (inFlight.get(key)?.promise === promise) inFlight.delete(key);
    });
    inFlight.set(key, { controller, promise });
  };

  const dispatch = (keys, generation) => {
    // Keep these calls synchronous and await-free: all direct requests plus
    // the redundant backend prewarm leave the browser in the first turn.
    keys.forEach((key) => launchProbe(key, generation));
    if (prewarmAccepted) launchPrewarmStatus(generation);
    else launchPrewarmTrigger(generation);
  };

  const runCycle = async (generation) => {
    const deadline = snapshot.startedAt + maxStartupMs;
    let unfinished = [...SERVICE_KEYS];

    dispatch(unfinished, generation);
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
        publish({ ...updates, revalidating: false });
        clearAllTimers();
        return snapshot;
      }

      await sleep(Math.min(pollIntervalMs, remaining));
      if (generation !== cycleGeneration) return snapshot;
      unfinished = SERVICE_KEYS.filter(
        (key) => snapshot[key].status !== STARTUP_STATUS.READY,
      );
      if (unfinished.length === 0) return snapshot;
      dispatch(unfinished, generation);
    }
    return snapshot;
  };

  const start = ({ force = false } = {}) => {
    if (activeCycle) return activeCycle;
    if (snapshot.allReady && !force) return Promise.resolve(snapshot);

    clearAllTimers();
    inFlight.forEach(({ controller }) => controller.abort());
    inFlight.clear();
    prewarmAccepted = false;
    const startedAt = now();
    const priorReadyEdgeCount = ['camBorder01', 'camCheckpoint01'].filter(
      (key) => snapshot[key].status === STARTUP_STATUS.READY,
    ).length;
    const revalidating = Boolean(force && (snapshot.allReady || snapshot.lastReadyAt));
    const waking = Object.fromEntries(
      SERVICE_KEYS.map((key) => [key, { status: STARTUP_STATUS.WAKING }]),
    );
    publish({
      requested: true,
      ...waking,
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
    return () => listeners.delete(listener);
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
    prewarmAccepted = false;
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
