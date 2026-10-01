import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Health from '../src/pages/Health';

vi.mock('../src/hooks/useWebSocket', () => ({
  default: () => ({
    isConnected: true,
    liveTracks: {},
    health: {
      'cam-test': {
        camera_id: 'cam-test',
        health_state: 'DEGRADED',
        health_reason: 'LOW_FPS',
        fps_actual: 7.5,
      },
    },
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
    json: async () => path === '/cameras' ? ([{
      camera_id: 'cam-test',
      location: 'Synthetic fixture',
      health_state: 'OK',
      health_reason: 'OK',
      fps_actual: 25,
      fps_declared: 25,
    }]) : path === '/ready' ? ({ status: 'ready', database: 'connected' })
      : path === '/system/capabilities' ? ({ evidence: { durable_storage: false }, blockchain: { simulated: true } })
        : path === '/sync/status' ? ({ queued: 0, failed: 0, has_activity: false })
          : ({ command_id: 'COMMAND_TEST' }),
  })),
}));

describe('Health REST/WebSocket contract', () => {
  it('merges health_state and fps_actual from the realtime payload', async () => {
    render(<Health />);
    expect((await screen.findAllByText('cam-test')).length).toBeGreaterThan(0);
    expect(screen.getByText('7.5')).toBeInTheDocument();
    expect(screen.getByText('LOW_FPS')).toBeInTheDocument();
    expect(screen.getByText('Local ephemeral storage is not durable')).toBeInTheDocument();
    expect(screen.getByText('SIMULATED / MOCK MODE')).toBeInTheDocument();
  });
});
