import React, { useEffect, useState } from 'react';
import useStartupReadiness from '../hooks/useStartupReadiness';
import { retryStartupWake, STARTUP_STATUS } from '../services/startupWake';

const labels = [
  ['backend', 'Backend Control Plane'],
  ['camBorder01', 'Camera Node 1'],
  ['camCheckpoint01', 'Camera Node 2'],
];

function displayStatus(status) {
  if (status === STARTUP_STATUS.TIMEOUT) return 'UNAVAILABLE';
  if (status === STARTUP_STATUS.RETRYING) return 'RETRYING';
  if (status === STARTUP_STATUS.READY) return 'READY';
  return 'WARMING';
}

export default function StartupGate({ children }) {
  const startup = useStartupReadiness();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  if (startup.admitted || startup.allReady) return children;

  const timedOut = labels.some(([key]) => startup[key].status === STARTUP_STATUS.TIMEOUT);
  const elapsedSeconds = startup.startedAt ? Math.max(0, Math.floor((now - startup.startedAt) / 1000)) : 0;
  return (
    <main
      aria-label="NETRAKSH startup readiness"
      style={{
        minHeight: '100vh', display: 'grid', placeItems: 'center', padding: '2rem',
        background: '#08101d', color: '#e6f3ff', fontFamily: 'monospace',
      }}
    >
      <section style={{ width: 'min(42rem, 100%)', border: '1px solid #244762', padding: '2rem' }}>
        <h1 style={{ letterSpacing: '0.14em', marginTop: 0 }}>NETRAKSH INITIALIZING</h1>
        <div style={{ display: 'grid', gap: '0.9rem', margin: '2rem 0' }}>
          {labels.map(([key, label]) => (
            <div key={key} style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
              <span>{label}</span>
              <strong>{displayStatus(startup[key].status)}</strong>
            </div>
          ))}
        </div>
        <p role="status">Elapsed: {Math.floor(elapsedSeconds / 60)}:{String(elapsedSeconds % 60).padStart(2, '0')}</p>
        {elapsedSeconds >= 60 && !timedOut && (
          <p>Services are taking longer than expected to start.</p>
        )}
        {!timedOut && elapsedSeconds < 60 && <p>Waking and checking all three services concurrently…</p>}
        {labels.map(([key, label]) => startup[key].detail && (
          <p key={`${key}-detail`} style={{ color: 'var(--text-muted)', fontSize: '0.8rem', lineHeight: 1.5 }}>
            {label}: {startup[key].detail}
          </p>
        ))}
        {timedOut && (
          <>
            <p>One or more required services did not become ready. Check the service status and retry.</p>
            <button type="button" onClick={() => retryStartupWake()}>
            RETRY STARTUP
            </button>
          </>
        )}
      </section>
    </main>
  );
}
