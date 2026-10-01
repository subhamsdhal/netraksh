import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  state: null,
  retryStartupWake: vi.fn(),
}));

vi.mock('../src/hooks/useStartupReadiness', () => ({
  default: () => mocks.state,
}));

vi.mock('../src/services/startupWake', () => ({
  STARTUP_STATUS: {
    UNKNOWN: 'UNKNOWN',
    WAKING: 'WAKING',
    READY: 'READY',
    TIMEOUT: 'TIMEOUT',
  },
  retryStartupWake: mocks.retryStartupWake,
}));

import StartupGate from '../src/components/StartupGate';

function state(statuses) {
  return {
    allReady: Object.values(statuses).every((status) => status === 'READY'),
    backend: { status: statuses.backend },
    camBorder01: { status: statuses.camBorder01 },
    camCheckpoint01: { status: statuses.camCheckpoint01 },
  };
}

describe('StartupGate', () => {
  beforeEach(() => {
    mocks.retryStartupWake.mockReset();
  });

  it('keeps authenticated dashboard children unmounted while services warm', () => {
    mocks.state = state({
      backend: 'READY',
      camBorder01: 'WAKING',
      camCheckpoint01: 'WAKING',
    });

    render(<StartupGate><div>Protected Dashboard</div></StartupGate>);

    expect(screen.getByRole('heading', { name: 'NETRAKSH INITIALIZING' })).toBeInTheDocument();
    expect(screen.queryByText('Protected Dashboard')).not.toBeInTheDocument();
    expect(screen.getAllByText('WARMING')).toHaveLength(2);
  });

  it('mounts the dashboard only after all three services are ready', () => {
    mocks.state = state({
      backend: 'READY',
      camBorder01: 'READY',
      camCheckpoint01: 'READY',
    });

    render(<StartupGate><div>Protected Dashboard</div></StartupGate>);

    expect(screen.getByText('Protected Dashboard')).toBeInTheDocument();
    expect(screen.queryByText('NETRAKSH INITIALIZING')).not.toBeInTheDocument();
  });

  it('offers one coordinated retry when any service times out', () => {
    mocks.state = state({
      backend: 'READY',
      camBorder01: 'TIMEOUT',
      camCheckpoint01: 'READY',
    });

    render(<StartupGate><div>Protected Dashboard</div></StartupGate>);
    fireEvent.click(screen.getByRole('button', { name: 'RETRY STARTUP' }));

    expect(mocks.retryStartupWake).toHaveBeenCalledTimes(1);
  });
});
