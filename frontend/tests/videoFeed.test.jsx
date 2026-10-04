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
    global.Image = class {
      set src(_value) { queueMicrotask(() => this.onload?.()); }
    };
    const headers = new Headers({
      'X-Analysis-Session': 'session-1', 'X-Frame-Index': '42',
      'X-Person-Count': '1', 'X-Vehicle-Count': '1', 'X-Track-Count': '2',
    });
    authFetch.mockResolvedValue({ ok: true, headers, blob: async () => new Blob(['jpeg']) });
  });

  it('defaults durable uploads to the authoritative analyzed frame and can switch to source preview', async () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      expectedSessionId="session-1"
      telemetryStatus="LIVE"
      liveTracksData={{
        stream_id: 'session-1',
        analysis_session_id: 'session-1', frame_index: 42, preview_available: true,
        person_count: 1, vehicle_count: 1, track_count: 2, tracks: [],
        frame_width: 768, frame_height: 576,
      }}
    />);

    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(authFetch.mock.calls[0][0]).toContain('hud=true');
    expect(screen.getByTitle('Toggle debug HUD')).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(screen.getByAltText('Annotated analyzed frame for cam-border-01')).toBeInTheDocument());
    expect(screen.getByText(/LATEST ANALYZED FRAME · FRAME 42/)).toBeInTheDocument();
    screen.getByTitle('Toggle debug HUD').click();
    await waitFor(() => expect(screen.getByText(/SOURCE PREVIEW · AI SAMPLE AVAILABLE · FRAME 42/)).toBeInTheDocument());
    expect(authFetch.mock.calls.every(([url]) => !url.includes('demo-telemetry'))).toBe(true);
  });

  it('does not fetch a frame for a stale session', async () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      expectedSessionId="new-session"
      telemetryStatus="LIVE"
      liveTracksData={{ stream_id: 'old-session', analysis_session_id: 'old-session', frame_index: 42, preview_available: true }}
    />);
    expect(authFetch).not.toHaveBeenCalled();
    expect(screen.getByText(/SOURCE PREVIEW · WAITING FOR FIRST ANALYZED FRAME/)).toBeInTheDocument();
  });

  it('does not offer an add-source action while durable authority is restoring', () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      sourceRestoring
      sourceRunState="RESTORING"
      canUpload
    />);
    expect(screen.getByText('RESTORING STORED SOURCE...')).toBeInTheDocument();
    expect(screen.queryByText('ADD VIDEO SOURCE')).not.toBeInTheDocument();
  });

  it('never calls an authoritative stored source NO VIDEO SOURCE when preview transport is absent', () => {
    render(<VideoFeed
      cameraId="cam-checkpoint-01"
      sourceMode="durable"
      sourceRunState="PAUSED"
      expectedSessionId="stored-source"
      telemetryStatus="STALE"
      canUpload
    />);
    expect(screen.getByText('SOURCE STORED · PREVIEW UNAVAILABLE FOR RESTORED SESSION')).toBeInTheDocument();
    expect(screen.queryByText('NO VIDEO SOURCE')).not.toBeInTheDocument();
    expect(screen.queryByText('ADD VIDEO SOURCE')).not.toBeInTheDocument();
  });

  it('shows measured upload progress and never claims normalization before it is known', () => {
    render(<VideoFeed
      cameraId="cam-checkpoint-01"
      isUploading
      uploadStage="UPLOADING"
      uploadProgress={63}
      canUpload
      sourceMode="durable"
      sourceRunState="UPLOADING"
    />);
    expect(screen.getByText('UPLOADING 63%')).toBeInTheDocument();
    expect(screen.queryByText(/NORMALIZING/)).not.toBeInTheDocument();
  });

  it('keeps preview availability separate from source readiness', () => {
    render(<VideoFeed
      cameraId="cam-checkpoint-01"
      sourceMode="durable"
      sourceRunState="READY"
      expectedSessionId="ready-source"
      telemetryStatus="WAITING"
      canUpload
    />);
    expect(screen.getByText('SOURCE STORED · PREVIEW UNAVAILABLE FOR RESTORED SESSION')).toBeInTheDocument();
    expect(screen.queryByText(/UPLOADING/)).not.toBeInTheDocument();
  });

  it('names an active restored source as awaiting its current analyzed frame', () => {
    render(<VideoFeed
      cameraId="cam-checkpoint-01"
      sourceMode="durable"
      sourceRunState="LIVE"
      expectedSessionId="stored-source"
      telemetryStatus="OFFLINE"
      canUpload
    />);
    expect(screen.getByText('SOURCE STORED · AWAITING CURRENT-RUN ANALYZED FRAME')).toBeInTheDocument();
    expect(screen.queryByText('SOURCE STORED · PREVIEW UNAVAILABLE FOR RESTORED SESSION')).not.toBeInTheDocument();
  });

  it('labels persisted completed telemetry as historical rather than active', () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      sourceMode="durable"
      sourceRunState="COMPLETED"
      expectedSessionId="session-1"
      telemetryStatus="COMPLETED"
      liveTracksData={{ analysis_session_id: 'session-1', frame_index: 42 }}
    />);
    expect(screen.getByText('SOURCE STORED · ANALYSIS COMPLETED')).toBeInTheDocument();
    expect(screen.queryByText('TELEMETRY ACTIVE · LOCAL PLAYBACK OPTIONAL')).not.toBeInTheDocument();
  });

  it('does not say a completed source is waiting for its first analyzed frame', () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      sourceRunState="COMPLETED"
      expectedSessionId="source-1"
      telemetryStatus="COMPLETED"
      liveTracksData={{ stream_id: 'source-1', analysis_session_id: 'run-1', frame_index: 42, preview_available: false }}
    />);
    expect(screen.getByText('SOURCE PREVIEW · COMPLETED RUN · ANALYZED FRAME UNAVAILABLE')).toBeInTheDocument();
    expect(screen.queryByText('SOURCE PREVIEW · WAITING FOR FIRST ANALYZED FRAME')).not.toBeInTheDocument();
    expect(screen.getByTitle('Analyzed frame unavailable')).toBeDisabled();
  });

  it('uses the active label only for live telemetry', () => {
    const { rerender } = render(<VideoFeed
      cameraId="cam-border-01"
      telemetryStatus="LIVE"
      liveTracksData={{ analysis_session_id: 'session-1', frame_index: 42 }}
    />);
    expect(screen.getByText('TELEMETRY ACTIVE · LOCAL PLAYBACK OPTIONAL')).toBeInTheDocument();

    rerender(<VideoFeed
      cameraId="cam-border-01"
      telemetryStatus="STALE"
      liveTracksData={{ analysis_session_id: 'session-1', frame_index: 42 }}
    />);
    expect(screen.getByText('LAST TELEMETRY AVAILABLE · NOT LIVE')).toBeInTheDocument();
    expect(screen.queryByText('TELEMETRY ACTIVE · LOCAL PLAYBACK OPTIONAL')).not.toBeInTheDocument();
  });
});
