import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Health from '../src/pages/Health';

vi.mock('../src/hooks/useWebSocket', () => ({
  default: () => ({
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

vi.mock('../src/services/auth', () => ({
  WS_URL: 'ws://test/ws/dashboard',
  authFetch: vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ([{
      camera_id: 'cam-test',
      location: 'Synthetic fixture',
      health_state: 'OK',
      health_reason: 'OK',
      fps_actual: 25,
      fps_declared: 25,
    }]),
  })),
}));

describe('Health REST/WebSocket contract', () => {
  it('merges health_state and fps_actual from the realtime payload', async () => {
    render(<Health />);
    expect(await screen.findByText('cam-test')).toBeInTheDocument();
    expect(screen.getByText('7.5')).toBeInTheDocument();
    expect(screen.getByText('LOW_FPS')).toBeInTheDocument();
  });
});
