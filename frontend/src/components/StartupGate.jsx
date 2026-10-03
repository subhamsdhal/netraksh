import React from 'react';
import useStartupReadiness from '../hooks/useStartupReadiness';
import { retryStartupWake, STARTUP_STATUS } from '../services/startupWake';

const labels = [
  ['backend', 'Backend Control Plane'],
  ['camBorder01', 'Camera Node 1'],
  ['camCheckpoint01', 'Camera Node 2'],
];

function displayStatus(status) {
  if (status === STARTUP_STATUS.TIMEOUT) return 'TIMEOUT';
  if (status === STARTUP_STATUS.READY) return 'READY';
  return 'WARMING';
}

export default function StartupGate({ children }) {
  const startup = useStartupReadiness();

  if (startup.admitted || startup.allReady) return children;

  const timedOut = labels.some(([key]) => startup[key].status === STARTUP_STATUS.TIMEOUT);
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
        <p>{timedOut ? 'One or more required services did not become ready.' : 'Starting required services…'}</p>
        {!timedOut && (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', lineHeight: 1.5 }}>
            Cloud services are starting. This can take up to 2 minutes on first launch. Please keep this tab open. If the screen remains here for more than 2 minutes, refresh the tab once.
          </p>
        )}
        {timedOut && (
          <button type="button" onClick={() => retryStartupWake()}>
            RETRY STARTUP
          </button>
        )}
      </section>
    </main>
  );
}
