import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/services/auth', () => ({
  authFetch: vi.fn(),
  getToken: () => 'jwt-test',
  logout: vi.fn(),
}));

import useWebSocket from '../src/hooks/useWebSocket';

class FakeWebSocket {
  static instances = [];
  constructor(url, protocols) {
    this.url = url;
    this.protocols = protocols;
    this.readyState = 1;
    FakeWebSocket.instances.push(this);
  }
  send = vi.fn();
  close = vi.fn();
}

describe('dashboard WebSocket processing', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    global.WebSocket = FakeWebSocket;
  });

  it('keeps JWT out of the URL and processes the health contract', async () => {
    const { result } = renderHook(() => useWebSocket('ws://backend/ws/dashboard', { fetchInitial: false }));
    const socket = FakeWebSocket.instances[0];
    expect(socket.url).toBe('ws://backend/ws/dashboard');
    expect(socket.protocols).toEqual(['netraksh.jwt', 'jwt-test']);

    act(() => socket.onopen());
    await waitFor(() => expect(result.current.isConnected).toBe(true));

    act(() => socket.onmessage({ data: JSON.stringify({
      type: 'camera_health',
      health: { camera_id: 'cam-test', health_state: 'DEGRADED', fps_actual: 7.5 },
    }) }));
    await waitFor(() => expect(result.current.health['cam-test'].fps_actual).toBe(7.5));
  });
});
