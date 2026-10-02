import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Health from '../src/pages/Health';

let cameraFixture;
let healthFixture;

vi.mock('../src/hooks/useWebSocket', () => ({
  default: () => ({
    isConnected: true,
    liveTracks: {},
    health: healthFixture,
  }),
}));

vi.mock('../src/hooks/useStartupReadiness', () => ({
  default: () => ({
    camBorder01: { status: 'READY' },
    camCheckpoint01: { status: 'READY' },
  }),
}));

vi.mock('../src/services/auth', () => ({
  WS_URL: 'ws://test/ws/dashboard',
  authFetch: vi.fn(async (path) => ({
    ok: true, status: 200,
    json: async () => path === '/cameras' ? ([cameraFixture]) : path === '/ready' ? ({ status: 'ready', database: 'connected' })
      : path === '/system/capabilities' ? ({ evidence: { durable_storage: false }, blockchain: { simulated: true } })
        : path === '/sync/status' ? ({ queued: 0, failed: 0, has_activity: false })
          : ({ command_id: 'COMMAND_TEST' }),
  })),
}));

describe('Health REST/WebSocket contract', () => {
  beforeEach(() => {
    cameraFixture = {
      camera_id: 'cam-border-01',
      location: 'Synthetic fixture',
    };
    healthFixture = {};
  });

  it('shows a fresh realtime health sample as current with formatted FPS', async () => {
    healthFixture = {
      'cam-border-01': {
        health_state: 'DEGRADED',
        health_reason: 'fps_degraded',
        fps_actual: 8.19093347220414,
        last_health_check: new Date(Date.now() - 4_000).toISOString(),
      },
    };
    render(<Health />);
    expect((await screen.findAllByText('cam-border-01')).length).toBeGreaterThan(0);
    expect(screen.getByText('8.19')).toBeInTheDocument();
    expect(screen.getByText('fps_degraded')).toBeInTheDocument();
    expect(screen.queryByText(/STALE/)).not.toBeInTheDocument();
    expect(screen.getByText('Local ephemeral storage is not durable')).toBeInTheDocument();
    expect(screen.getByText('SIMULATED / MOCK MODE')).toBeInTheDocument();
  });

  it('marks an old sample stale without implying its health or FPS is current', async () => {
    healthFixture = {
      'cam-border-01': {
        health_state: 'DEGRADED',
        health_reason: 'fps_degraded',
        fps_actual: 0.24055288578429176,
        last_health_check: new Date(Date.now() - 60_000).toISOString(),
      },
    };
    render(<Health />);
    await screen.findByText('STALE · LAST MEASURED DEGRADED');
    expect(screen.getByText('N/A CURRENT')).toBeInTheDocument();
    expect(screen.getByText('Last measured: 0.24 FPS')).toBeInTheDocument();
    expect(screen.getByText('Last measured: fps_degraded')).toBeInTheDocument();
  });

  it('reports missing samples without inventing zero values', async () => {
    render(<Health />);
    await screen.findByText('NOT REPORTED');
    expect(screen.getAllByText('N/A')).toHaveLength(2);
    expect(screen.getByText('Never')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('keeps a ready edge and idle analysis independent from stale health', async () => {
    healthFixture = {
      'cam-border-01': {
        health_state: 'DEGRADED',
        health_reason: 'fps_degraded',
        fps_actual: 8.19093347220414,
        last_health_check: new Date(Date.now() - 31_000).toISOString(),
      },
    };
    render(<Health />);
    await screen.findByText('STALE · LAST MEASURED DEGRADED');
    expect(screen.getAllByText('READY').length).toBeGreaterThan(0);
    expect(screen.getAllByText('IDLE').length).toBeGreaterThan(0);
    expect(screen.getByText('Last measured: 8.19 FPS')).toBeInTheDocument();
  });

  it('treats an invalid measurement timestamp as stale', async () => {
    healthFixture = {
      'cam-border-01': {
        health_state: 'DEGRADED',
        health_reason: 'fps_degraded',
        fps_actual: 7.5,
        last_health_check: 'not-a-timestamp',
      },
    };
    render(<Health />);
    await screen.findByText('STALE · LAST MEASURED DEGRADED');
    expect(screen.getByText('Invalid timestamp · STALE')).toBeInTheDocument();
  });
});
