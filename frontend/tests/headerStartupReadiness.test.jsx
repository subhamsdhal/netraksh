import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';

const mocks = vi.hoisted(() => ({
  snapshot: null,
  subscribe: vi.fn(() => () => {}),
  authFetch: vi.fn(),
  startupRequests: vi.fn(),
}));

vi.mock('../src/services/startupWake', () => ({
  startupWakeState: () => mocks.snapshot,
  subscribeStartupWake: mocks.subscribe,
  requestStartupWake: mocks.startupRequests,
}));

vi.mock('../src/hooks/useAuth', () => ({
  default: () => ({ isAuthenticated: true, role: 'ADMIN', username: 'admin' }),
}));

vi.mock('../src/hooks/useWebSocket', () => ({
  default: () => ({ isConnected: true, lastTelemetryAt: 0 }),
}));

vi.mock('../src/services/auth', () => ({
  BACKEND_URL: 'https://backend.example',
  WS_URL: 'wss://backend.example',
  logout: vi.fn(),
  authFetch: (...args) => mocks.authFetch(...args),
}));

import Header from '../src/components/Header';

function snapshot({ border = 'READY', checkpoint = 'READY', revalidating = false, lastReady = 2 } = {}) {
  return {
    requested: true,
    revalidating,
    lastReadyEdgeCount: lastReady,
    backend: { status: 'READY' },
    camBorder01: { status: border },
    camCheckpoint01: { status: checkpoint },
    allReady: border === 'READY' && checkpoint === 'READY',
  };
}

function RouteShell({ initial = '/watchlist' }) {
  return (
    <MemoryRouter initialEntries={[initial]}>
      <Header />
      <nav>
        <Link to="/watchlist">Watchlist route</Link>
        <Link to="/evidence">Evidence route</Link>
        <Link to="/map">Map route</Link>
        <Link to="/analytics">Analytics route</Link>
      </nav>
      <Routes>
        <Route path="/watchlist" element={<div>Watchlist module</div>} />
        <Route path="/evidence" element={<div>Evidence module</div>} />
        <Route path="/map" element={<div>Map module</div>} />
        <Route path="/analytics" element={<div>Analytics module</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('Header startup readiness hydration', () => {
  beforeEach(() => {
    mocks.snapshot = snapshot();
    mocks.subscribe.mockClear();
    mocks.startupRequests.mockClear();
    mocks.authFetch.mockResolvedValue({ ok: false });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
  });

  it.each(['/watchlist', '/evidence'])(
    'hydrates READY 2/2 immediately on direct %s load after startup completed',
    (initial) => {
      render(<RouteShell initial={initial} />);
      expect(screen.getByText('READY · 2/2')).toBeInTheDocument();
      expect(mocks.startupRequests).not.toHaveBeenCalled();
    },
  );

  it('never formats two configured warming edges as 0/0', () => {
    mocks.snapshot = snapshot({ border: 'WAKING', checkpoint: 'WAKING', lastReady: 0 });
    render(<RouteShell />);
    expect(screen.getByText('WARMING · 0/2')).toBeInTheDocument();
    expect(screen.queryByText('WARMING · 0/0')).not.toBeInTheDocument();
  });

  it('shows last-known readiness while a long-resume recheck begins', () => {
    mocks.snapshot = snapshot({ border: 'WAKING', checkpoint: 'WAKING', revalidating: true });
    render(<RouteShell />);
    expect(screen.getByText('RECHECKING · LAST READY 2/2')).toBeInTheDocument();
  });

  it('shows partial current revalidation progress', () => {
    mocks.snapshot = snapshot({ border: 'READY', checkpoint: 'WAKING', revalidating: true });
    render(<RouteShell />);
    expect(screen.getByText('RECHECKING · 1/2')).toBeInTheDocument();
  });

  it('retains readiness across module switches without requesting startup again', () => {
    render(<RouteShell />);
    for (const [link, module] of [
      ['Evidence route', 'Evidence module'],
      ['Map route', 'Map module'],
      ['Analytics route', 'Analytics module'],
      ['Watchlist route', 'Watchlist module'],
    ]) {
      fireEvent.click(screen.getByRole('link', { name: link }));
      expect(screen.getByText(module)).toBeInTheDocument();
      expect(screen.getByText('READY · 2/2')).toBeInTheDocument();
    }
    expect(mocks.startupRequests).not.toHaveBeenCalled();
  });
});
