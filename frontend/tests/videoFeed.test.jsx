import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import VideoFeed from '../src/components/VideoFeed';
import { authFetch } from '../src/services/auth';

vi.mock('../src/services/auth', () => ({ authFetch: vi.fn() }));

describe('per-camera analyzed-frame HUD', () => {
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

  it('shows the native preview with HUD off and the authoritative annotated frame with HUD on', async () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      mediaUrl="blob:video"
      telemetryStatus="LIVE"
      liveTracksData={{
        analysis_session_id: 'session-1', frame_index: 42, preview_available: true,
        person_count: 1, vehicle_count: 1, track_count: 2, tracks: [],
        frame_width: 768, frame_height: 576,
      }}
    />);

    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(authFetch.mock.calls[0][0]).toContain('hud=false');
    expect(screen.getByTitle('Toggle debug HUD')).toHaveAttribute('aria-pressed', 'false');
    expect(document.querySelector('video')).toBeInTheDocument();
    expect(screen.queryByAltText('Annotated analyzed frame for cam-border-01')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTitle('Toggle debug HUD'));
    await waitFor(() => expect(authFetch.mock.calls.some(([url]) => url.includes('hud=true'))).toBe(true));
    await waitFor(() => expect(screen.getByAltText('Annotated analyzed frame for cam-border-01')).toBeInTheDocument());
    expect(screen.getByTitle('Toggle debug HUD')).toHaveAttribute('aria-pressed', 'true');
  });
});
