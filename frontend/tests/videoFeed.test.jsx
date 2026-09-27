import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import VideoFeed from '../src/components/VideoFeed';
import { authFetch } from '../src/services/auth';

vi.mock('../src/services/auth', () => ({ authFetch: vi.fn() }));

describe('per-camera authoritative analyzed frame', () => {
  beforeEach(() => {
    global.ResizeObserver = class { observe() {} disconnect() {} };
    URL.createObjectURL = vi.fn(() => 'blob:analyzed-frame');
    URL.revokeObjectURL = vi.fn();
    const headers = new Headers({
      'X-Analysis-Session': 'session-1', 'X-Frame-Index': '42',
      'X-Person-Count': '1', 'X-Vehicle-Count': '1', 'X-Track-Count': '2',
    });
    authFetch.mockResolvedValue({ ok: true, headers, blob: async () => new Blob(['jpeg']) });
  });

  it('shows the authoritative annotated frame for a durable source without relying on HUD', async () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      expectedSessionId="session-1"
      telemetryStatus="LIVE"
      liveTracksData={{
        analysis_session_id: 'session-1', frame_index: 42, preview_available: true,
        person_count: 1, vehicle_count: 1, track_count: 2, tracks: [],
        frame_width: 768, frame_height: 576,
      }}
    />);

    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(authFetch.mock.calls[0][0]).toContain('hud=true');
    expect(screen.getByTitle('Toggle debug HUD')).toHaveAttribute('aria-pressed', 'false');
    await waitFor(() => expect(screen.getByAltText('Annotated analyzed frame for cam-border-01')).toBeInTheDocument());
    expect(screen.getByText(/LATEST ANALYZED FRAME · FRAME 42/)).toBeInTheDocument();
    expect(authFetch.mock.calls.every(([url]) => !url.includes('demo-telemetry'))).toBe(true);
  });

  it('does not fetch a frame for a stale session', async () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      expectedSessionId="new-session"
      telemetryStatus="LIVE"
      liveTracksData={{ analysis_session_id: 'old-session', frame_index: 42, preview_available: true }}
    />);
    expect(authFetch).not.toHaveBeenCalled();
    expect(screen.getByText(/SOURCE PREVIEW · NORMALIZED USER UPLOAD/)).toBeInTheDocument();
  });
});
